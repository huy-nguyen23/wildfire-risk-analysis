import  math
import pandas as pd

GRID_SIZE_DEG=0.1

PRIMARY_KEY = ["grid_id", "date"]

LAND_COVER_GROUPS = {
    "forest": [10, 95],            # tree cover, mangroves
    "grassland": [20, 30],         # shrubland, grassland
    "cropland": [40],              # cropland - where agricultural burning happens
    "other": [50, 60, 70, 80, 90, 100],  # built-up, bare, snow, water, wetland, moss
}

SCHEMA = {
    # --- Keys and location -------------------------------------------------
    "grid_id": {
        "dtype": "object",
        "unit": None,
        "source": "derived",
        "aggregation": "id of the 0.1 degree ERA5-Land cell, as 'lat_lon' of its centre",
        "valid_range": None,
        "description": "Grid cell identifier, e.g. '18.5_99.0'",
    },
    "date": {
        "dtype": "datetime64[ns]",
        "unit": None,
        "source": "derived",
        "aggregation": "calendar day in UTC (project-wide convention, Session 3)",
        "valid_range": None,
        "description": "The day this row describes",
    },
    "latitude": {
        "dtype": "float64",
        "unit": "degrees",
        "source": "derived",
        "aggregation": "centre of the grid cell",
        "valid_range": (-90, 90),
        "description": "Latitude of the grid cell centre",
    },
    "longitude": {
        "dtype": "float64",
        "unit": "degrees",
        "source": "derived",
        "aggregation": "centre of the grid cell",
        "valid_range": (-180, 180),
        "description": "Longitude of the grid cell centre",
    },
    "country": {
        "dtype": "object",
        "unit": None,
        "source": "derived",
        "aggregation": "country containing the cell centre (Session 7)",
        "valid_range": None,
        "description": "ISO-3 country code, e.g. 'THA'",
    },
    "year": {
        "dtype": "int64",
        "unit": None,
        "source": "derived",
        "aggregation": "from date",
        "valid_range": (2020, 2025),
        "description": "Calendar year, for grouping",
    },
    "month": {
        "dtype": "int64",
        "unit": None,
        "source": "derived",
        "aggregation": "from date",
        "valid_range": (1, 12),
        "description": "Calendar month, for seasonal analysis",
    },

    # --- Fire: the label and its descriptors (NASA FIRMS) ------------------
    "fire": {
        "dtype": "int64",
        "unit": None,
        "source": "FIRMS",
        "aggregation": "1 if any hotspot was detected in this cell on this day, else 0",
        "valid_range": (0, 1),
        "description": "LABEL for the classification model (Session 18)",
    },
    "hotspot_count": {
        "dtype": "int64",
        "unit": "detections",
        "source": "FIRMS",
        "aggregation": "count of detections in the cell that day",
        "valid_range": (0, None),
        "description": "How many detections - a measure of extent, not of fire count",
    },
    "frp_max": {
        "dtype": "float64",
        "unit": "MW",
        "source": "FIRMS",
        "aggregation": "max FRP among that day's detections; 0 when none",
        "valid_range": (0, None),
        "description": "Peak fire intensity in the cell that day",
    },
    "frp_sum": {
        "dtype": "float64",
        "unit": "MW",
        "source": "FIRMS",
        "aggregation": "sum of FRP over that day's detections; 0 when none",
        "valid_range": (0, None),
        "description": "Total radiative power - scales with both size and intensity",
    },
    
    # --- Weather (ERA5-Land) ----------------------------------------------
    "temp_max_c": {
        "dtype": "float64",
        "unit": "degrees Celsius",
        "source": "ERA5-Land",
        "aggregation": "max of the 24 hourly 2m temperatures, converted from Kelvin",
        "valid_range": (-90, 60),
        "description": "Daily maximum air temperature",
    },
    "temp_mean_c": {
        "dtype": "float64",
        "unit": "degrees Celsius",
        "source": "ERA5-Land",
        "aggregation": "mean of the 24 hourly 2m temperatures, converted from Kelvin",
        "valid_range": (-90, 60),
        "description": "Daily mean air temperature",
    },
    "rainfall_mm": {
        "dtype": "float64",
        "unit": "mm",
        "source": "ERA5-Land",
        "aggregation": "accumulated value at 23:00 UTC, converted from metres (Session 3)",
        "valid_range": (0, None),
        "description": "Total precipitation that day",
    },
    "rainfall_7d_mm": {
        "dtype": "float64",
        "unit": "mm",
        "source": "ERA5-Land",
        "aggregation": "rolling 7-day sum of rainfall_mm, ending on this date",
        "valid_range": (0, None),
        "description": "Rain over the previous week - dry weeks precede fire seasons",
    },
    "dry_days": {
        "dtype": "int64",
        "unit": "days",
        "source": "ERA5-Land",
        "aggregation": "consecutive days up to and including this one with rainfall_mm < 1",
        "valid_range": (0, None),
        "description": "Length of the current dry spell",
    },
    "wind_speed_kmh": {
        "dtype": "float64",
        "unit": "km/h",
        "source": "ERA5-Land",
        "aggregation": "mean of hourly sqrt(u10^2 + v10^2), converted from m/s",
        "valid_range": (0, None),
        "description": "Daily mean wind speed - wind spreads fire",
    },
    "soil_moisture": {
        "dtype": "float64",
        "unit": "m3/m3",
        "source": "ERA5-Land",
        "aggregation": "mean of the 24 hourly values of soil water layer 1",
        "valid_range": (0, 1),
        "description": "Surface soil water content - already a ratio, no conversion",
    },
    
    # --- Land cover (ESA WorldCover) ---------------------------------------
    # NOTE: WorldCover has no time dimension. The 2021 map is joined to every
    # date from 2020-2025, i.e. we assume land cover did not change over the
    # study period. That assumption belongs in the Limitations section.
    "land_cover_dominant": {
        "dtype": "object",
        "unit": None,
        "source": "WorldCover",
        "aggregation": "group holding the largest share of the cell's 1.44M pixels",
        "valid_range": None,
        "description": "Most common land-cover group in the cell",
    },
    "forest_pct": {
        "dtype": "float64",
        "unit": "%",
        "source": "WorldCover",
        "aggregation": "share of cell pixels in the forest group",
        "valid_range": (0, 100),
        "description": "Percent tree cover and mangroves",
    },
    "cropland_pct": {
        "dtype": "float64",
        "unit": "%",
        "source": "WorldCover",
        "aggregation": "share of cell pixels in the cropland group",
        "valid_range": (0, 100),
        "description": "Percent cropland - where agricultural burning occurs",
    },
    "grassland_pct": {
        "dtype": "float64",
        "unit": "%",
        "source": "WorldCover",
        "aggregation": "share of cell pixels in the grassland group",
        "valid_range": (0, 100),
        "description": "Percent grassland and shrubland",
    },
    "other_pct": {
        "dtype": "float64",
        "unit": "%",
        "source": "WorldCover",
        "aggregation": "share of cell pixels in the other group",
        "valid_range": (0, 100),
        "description": "Percent built-up, bare, water, wetland and similar",
    },
}

REQUIRED_NOT_NULL = ["grid_id", "date", "latitude", "longitude", "fire"]
    
def resolution_facts(lat=18.0):
    """Report how far apart the three sources' resolutions really are.  

    Turning the mismatch into concrete numbers is the point of Exercise 1:
    'ERA5-Land is coarser' is vague, '1.44 million WorldCover pixels fit in
    one ERA5-Land cell' is not.

    Args:
        lat: latitude at which to measure, since a degree of longitude
            shrinks toward the poles.

    Returns:
        dict of computed facts.
    """
    km_per_deg_lat = 111.32
    km_per_deg_lon = 111.32 * math.cos(math.radians(lat))

    cell_h_km = GRID_SIZE_DEG * km_per_deg_lat
    cell_w_km = GRID_SIZE_DEG * km_per_deg_lon

    # WorldCover ships 3-degree tiles of 36000x36000 pixels
    wc_deg_per_px = 3 / 36000
    wc_px_per_side = GRID_SIZE_DEG / wc_deg_per_px

    viirs_m = 375
    viirs_px = (cell_w_km * 1000 / viirs_m) * (cell_h_km * 1000 / viirs_m)

    return {
        "latitude": lat,
        "cell_width_km": round(cell_w_km, 2),
        "cell_height_km": round(cell_h_km, 2),
        "cell_area_km2": round(cell_w_km * cell_h_km, 1),
        "worldcover_pixels_per_side": int(wc_px_per_side),
        "worldcover_pixels_per_cell": int(wc_px_per_side ** 2),
        "viirs_pixels_per_cell": int(viirs_px),
        "era5_values_per_cell_per_day": 24,
    }
    
def schema_table():
    """Return SCHEMA as a DataFrame - the table that goes into the docs."""
    rows = []
    for col, spec in SCHEMA.items():
        rows.append({
            "column": col,
            "dtype": spec["dtype"],
            "unit": spec["unit"] or "",
            "source": spec["source"],
            "valid_range": (
                "" if spec["valid_range"] is None
                else f"{spec['valid_range'][0]} .. {spec['valid_range'][1]}"
            ),
            "description": spec["description"],
        })
    return pd.DataFrame(rows)

def _snap_index(value, size=GRID_SIZE_DEG):
    steps_per_degree = round(1 / size)      # 0.1 -> 10
    return math.floor(value * steps_per_degree + 0.5)

def latlon_to_grid_id(lat, lon, size=GRID_SIZE_DEG):
    """Turn any coordinate into the id of its grid cell.

    Example: (18.52, 99.03) -> "18.5_99.0"   (the centre of the cell)
    """
    if not (-90 <= lat <= 90):
        raise ValueError(f"latitude must be between -90 and 90, got {lat}")
    if not (-180 <= lon <= 180):
        raise ValueError(f"longitude must be between -180 and 180, got {lon}")

    lat_c = _snap_index(lat, size) * size
    lon_c = _snap_index(lon, size) * size
    return f"{lat_c:.1f}_{lon_c:.1f}"


def grid_id_to_latlon(grid_id):
    """The opposite of latlon_to_grid_id(): "18.5_99.0" -> (18.5, 99.0)."""
    try:
        lat_str, lon_str = grid_id.split("_")
        return float(lat_str), float(lon_str)
    except (ValueError, AttributeError):
        raise ValueError(f"Not a valid grid_id: {grid_id!r}. Expected e.g. '18.5_99.0'")


def grid_cell_bounds(grid_id, size=GRID_SIZE_DEG):
    # Return (west, south, east, north) of a grid cell.
    lat_c, lon_c = grid_id_to_latlon(grid_id)
    half = size / 2
    return (lon_c - half, lat_c - half, lon_c + half, lat_c + half)

def empty_dataframe():
    return pd.DataFrame({
        col: pd.Series(dtype=spec["dtype"]) for col, spec in SCHEMA.items()
    })
    
def validate_schema(df, strict=False, verbose=True):
    """Check a table against SCHEMA and list EVERY problem found.

    It does not stop at the first problem: seeing the whole list at once
    is faster than fixing one thing and running it again seven times.
    Returns a list of problems (empty list = the table is fine).
    """
    problems = []

    # 1. Missing columns
    missing = []
    for column in SCHEMA:
        if column not in df.columns:
            missing.append(column)
    if len(missing) > 0:
        problems.append(f"Missing columns: {missing}")

    # 2. Extra columns (only if strict=True)
    if strict:
        extra = []
        for column in df.columns:
            if column not in SCHEMA:
                extra.append(column)
        if len(extra) > 0:
            problems.append(f"Unexpected columns not in SCHEMA: {extra}")

    # 3. Column types
    for column in SCHEMA:
        if column not in df.columns:
            continue
        actual = str(df[column].dtype)
        expected = SCHEMA[column]["dtype"]

        # Different pandas versions name text and date types differently.
        # I accept all of them so the check does not fail because of a version.
        if expected == "object" and actual in ["object", "str", "string"]:
            continue
        if expected.startswith("datetime64") and actual.startswith("datetime64"):
            continue
        if actual != expected:
            problems.append(f"Column '{column}': dtype is {actual}, expected {expected}")

    # 4. Values outside the allowed range
    for column in SCHEMA:
        if column not in df.columns:
            continue
        allowed = SCHEMA[column]["valid_range"]
        if allowed is None:
            continue

        lowest, highest = allowed
        numbers = pd.to_numeric(df[column], errors="coerce")

        if lowest is not None:
            n_too_low = int((numbers < lowest).sum())
            if n_too_low > 0:
                problems.append(f"Column '{column}': {n_too_low} value(s) below minimum {lowest}")
        if highest is not None:
            n_too_high = int((numbers > highest).sum())
            if n_too_high > 0:
                problems.append(f"Column '{column}': {n_too_high} value(s) above maximum {highest}")

    # 5. Empty values in columns that must be filled
    for column in REQUIRED_NOT_NULL:
        if column in df.columns:
            n_empty = int(df[column].isna().sum())
            if n_empty > 0:
                problems.append(f"Column '{column}': {n_empty} null value(s), but it is required")

    # 6. The 4 land cover percentages must add up to 100
    percent_columns = ["forest_pct", "cropland_pct", "grassland_pct", "other_pct"]
    has_all = True
    for column in percent_columns:
        if column not in df.columns:
            has_all = False
    if has_all:
        total = df[percent_columns].sum(axis=1)
        # allow 1 percentage point for rounding
        n_bad = int(((total - 100).abs() > 1.0).sum())
        if n_bad > 0:
            problems.append(f"{n_bad} row(s) where the four land-cover percentages do not sum to 100")

    if verbose:
        if len(problems) > 0:
            print(f"validate_schema: {len(problems)} problem(s) found")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"validate_schema: OK - {len(df)} rows, {len(df.columns)} columns")

    return problems

def check_primary_key(df, verbose=True):
    """Verify that (grid_id, date) identifies each row uniquely.

    A duplicated key means the same cell-day got built twice - usually a
    merge that fanned out, which quietly double-counts everything
    downstream. Worth checking after every join.

    Args:
        df: the table to check.
        verbose: print the result.

    Returns:
        DataFrame of the duplicated key rows - empty means the key is sound.
    """
    for col in PRIMARY_KEY:
        if col not in df.columns:
            if verbose:
                print(f"check_primary_key: cannot check, column '{col}' is missing")
            return None

    dupes = df[df.duplicated(subset=PRIMARY_KEY, keep=False)]

    if verbose:
        if len(dupes):
            print(f"check_primary_key: FAILED - {len(dupes)} row(s) share a "
                  f"(grid_id, date) with another row")
            print(dupes[PRIMARY_KEY].head(10).to_string(index=False))
        else:
            print(f"check_primary_key: OK - all {len(df)} rows have a unique "
                  f"(grid_id, date)")

    return dupes   