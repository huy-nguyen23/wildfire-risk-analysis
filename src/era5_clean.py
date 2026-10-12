from pathlib import Path
import numpy as np
import pandas as pd 
import config
import schema
import xarray as xr

def load_raw_era5(raw_dir=None,max_files=1,verbose=True):
    if raw_dir is None:
        raw_dir = config.RAW_SUBDIRS["era5"]

    files = sorted(Path(raw_dir).glob("**/*.nc"))
    if len(files) == 0:
        raise FileNotFoundError(f"No .nc files in {raw_dir}. Run scripts/download_all.py first.")

    chosen = files[:max_files]
    datasets = []
    for file in chosen:
        datasets.append(xr.open_dataset(file))

    if len(datasets) == 1:
        dataset = datasets[0]
    else:
        dataset = xr.combine_by_coords(datasets)

    if verbose:
        print(f"Opened {len(chosen)} of {len(files)} file(s)")
        print(f"Dimensions: {dict(dataset.sizes)}")
        print(f"Variables : {list(dataset.data_vars)}")

    return dataset

def kelvin_to_celsius(values):
    """Kelvin -> degrees Celsius."""
    return values - 273.15


def metres_to_mm(values):
    """Metres -> millimetres. ERA5-Land gives rain in METRES, not mm."""
    return values * 1000.0


def ms_to_kmh(values):
    """Metres per second -> kilometres per hour."""
    return values * 3.6

def wind_speed(u, v):
    """Wind speed from its two parts: sqrt(u^2 + v^2)."""
    return np.sqrt(u ** 2 + v ** 2)

def compare_wind_methods(df,time_column="time"):
    table = df.copy()
    table["date"] = pd.to_datetime(table[time_column]).dt.floor("D")
    table["speed_each_hour"] = wind_speed(table["u10"], table["v10"])

    groups = table.groupby(["grid_id", "date"])

    right = groups["speed_each_hour"].mean()

    average_u = groups["u10"].mean()
    average_v = groups["v10"].mean()
    wrong = wind_speed(average_u, average_v)

    result = pd.DataFrame({
        "speed_correct_ms": right,
        "speed_wrong_ms": wrong,
    }).reset_index()

    result["difference_ms"] = (result["speed_correct_ms"] - result["speed_wrong_ms"]).round(3)
    result["understated_by_pct"] = ((1 - result["speed_wrong_ms"] / result["speed_correct_ms"]) * 100).round(1)

    return result

def compare_rainfall_methods(df,time_column="time"):
    table = df.copy()
    table[time_column] = pd.to_datetime(table[time_column])
    table["date"] = table[time_column].dt.floor("D")
    table["hour"] = table[time_column].dt.hour

    groups = table.groupby(["grid_id", "date"])
    result = pd.DataFrame({
        "sum_all_hours_mm": groups["tp"].sum() * 1000,
        "max_within_day_mm": groups["tp"].max() * 1000,
    })

    last_hour = table[table["hour"] == 23]
    if len(last_hour) > 0:
        result["value_at_23h_mm"] = last_hour.groupby(["grid_id", "date"])["tp"].first() * 1000
        
        result["sum_overstates_by_x"] = (
            result["sum_all_hours_mm"] / result["value_at_23h_mm"].replace(0, np.nan)
        ).round(1)

    return result.reset_index()

def to_dataframe(dataset):
    """Turn an ERA5-Land dataset into a normal table with one row per hour."""
    table = dataset.to_dataframe().reset_index()

    if "valid_time" in table.columns and "time" not in table.columns:
        table = table.rename(columns={"valid_time": "time"})

    for column in ["number", "expver"]:
        if column in table.columns:
            table = table.drop(columns=[column])

    weather_columns = []
    for column in ["t2m", "tp", "u10", "v10", "swvl1"]:
        if column in table.columns:
            weather_columns.append(column)
    table = table.dropna(subset=weather_columns, how="all")

    grid_ids = []
    for lat, lon in zip(table["latitude"], table["longitude"]):
        grid_ids.append(schema.latlon_to_grid_id(lat, lon))
    table["grid_id"] = grid_ids

    return table

def aggregate_daily(df,time_column="time",verbose=True):
    table = df.copy()
    table[time_column] = pd.to_datetime(table[time_column])
    table["date"] = table[time_column].dt.floor("D")

    table["wind_speed_ms"] = wind_speed(table["u10"], table["v10"])

    daily = table.groupby(["grid_id", "date"]).agg(
        temp_max_k=("t2m", "max"),
        temp_mean_k=("t2m", "mean"),
        rain_m=("tp", "max"),             
        soil_moisture=("swvl1", "mean"),
        wind_speed_ms=("wind_speed_ms", "mean"),
        latitude=("latitude", "first"),
        longitude=("longitude", "first"),
    ).reset_index()

    daily["temp_max_c"] = kelvin_to_celsius(daily["temp_max_k"])
    daily["temp_mean_c"] = kelvin_to_celsius(daily["temp_mean_k"])
    daily["rainfall_mm"] = metres_to_mm(daily["rain_m"])
    daily["wind_speed_kmh"] = ms_to_kmh(daily["wind_speed_ms"])
    daily = daily.drop(columns=["temp_max_k", "temp_mean_k", "rain_m", "wind_speed_ms"])

    daily["year"] = daily["date"].dt.year
    daily["month"] = daily["date"].dt.month

    if verbose:
        print(f"Hourly rows {len(df):,} -> daily rows {len(daily):,}")
        print(f"Columns: {list(daily.columns)}")

    return daily

def add_rolling_features(df,window=config.RAINFALL_WINDOW_DAYS,min_periods=1,verbose=True):
    table = df.sort_values(["grid_id", "date"]).reset_index(drop=True)
    column = f"rainfall_{window}d_mm"
    table[column] = np.nan

    n_short_history = 0

    for grid_id in table["grid_id"].unique():
        rows = table["grid_id"] == grid_id
        rain = table.loc[rows, "rainfall_mm"]
        table.loc[rows, column] = rain.rolling(window, min_periods=min_periods).sum()

        n_short_history = n_short_history + min(len(rain), window - 1)

    if verbose:
        print(f"Added {column}")
        print(f"  {n_short_history:,} row(s) have less than {window} days of history")

    return table

def add_dry_days(df,threshold_mm=config.DRY_DAY_THRESHOLD_MM,verbose=True):
    table = df.sort_values(["grid_id", "date"]).reset_index(drop=True)
    dry_days = []

    counter = 0
    previous_cell = None

    for grid_id, rain in zip(table["grid_id"], table["rainfall_mm"]):
        if grid_id != previous_cell:
            counter = 0
            previous_cell = grid_id

        if rain < threshold_mm:
            counter = counter + 1
        else:
            counter = 0

        dry_days.append(counter)

    table["dry_days"] = dry_days

    if verbose:
        print(f"Added dry_days (threshold {threshold_mm} mm)")
        print(f"  longest dry spell: {max(dry_days)} days")

    return table

def clean_era5(dataset,verbose=True):
    report = {}

    hourly = to_dataframe(dataset)
    report["hourly_rows"] = len(hourly)

    daily = aggregate_daily(hourly, verbose=verbose)
    report["daily_rows"] = len(daily)
    report["grid_cells"] = daily["grid_id"].nunique()
    report["days"] = daily["date"].nunique()

    daily = add_rolling_features(daily, verbose=verbose)
    daily = add_dry_days(daily, verbose=verbose)

    if verbose:
        print()
        print("=" * 60)
        for key in report:
            print(f"  {key:16s} {report[key]:,}")
        print("=" * 60)

    return daily, report

def clean_era5_folder(raw_dir=None,verbose=True):
    if raw_dir is None:
        raw_dir = config.RAW_SUBDIRS["era5"]

    files = sorted(Path(raw_dir).glob("**/*.nc"))
    if len(files) == 0:
        raise FileNotFoundError(f"No .nc files in {raw_dir}. Run scripts/download_all.py first.")

    daily_tables = []
    hourly_rows = 0

    for number, file in enumerate(files, start=1):
        with xr.open_dataset(file) as dataset:
            hourly = to_dataframe(dataset)
        hourly_rows = hourly_rows + len(hourly)
        daily_tables.append(aggregate_daily(hourly, verbose=False))

        if verbose:
            print(f"  [{number}/{len(files)}] {file.name[:60]}... -> {len(daily_tables[-1]):,} daily rows")

    daily = pd.concat(daily_tables, ignore_index=True)

    n_before = len(daily)
    daily = daily.drop_duplicates(subset=["grid_id", "date"], keep="first")
    n_repeated = n_before - len(daily)

    daily = add_rolling_features(daily, verbose=verbose)
    daily = add_dry_days(daily, verbose=verbose)

    report = {
        "files": len(files),
        "hourly_rows": hourly_rows,
        "daily_rows": len(daily),
        "repeated_cell_days_removed": n_repeated,
        "grid_cells": daily["grid_id"].nunique(),
        "days": daily["date"].nunique(),
    }

    if verbose:
        print()
        print("=" * 60)
        for key in report:
            print(f"  {key:28s} {report[key]:,}")
        print("=" * 60)

    return daily, report

def save_daily(df,path=None):
    if path is None:
        path = config.PROCESSED_DIR / "weather_daily.parquet"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(path, index=False)
    print(f"Saved {len(df):,} rows -> {path}")
    return path