import math
import pandas as pd
import config
import schema
from features import dataset_build
import geopandas as gpd
import requests
from shapely.geometry import Point

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def cell_area_km2(latitude,size_deg=schema.GRID_SIZE_DEG):
    km_per_degree = 111.32
    return (size_deg * km_per_degree) ** 2 * math.cos(math.radians(latitude))

def load_provinces(verbose=True):
    path = config.PROVINCES_PATH
    if not path.exists():
        if verbose:
            print(f"Downloading province borders from {config.PROVINCES_URL} ...")
        path.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(config.PROVINCES_URL, timeout=300)
        response.raise_for_status()
        path.write_bytes(response.content)

    provinces = gpd.read_file(path)
    provinces = provinces[provinces["adm0_a3"].isin(config.STUDY_COUNTRIES)]
    provinces = provinces[["adm0_a3", "name_en", "geometry"]]
    provinces = provinces.rename(columns={"adm0_a3": "country", "name_en": "province"})
    return provinces.reset_index(drop=True)
    
def province_for_cells(cells,provinces,max_distance_km=config.COASTAL_MAX_DISTANCE_KM):
    points = []
    for lon, lat in zip(cells["longitude"], cells["latitude"]):
        points.append(Point(lon, lat))
    point_table = gpd.GeoDataFrame(cells[[]].reset_index(drop=True), geometry=points, crs="EPSG:4326")

    inside = gpd.sjoin(point_table, provinces[["province", "geometry"]].to_crs("EPSG:4326"),
                       how="left", predicate="within")
    inside = inside[~inside.index.duplicated(keep="first")]
    result = inside["province"].values.copy()

    # Centres in the sea: nearest province (distances in metres, Web Mercator)
    missing = pd.isna(result)
    if missing.sum() > 0:
        near = gpd.sjoin_nearest(point_table[missing].to_crs("EPSG:3857"),
                                 provinces[["province", "geometry"]].to_crs("EPSG:3857"),
                                 how="left", max_distance=max_distance_km * 1000)
        near = near[~near.index.duplicated(keep="first")]
        result[missing] = near["province"].values
    return result

def build_cell_table(verbose=True):
    cells = dataset_build.load_cell_countries()
    cells = cells[cells["in_study_area"] == 1].reset_index(drop=True)
    cells = cells[["grid_id", "latitude", "longitude", "country"]]

    landcover = pd.read_parquet(config.PROCESSED_FILES["landcover_cells"])
    landcover = landcover[["grid_id", "land_cover_dominant", "forest_pct", "grassland_pct",
                           "cropland_pct", "other_pct"]]
    cells = cells.merge(landcover, on="grid_id", how="left")

    areas = []
    for lat in cells["latitude"]:
        areas.append(cell_area_km2(lat))
    cells["area_km2"] = areas

    cells["province"] = province_for_cells(cells, load_provinces(verbose=verbose))

    if verbose:
        print(f"Grid cells in the study area: {len(cells):,} "
              f"({cells['area_km2'].sum():,.0f} km2, {cells['province'].nunique()} provinces)")
        n_no_province = int(cells["province"].isna().sum())
        if n_no_province > 0:
            print(f"  {n_no_province} cell(s) without a province")
    return cells

def add_cell_info(totals,cells,columns):
    return totals.merge(cells[["grid_id"] + columns], on="grid_id", how="left")

def monthly_fire_totals(years=None,verbose=True):
    if years is None:
        years = config.PROCESSING_YEARS

    pieces = []
    for year in years:
        table = dataset_build.load_analysis_dataset(years=[year], columns=["grid_id", "month", "fire", "hotspot_count"])
        summed = table.groupby(["grid_id", "month"]).agg(fire_days=("fire", "sum"), hotspots=("hotspot_count", "sum"))
        summed = summed.reset_index()
        summed["year"] = year
        pieces.append(summed)
        del table

    totals = pd.concat(pieces, ignore_index=True)
    if verbose:
        print(f"Monthly totals: {len(totals):,} rows | {int(totals['hotspots'].sum()):,} hotspots, "
              f"{int(totals['fire_days'].sum()):,} fire cell-days, {len(years)} years")
    return totals

def country_summary(totals,cells):
    n_years = totals["year"].nunique()
    with_country = add_cell_info(totals, cells, ["country"])

    sums = with_country.groupby("country").agg(hotspots=("hotspots", "sum"), fire_days=("fire_days", "sum"))
    size = cells.groupby("country").agg(cells=("grid_id", "count"), area_km2=("area_km2", "sum"))
    table = size.join(sums)

    table["hotspots_per_year"] = (table["hotspots"] / n_years).round(0)
    table["hotspots_per_1000km2"] = (table["hotspots"] / n_years / table["area_km2"] * 1000).round(1)
    table["fire_days_per_cell"] = (table["fire_days"] / n_years / table["cells"]).round(2)
    table["rank_by_total"] = table["hotspots_per_year"].rank(ascending=False).astype("int64")
    table["rank_by_density"] = table["hotspots_per_1000km2"].rank(ascending=False).astype("int64")

    table["area_km2"] = table["area_km2"].round(0)
    columns = ["cells", "area_km2", "hotspots_per_year", "rank_by_total",
               "hotspots_per_1000km2", "rank_by_density", "fire_days_per_cell"]
    return table[columns].sort_values("hotspots_per_1000km2", ascending=False).reset_index()

def country_by_year(totals,cells):
    with_country = add_cell_info(totals, cells, ["country"])
    sums = with_country.groupby(["year", "country"])["hotspots"].sum().reset_index()
    areas = cells.groupby("country")["area_km2"].sum()

    density = []
    for country, hotspots in zip(sums["country"], sums["hotspots"]):
        density.append(round(hotspots / areas[country] * 1000, 1))
    sums["hotspots_per_1000km2"] = density
    return sums.pivot(index="year", columns="country", values="hotspots_per_1000km2")
    
def seasonal_profile(totals,cells):
    with_country = add_cell_info(totals, cells, ["country"])
    sums = with_country.groupby(["country", "month"])["hotspots"].sum().reset_index()
    country_totals = sums.groupby("country")["hotspots"].sum()

    shares = []
    for country, hotspots in zip(sums["country"], sums["hotspots"]):
        shares.append(round(hotspots / country_totals[country] * 100, 1))
    sums["share_pct"] = shares

    table = sums.pivot(index="country", columns="month", values="share_pct").fillna(0.0)
    table.columns = MONTH_NAMES[:len(table.columns)]
    return table

def fire_season(profile,threshold_pct=10.0):
    rows = []
    for country in profile.index:
        shares = profile.loc[country]
        season = []
        for month in profile.columns:
            if shares[month] >= threshold_pct:
                season.append(month)
        in_season = 0.0
        for month in season:
            in_season = in_season + shares[month]
        rows.append({
            "country": country,
            "peak_month": shares.idxmax(),
            "peak_share_pct": shares.max(),
            "season_months": ", ".join(season),
            "season_share_pct": round(in_season, 1),
        })
    return pd.DataFrame(rows)
    
def by_landcover(totals,cells):
    n_years = totals["year"].nunique()
    with_lc = add_cell_info(totals, cells, ["land_cover_dominant"])

    sums = with_lc.groupby("land_cover_dominant").agg(hotspots=("hotspots", "sum"), fire_days=("fire_days", "sum"))
    size = cells.groupby("land_cover_dominant").agg(cells=("grid_id", "count"), area_km2=("area_km2", "sum"))
    table = size.join(sums)
    table["share_of_cells_pct"] = (table["cells"] / table["cells"].sum() * 100).round(1)
    table["share_of_hotspots_pct"] = (table["hotspots"] / table["hotspots"].sum() * 100).round(1)
    table["fire_days_per_cell"] = (table["fire_days"] / n_years / table["cells"]).round(2)
    table["hotspots_per_1000km2"] = (table["hotspots"] / n_years / table["area_km2"] * 1000).round(1)
    columns = ["cells", "share_of_cells_pct", "share_of_hotspots_pct", "fire_days_per_cell", "hotspots_per_1000km2"]
    return table[columns].sort_values("fire_days_per_cell", ascending=False).reset_index()
    
def by_landcover_share(totals,cells,column,bins=None):
    if bins is None:
        bins = [0, 20, 40, 60, 80, 100]
    n_years = totals["year"].nunique()

    per_cell = totals.groupby("grid_id")["fire_days"].sum().reset_index()
    per_cell = per_cell.merge(cells[["grid_id", column]], on="grid_id", how="left")
    per_cell["share_bin"] = pd.cut(per_cell[column], bins=bins, include_lowest=True)

    table = per_cell.groupby("share_bin", observed=False).agg(cells=("grid_id", "count"), fire_days=("fire_days", "sum"))
    table["fire_days_per_cell"] = (table["fire_days"] / n_years / table["cells"]).round(2)
    table = table.reset_index()
    table["share_bin"] = table["share_bin"].astype(str)
    return table[["share_bin", "cells", "fire_days_per_cell"]]
    
def province_summary(totals,cells,min_area_km2=2000):
    n_years = totals["year"].nunique()
    with_province = add_cell_info(totals, cells, ["province"])

    sums = with_province.groupby("province").agg(hotspots=("hotspots", "sum"), fire_days=("fire_days", "sum"))
    size = cells.groupby("province").agg(country=("country", "first"), cells=("grid_id", "count"),
                                         area_km2=("area_km2", "sum"))
    table = size.join(sums)
    table = table[table["area_km2"] >= min_area_km2]

    table["hotspots_per_year"] = (table["hotspots"] / n_years).round(0)
    table["hotspots_per_1000km2"] = (table["hotspots"] / n_years / table["area_km2"] * 1000).round(1)
    table["fire_days_per_cell"] = (table["fire_days"] / n_years / table["cells"]).round(2)
    table["area_km2"] = table["area_km2"].round(0)
    columns = ["country", "cells", "area_km2", "hotspots_per_year", "hotspots_per_1000km2", "fire_days_per_cell"]
    return table[columns].sort_values("hotspots_per_1000km2", ascending=False).reset_index()
    
def cell_density(totals,cells):
    n_years = totals["year"].nunique()
    per_cell = totals.groupby("grid_id").agg(fire_days=("fire_days", "sum"), hotspots=("hotspots", "sum")).reset_index()
    per_cell["fire_days_per_year"] = (per_cell["fire_days"] / n_years).round(2)
    per_cell["hotspots_per_year"] = (per_cell["hotspots"] / n_years).round(1)
    per_cell = cells[["grid_id", "latitude", "longitude", "country", "province"]].merge(per_cell, on="grid_id", how="left")
    return per_cell[["grid_id", "latitude", "longitude", "country", "province", "fire_days_per_year", "hotspots_per_year"]]