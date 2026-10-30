from config import ACCUMULATION_RESET_HOUR_UTC
import pandas as pd

def describe_era5(ds, name="dataset"):
    """Print a structured overview of an ERA5-Land xarray.Dataset.

    This is the xarray counterpart to data_utils.describe_firms() from
    Session 2 - same purpose, different data shape. A NetCDF Dataset has
    dimensions and coordinates in addition to the variables a DataFrame has.
    """
    print("=" * 64)
    print(f"OVERVIEW: {name}")
    print("=" * 64)

    print(f"\n[1] Dimensions: {dict(ds.sizes)}")

    print("\n[2] Coordinates:")
    for coord in ds.coords:
        values = ds.coords[coord].values
        # Some coordinates carried over from the GRIB source (e.g. 'number',
        # the ensemble member id, and 'expver', the experiment version) are
        # scalar - they have no length, so len() raises TypeError on them.
        # ndim == 0 is the reliable way to detect "this coordinate is a
        # single value, not an array".
        if values.ndim == 0:
            print(f"    {coord}: {values} ")
        elif len(values) > 1:
            print(f"    {coord}: {len(values)} values, from {values[0]} to {values[-1]}")
        else:
            print(f"    {coord}: {values}")

    print("\n[3] Data variables (short name -> long name, units):")
    for var in ds.data_vars:
        long_name = ds[var].attrs.get("long_name", "?")
        units = ds[var].attrs.get("units", "?")
        print(f"    {var:8s} -> {long_name} [{units}]")

    print("\n[4] Value ranges:")
    for var in ds.data_vars:
        vmin = float(ds[var].min())
        vmax = float(ds[var].max())
        print(f"    {var:8s} min={vmin:.4f}  max={vmax:.4f}")

    print("\n" + "=" * 64)
    
def _approx_distance_km(lat1, lon1, lat2, lon2):
    import math
    dlat = (lat2 - lat1) * 111.0
    dlon = (lon2 - lon1) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.sqrt(dlat**2 + dlon**2)
    
def extract_point(ds, latitude, longitude, variables=None):
    point = ds.sel(latitude=latitude, longitude=longitude, method="nearest")

    if variables:
        point = point[variables]

    df = point.to_dataframe().reset_index()

    if "valid_time" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"valid_time": "time"})

    df = df.drop(columns=[c for c in ("number", "expver") if c in df.columns])

    matched_lat = float(point["latitude"])
    matched_lon = float(point["longitude"])
    offset_km = _approx_distance_km(latitude, longitude, matched_lat, matched_lon)

    print(f"Requested ({latitude}, {longitude}) -> matched grid cell "
          f"({matched_lat:.2f}, {matched_lon:.2f}), ~{offset_km:.1f} km away")

    return df

def add_derived_variables(df):
    df = df.copy()

    if "t2m" in df.columns:
        df["temperature_c"] = df["t2m"] - 273.15

    if "tp" in df.columns:
        df["precipitation_mm"] = df["tp"] * 1000.0

    if "u10" in df.columns and "v10" in df.columns:
        df["wind_speed_ms"] = (df["u10"] ** 2 + df["v10"] ** 2) ** 0.5

    return df

def daily_precipitation(df, time_col="time", precip_col="tp"):
    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col])

    last_hour_of_day = 23 if ACCUMULATION_RESET_HOUR_UTC == 0 else (ACCUMULATION_RESET_HOUR_UTC - 1) % 24
    daily = df[df[time_col].dt.hour == last_hour_of_day].copy()

    daily["date"] = daily[time_col].dt.floor("D")
    daily["precipitation_mm"] = daily[precip_col] * 1000.0

    return daily[["date", "precipitation_mm"]].reset_index(drop=True)

def rolling_precip_sum(daily_df, window_days=7, value_col="precipitation_mm"):
    daily_df = daily_df.sort_values("date").reset_index(drop=True)
    out_col = f"{value_col}_{window_days}d"
    daily_df[out_col] = daily_df[value_col].rolling(window_days, min_periods=1).sum()
    return daily_df