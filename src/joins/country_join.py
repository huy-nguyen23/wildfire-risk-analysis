from pathlib import Path
import pandas as pd 
import config
import schema
from cleaners import firms_clean

def cell_centres(grid_ids):
    rows = []
    for grid_id in sorted(set(grid_ids)):
        lat, lon = schema.grid_id_to_latlon(grid_id)
        rows.append({"grid_id": grid_id, "latitude": lat, "longitude": lon})
    return pd.DataFrame(rows)

def nearest_country(cells,borders,max_distance_km):
    import geopandas as gpd
    from shapely.geometry import Point

    points = []
    for lon, lat in zip(cells["longitude"], cells["latitude"]):
        points.append(Point(lon, lat))
    point_table = gpd.GeoDataFrame(cells[[]], geometry=points, crs="EPSG:4326").to_crs("EPSG:3857")

    joined = gpd.sjoin_nearest(point_table, borders.to_crs("EPSG:3857"), how="left",
                               max_distance=max_distance_km * 1000)
    joined = joined[~joined.index.duplicated(keep="first")]
    return joined["country"].values

def country_for_cells(grid_ids,borders=None,max_distance_km=15,verbose=True):
    if borders is None:
        borders = firms_clean.load_country_borders(verbose=False)

    cells = cell_centres(grid_ids)

    # Step 1: point in polygon for every cell centre
    cells = firms_clean.assign_country(cells, borders=borders, column="country", verbose=False)
    cells["country_method"] = "inside"

    # Step 2: centres in the sea - take the nearest country, if close enough
    at_sea = cells["country"].isna()
    if at_sea.sum() > 0:
        cells.loc[at_sea, "country"] = nearest_country(cells[at_sea], borders, max_distance_km)
        cells.loc[at_sea, "country_method"] = "nearest"

    still_missing = cells["country"].isna()
    cells.loc[still_missing, "country_method"] = "none"

    cells["in_study_area"] = cells["country"].isin(config.STUDY_COUNTRIES).astype("int64")

    if verbose:
        n_in = int(cells["in_study_area"].sum())
        print(f"Grid cells: {len(cells):,}")
        print(f"  centre inside a border:       {int((cells['country_method'] == 'inside').sum()):,}")
        print(f"  coastal, nearest country:     {int((cells['country_method'] == 'nearest').sum()):,}")
        print(f"  no country found:             {int(still_missing.sum()):,}")
        print(f"  in the study countries:       {n_in:,} ({n_in / len(cells) * 100:.1f}%)")
        print(f"  outside the study countries:  {len(cells) - n_in:,}")

    return cells

def save_cell_countries(table,path=None):
    if path is None:
        path = config.PROCESSED_FILES["cell_countries"]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    table.to_parquet(path, index=False)
    print(f"Saved {len(table):,} cells -> {path}")
    return path