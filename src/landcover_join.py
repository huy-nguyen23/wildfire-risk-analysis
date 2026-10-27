import math
from pathlib import Path
import numpy as np
import pandas as pd
import config 
import schema
import worldcover_api

GROUP_NAMES=list(schema.LAND_COVER_GROUPS.keys())

def make_group_lookup():
    lookup = np.full(256, -1, dtype=np.int16)
    for number, name in enumerate(GROUP_NAMES):
        for code in schema.LAND_COVER_GROUPS[name]:
            lookup[code] = number
    return lookup

GROUP_LOOKUP=make_group_lookup()

def class_name(code):
    if code in config.LAND_COVER_CLASSES:
        return config.LAND_COVER_CLASSES[code][0]
    return None

def group_name(code):
    for name in GROUP_NAMES:
        if code in schema.LAND_COVER_GROUPS[name]:
            return name
    return None

def pixel_size_m(transform,lat):
    width = abs(transform.a) * 111320 * math.cos(math.radians(lat))
    height = abs(transform.e) * 111320
    return width, height

def load_saved_landcover(region_name,year=None):
    import rasterio

    if year is None:
        year = config.DEFAULT_YEAR

    parts = config.STUDY_REGIONS[region_name].split(",")
    bbox = (float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3]))

    folder = config.RAW_SUBDIRS["worldcover"] / str(year)
    path = worldcover_api._cache_path(bbox, year, folder)

    if not path.exists():
        raise FileNotFoundError(
            f"No land cover map for {region_name!r} at {path}. "
            "Run scripts/download_all.py --source worldcover first."
        )

    with rasterio.open(path) as source:
        return source.read(1), source.transform
    
def load_all_landcover(year=None,verbose=True):
    maps = {}
    for name in config.STUDY_REGIONS:
        maps[name] = load_saved_landcover(name, year)
        if verbose:
            data, transform = maps[name]
            lat = (transform.f + transform.f + transform.e * data.shape[0]) / 2
            width_m, height_m = pixel_size_m(transform, lat)
            print(f"{name:12s} {data.shape[1]:,} x {data.shape[0]:,} pixels, "
                  f"each about {width_m:.0f} x {height_m:.0f} m")
    return maps

def landcover_at_points(df,data,transform):
    result = df.copy().reset_index(drop=True)
    height, width = data.shape

    cols = np.floor((result["longitude"].values - transform.c) / transform.a).astype(int)
    rows = np.floor((result["latitude"].values - transform.f) / transform.e).astype(int)

    inside = (rows >= 0) & (rows < height) & (cols >= 0) & (cols < width)

    codes = np.full(len(result), -1, dtype=int)
    codes[inside] = data[rows[inside], cols[inside]]

    classes = []
    groups = []
    statuses = []
    for is_inside, code in zip(inside, codes):
        if not is_inside:
            classes.append(None)
            groups.append(None)
            statuses.append("outside_map")
        elif code == 0:
            classes.append(None)
            groups.append(None)
            statuses.append("no_data")
        elif code not in config.LAND_COVER_CLASSES:
            classes.append(None)
            groups.append(None)
            statuses.append("unknown_code")
        else:
            classes.append(class_name(code))
            groups.append(group_name(code))
            statuses.append("ok")

    result["landcover_code"] = pd.array(
        [code if is_inside else None for is_inside, code in zip(inside, codes)],
        dtype="Int64",
    )
    result["landcover_class"] = classes
    result["landcover_group"] = groups
    result["landcover_status"] = statuses

    return result

def landcover_around_points(df,data,transform,size_m=375):
    result = df.copy().reset_index(drop=True)
    height, width = data.shape

    best_groups = []
    best_percents = []

    for lat, lon in zip(result["latitude"], result["longitude"]):
        pixel_w, pixel_h = pixel_size_m(transform, lat)
        half_cols = max(1, int(round(size_m / 2 / pixel_w)))
        half_rows = max(1, int(round(size_m / 2 / pixel_h)))

        centre_col = int(math.floor((lon - transform.c) / transform.a))
        centre_row = int(math.floor((lat - transform.f) / transform.e))
        
        first_row = max(0, centre_row - half_rows)
        last_row = min(height, centre_row + half_rows + 1)
        first_col = max(0, centre_col - half_cols)
        last_col = min(width, centre_col + half_cols + 1)

        if first_row >= last_row or first_col >= last_col:
            best_groups.append(None)
            best_percents.append(np.nan)
            continue

        square = data[first_row:last_row, first_col:last_col]
        group_numbers = GROUP_LOOKUP[square.ravel()]
        group_numbers = group_numbers[group_numbers >= 0]  

        if len(group_numbers) == 0:
            best_groups.append(None)
            best_percents.append(np.nan)
            continue

        counts = np.bincount(group_numbers, minlength=len(GROUP_NAMES))
        winner = int(counts.argmax())
        best_groups.append(GROUP_NAMES[winner])
        best_percents.append(round(counts[winner] / counts.sum() * 100, 1))

    result["around_group"] = best_groups
    result["around_group_pct"] = best_percents
    return result

def landcover_by_cell(grid_ids,data,transform,min_coverage=0.5):
    rows = []
    height, width = data.shape

    for grid_id in grid_ids:
        west, south, east, north = schema.grid_cell_bounds(grid_id)

        first_col = math.floor((west - transform.c) / transform.a + 1e-6)
        last_col = math.ceil((east - transform.c) / transform.a - 1e-6)
        first_row = math.floor((north - transform.f) / transform.e + 1e-6)
        last_row = math.ceil((south - transform.f) / transform.e - 1e-6)

        first_col = max(0, first_col)
        first_row = max(0, first_row)
        last_col = min(width, last_col)
        last_row = min(height, last_row)

        expected = ((east - west) / abs(transform.a)) * ((north - south) / abs(transform.e))

        row = {"grid_id": grid_id}

        if first_row >= last_row or first_col >= last_col:
            row["landcover_coverage_pct"] = 0.0
            rows.append(row)
            continue

        square = data[first_row:last_row, first_col:last_col]
        group_numbers = GROUP_LOOKUP[square.ravel()]
        group_numbers = group_numbers[group_numbers >= 0]  

        coverage = min(1.0, len(group_numbers) / expected)
        row["landcover_coverage_pct"] = round(coverage * 100, 1)

        if coverage >= min_coverage and len(group_numbers) > 0:
            counts = np.bincount(group_numbers, minlength=len(GROUP_NAMES))
            percents = counts / counts.sum() * 100
            for number, name in enumerate(GROUP_NAMES):
                row[f"{name}_pct"] = round(float(percents[number]), 2)
            row["land_cover_dominant"] = GROUP_NAMES[int(counts.argmax())]

        rows.append(row)

    return pd.DataFrame(rows)

def landcover_for_cells(grid_ids,maps,min_coverage=0.5,verbose=True):
    unique_ids = sorted(set(grid_ids))

    tables = []
    for name in maps:
        data, transform = maps[name]
        table = landcover_by_cell(unique_ids, data, transform, min_coverage)
        table["region"] = name
        tables.append(table)

    combined = pd.concat(tables, ignore_index=True)

    combined = combined.sort_values("landcover_coverage_pct", ascending=False)
    best = combined.drop_duplicates(subset="grid_id", keep="first")
    best = best.sort_values("grid_id").reset_index(drop=True)

    best.loc[best["landcover_coverage_pct"] == 0, "region"] = None

    if verbose:
        n_ok = int(best["land_cover_dominant"].notna().sum())
        print(f"{n_ok:,} of {len(best):,} cells have land cover "
              f"(coverage of at least {min_coverage * 100:.0f}%)")
        n_partial = int(((best["landcover_coverage_pct"] < 99) & best["land_cover_dominant"].notna()).sum())
        if n_partial > 0:
            print(f"  {n_partial:,} cell(s) are only partly covered (at the edge of a map)")

    return best

def add_landcover(df,cell_table,verbose=True):
    columns = ["grid_id", "land_cover_dominant", "forest_pct", "grassland_pct", "cropland_pct", "other_pct", "landcover_coverage_pct"]
    keep = cell_table[columns]

    result = df.merge(keep, on="grid_id", how="left")

    if verbose:
        n_missing = int(result["land_cover_dominant"].isna().sum())
        print(f"{len(result) - n_missing:,} of {len(result):,} rows got land cover "
              f"({n_missing:,} did not)")

    return schema.apply_schema_dtypes(result)

def save_landcover_cells(cell_table,path=None):
    if path is None:
        path = config.PROCESSED_FILES["landcover_cells"]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    cell_table.to_parquet(path, index=False)
    print(f"Saved {len(cell_table):,} cells -> {path}")
    return path

def save_fire_weather_landcover(df,path=None):
    if path is None:
        path = config.PROCESSED_FILES["fire_weather_landcover"]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(path, index=False)
    print(f"Saved {len(df):,} rows -> {path}")
    return path