import numpy as np
import pandas as pd
import config

def add_rolling_features(df,window=config.RAINFALL_WINDOW_DAYS,min_periods=1,verbose=True):
    table = df.sort_values(["grid_id", "date"]).reset_index(drop=True)
    column = f"rainfall_{window}d_mm"

    # Step 1: find the first row of every cell
    grid_ids = table["grid_id"].tolist()
    block_starts = []
    for i in range(len(grid_ids)):
        if i == 0 or grid_ids[i] != grid_ids[i - 1]:
            block_starts.append(i)
    block_starts.append(len(grid_ids))   # one past the last row

    # Step 2: rolling sum inside each cell's block of rows
    rain = table["rainfall_mm"]
    pieces = []
    n_short_history = 0

    for b in range(len(block_starts) - 1):
        start = block_starts[b]
        end = block_starts[b + 1]
        cell_rain = rain.iloc[start:end]
        pieces.append(cell_rain.rolling(window, min_periods=min_periods).sum())

        n_short_history = n_short_history + min(end - start, window - 1)

    if len(pieces) > 0:
        table[column] = pd.concat(pieces)
    else:
        table[column] = np.nan

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

def add_weather_features(df,verbose=True):
    result = add_rolling_features(df, verbose=verbose)
    result = add_dry_days(result, verbose=verbose)
    return result

def add_engineered_features(df,verbose=True):
    result = df.copy()

    dates = pd.to_datetime(result["date"])
    result["day_of_year"] = dates.dt.dayofyear.astype("int64")

    result["is_dry_season"] = result["month"].isin(config.DRY_SEASON_MONTHS).astype("int64")

    result["dry_wind_interaction"] = (result["dry_days"] * result["wind_speed_kmh"]).round(2)

    numerator = result["temp_max_c"] * (result["wind_speed_kmh"] + 1.0)
    denominator = (result["rainfall_7d_mm"] + 1.0) * (result["soil_moisture"] + 0.05)
    result["fire_weather_index"] = (numerator / denominator).round(2)

    result["is_extreme_heat"] = (result["temp_max_c"] >= config.EXTREME_HEAT_C).astype("int64")

    if verbose:
        print("Added engineered features:")
        print("  day_of_year, is_dry_season, dry_wind_interaction, fire_weather_index, is_extreme_heat")

    return result

    
    
    
    
    