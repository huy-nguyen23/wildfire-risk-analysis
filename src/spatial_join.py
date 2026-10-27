import math
from pathlib import Path
import numpy as np
import pandas as pd
import config 
import schema

def hotspots_to_grid(df,verbose=True):
    result=df.copy()
    grid_ids=[]
    for lat,lon in zip(result["latitude"],result["longitude"]):
        grid_ids.append(schema.latlon_to_grid_id(lat, lon))
    result["grid_id"] = grid_ids

    if verbose:
        print(f"{len(result):,} hotspots fall into {result['grid_id'].nunique():,} grid cells")

    return result

def distance_km(lat1,lon1,lat2,lon2):
    km_north = (lat2 - lat1) * 111.0
    middle_lat = (lat1 + lat2) / 2
    km_east = (lon2 - lon1) * 111.0 * math.cos(math.radians(middle_lat))
    return math.sqrt(km_north ** 2 + km_east ** 2)

def compare_grid_methods(df,weather_df,verbose=True):
    cells = weather_df[["latitude", "longitude"]].drop_duplicates()
    cell_ids = set(weather_df["grid_id"].unique())

    results = []
    for lat, lon in zip(df["latitude"], df["longitude"]):
        by_rounding = schema.latlon_to_grid_id(lat, lon)

        # Nearest-neighbour: the closest EXISTING weather cell
        km_to_each = []
        for cell_lat, cell_lon in zip(cells["latitude"], cells["longitude"]):
            km_to_each.append(distance_km(lat, lon, cell_lat, cell_lon))
        closest = int(np.argmin(km_to_each))
        by_nearest = schema.latlon_to_grid_id(cells["latitude"].iloc[closest],
                                              cells["longitude"].iloc[closest])

        results.append({
            "latitude": lat,
            "longitude": lon,
            "by_rounding": by_rounding,
            "by_nearest": by_nearest,
            "rounding_has_weather": by_rounding in cell_ids,
            "km_to_nearest_cell": round(km_to_each[closest], 1),
        })

    table = pd.DataFrame(results)
    table["same_answer"] = table["by_rounding"] == table["by_nearest"]

    if verbose:
        n_same = int(table["same_answer"].sum())
        n_outside = int((~table["rounding_has_weather"]).sum())
        inside = table[table["rounding_has_weather"]]
        n_disagree_inside = int((~inside["same_answer"]).sum())
        print(f"Same answer for {n_same:,} of {len(table):,} hotspots "
              f"({n_same / len(table) * 100:.1f}%)")
        print(f"Inside the weather area: {n_disagree_inside:,} disagreement(s) "
              f"out of {len(inside):,} hotspots")
        print(f"{n_outside:,} hotspots have no weather cell by rounding (outside the weather area)")
        if n_outside > 0:
            far = table[~table["rounding_has_weather"]]["km_to_nearest_cell"]
            print(f"  nearest-neighbour would give them a cell {far.min():,.0f} to "
                  f"{far.max():,.0f} km away")

    return table

def main_country(df):
    if "country" not in df.columns:
        return None

    counts = df.groupby(["grid_id", "date", "country"]).size().reset_index(name="n")
    counts = counts.sort_values(["grid_id", "date", "n"], ascending=[True, True, False])
    top = counts.drop_duplicates(subset=["grid_id", "date"])
    return top[["grid_id", "date", "country"]]

def count_hotspots_by_cell_day(df,verbose=True):
    result = df.groupby(["grid_id", "date"]).agg(
        hotspot_count=("frp", "size"),
        frp_max=("frp", "max"),
        frp_sum=("frp", "sum"),
    ).reset_index()

    result["fire"] = 1
    
    latitudes = []
    longitudes = []
    for grid_id in result["grid_id"]:
        lat, lon = schema.grid_id_to_latlon(grid_id)
        latitudes.append(lat)
        longitudes.append(lon)
    result["latitude"] = latitudes
    result["longitude"] = longitudes

    countries = main_country(df)
    if countries is not None:
        result = result.merge(countries, on=["grid_id", "date"], how="left")

    result["year"] = pd.to_datetime(result["date"]).dt.year
    result["month"] = pd.to_datetime(result["date"]).dt.month

    if verbose:
        print(f"{len(df):,} hotspots -> {len(result):,} cell-days with fire")
        print(f"  most detections in one cell-day: {result['hotspot_count'].max()}")

    return result

def join_weather(fire_df,weather_df,verbose=True):
    fire = fire_df.copy()
    weather = weather_df.copy()

    fire["date"] = pd.to_datetime(fire["date"]).dt.floor("D").astype("datetime64[ns]")
    weather["date"] = pd.to_datetime(weather["date"]).dt.floor("D").astype("datetime64[ns]")
    
    for column in ["latitude", "longitude", "year", "month"]:
        if column in weather.columns:
            weather = weather.drop(columns=[column])

    joined = fire.merge(weather, on=["grid_id", "date"], how="left")

    found = joined["temp_max_c"].notna()
    unmatched = joined[~found].copy()
    joined = joined[found].reset_index(drop=True)
    joined = schema.apply_schema_dtypes(joined)

    if verbose:
        print(f"Matched {len(joined):,} of {len(fire):,} fire rows "
              f"({len(joined) / len(fire) * 100:.1f}%)")

    return joined, unmatched
    
def explain_unmatched(unmatched,weather_df):
    weather_cells = set(weather_df["grid_id"].unique())
    weather_days = set(pd.to_datetime(weather_df["date"]).dt.floor("D"))

    wrong_place = 0
    wrong_day = 0
    both = 0

    days = pd.to_datetime(unmatched["date"]).dt.floor("D")
    for cell, day in zip(unmatched["grid_id"], days):
        place_is_bad = cell not in weather_cells
        day_is_bad = day not in weather_days
        if place_is_bad and day_is_bad:
            both += 1
        elif place_is_bad:
            wrong_place += 1
        elif day_is_bad:
            wrong_day += 1

    return pd.DataFrame([
        {"reason": "cell is outside the weather area", "rows": wrong_place},
        {"reason": "day is outside the weather dates", "rows": wrong_day},
        {"reason": "both", "rows": both},
    ])
    
def check_coverage(hotspots_df,weather_df,verbose=True):
    weather_cells = set(weather_df["grid_id"].unique())
    inside = hotspots_df["grid_id"].isin(weather_cells)

    report = {
        "hotspots": len(hotspots_df),
        "hotspots_in_weather_area": int(inside.sum()),
        "hotspots_outside_weather_area": int((~inside).sum()),
        "percent_in_weather_area": round(inside.sum() / len(hotspots_df) * 100, 2),
        "weather_cells": len(weather_cells),
        "cells_with_hotspots": int(hotspots_df.loc[inside, "grid_id"].nunique()),
    }

    if verbose:
        for key in report:
            print(f"  {key:32s} {report[key]:,}")

    return report

def build_fire_weather(firms_df,weather_df,verbose=True):
    report = {"hotspots_in": len(firms_df)}

    with_grid = hotspots_to_grid(firms_df, verbose=verbose)

    by_cell_day = count_hotspots_by_cell_day(with_grid, verbose=verbose)
    report["cell_days_with_fire"] = len(by_cell_day)

    joined, unmatched = join_weather(by_cell_day, weather_df, verbose=verbose)
    report["matched"] = len(joined)
    report["unmatched"] = len(unmatched)
    report["matched_percent"] = round(len(joined) / len(by_cell_day) * 100, 2)

    if verbose:
        print()
        print("=" * 60)
        for key in report:
            print(f"  {key:22s} {report[key]:,}")
        print("=" * 60)

    return joined, unmatched, report

def save_fire_weather(df,path=None):
    if path is None:
        path = config.PROCESSED_DIR / "fire_weather.parquet"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(path, index=False)
    print(f"Saved {len(df):,} rows -> {path}")
    return path








