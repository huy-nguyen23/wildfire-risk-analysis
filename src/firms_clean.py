import pandas as pd
from pathlib import Path
import config
from firms_utils import add_datetime_columns 

def load_raw_firms(raw_dir=None,verbose=True):
    if raw_dir is None:
        raw_dir = config.RAW_SUBDIRS["firms"]

    files = sorted(Path(raw_dir).glob("**/*.csv"))
    if len(files) == 0:
        raise FileNotFoundError(
            f"No CSV files in {raw_dir}. Run scripts/download_all.py first."
        )

    tables = []
    for file in files:
        table = pd.read_csv(file)
        if len(table) == 0:
            continue
        table["source_file"] = file.name
        tables.append(table)

    if len(tables) == 0:
        raise ValueError(f"All {len(files)} files in {raw_dir} were empty.")

    result = pd.concat(tables, ignore_index=True)
    if verbose:
        print(f"Loaded {len(files)} files -> {len(result):,} rows")
        print("Country is not inferred from the acquisition-area filename.")
    return result

def standardize_time(df,verbose=True):
    result = add_datetime_columns(df)

    # A plain date column (no time part) for grouping by day later
    result["date"] = result["acq_datetime_utc"].dt.floor("D").dt.tz_localize(None)

    if verbose:
        print(f"Dates: {result['date'].min().date()} to {result['date'].max().date()}")
        print(f"Years: {sorted(result['year'].unique())}")

    return result

def count_duplicates_by_key(df,verbose=True):
    definitions = {
        "coordinates only": ["latitude", "longitude"],
        "coordinates + date": ["latitude", "longitude", "acq_date"],
        "coordinates + exact time": ["latitude", "longitude", "acq_datetime_utc"],
        "coordinates + time + sensor": config.FIRMS_DUPLICATE_KEY,
    }

    rows = []
    for name, keys in definitions.items():
        # Skip a definition if the table does not have all its columns
        if not all(key in df.columns for key in keys):
            continue

        n_duplicates = int(df.duplicated(subset=keys).sum())
        rows.append({
            "definition": name,
            "rows_removed": n_duplicates,
            "percent": round(n_duplicates / len(df) * 100, 2),
        })

    result = pd.DataFrame(rows)

    if verbose:
        print(result.to_string(index=False))
        print()
        print("A looser key removes more rows. But two satellites seeing the")
        print("same fire are two independent observations, not a duplicate.")

    return result

def drop_duplicates_firms(df,verbose=True):
    keys = [key for key in config.FIRMS_DUPLICATE_KEY if key in df.columns]

    n_before = len(df)
    result = df.drop_duplicates(subset=keys, keep="first")
    result = result.reset_index(drop=True)
    n_removed = n_before - len(result)

    if verbose:
        percent = n_removed / n_before * 100
        print(f"Duplicates removed: {n_removed:,} of {n_before:,} ({percent:.2f}%)")

    return result, n_removed

def filter_invalid(df,verbose=True):
    result = df.copy()
    report = []

    # Rule 1: latitude must be between -90 and 90
    is_bad = ~result["latitude"].between(-90, 90)
    if is_bad.sum() > 0:
        report.append({"rule": "latitude outside -90..90", "rows_removed": int(is_bad.sum())})
    result = result[~is_bad]

    # Rule 2: longitude must be between -180 and 180
    is_bad = ~result["longitude"].between(-180, 180)
    if is_bad.sum() > 0:
        report.append({"rule": "longitude outside -180..180", "rows_removed": int(is_bad.sum())})
    result = result[~is_bad]

    # Rule 3: fire radiative power cannot be negative
    if "frp" in result.columns:
        is_bad = result["frp"].fillna(0) < 0
        if is_bad.sum() > 0:
            report.append({"rule": "frp is negative", "rows_removed": int(is_bad.sum())})
        result = result[~is_bad]

    # Rule 4: brightness temperature must be above zero Kelvin
    # VIIRS calls this column bright_ti4, MODIS calls it brightness
    if "bright_ti4" in result.columns:
        bright_column = "bright_ti4"
    elif "brightness" in result.columns:
        bright_column = "brightness"
    else:
        bright_column = None

    if bright_column is not None:
        is_bad = result[bright_column].fillna(1) <= 0
        if is_bad.sum() > 0:
            report.append({"rule": f"{bright_column} not positive", "rows_removed": int(is_bad.sum())})
        result = result[~is_bad]

    # Rule 5: coordinates must not be missing
    is_bad = result["latitude"].isna() | result["longitude"].isna()
    if is_bad.sum() > 0:
        report.append({"rule": "missing coordinates", "rows_removed": int(is_bad.sum())})
    result = result[~is_bad]

    result = result.reset_index(drop=True)

    if len(report) > 0:
        report_table = pd.DataFrame(report)
    else:
        report_table = pd.DataFrame(columns=["rule", "rows_removed"])

    if verbose:
        total_removed = len(df) - len(result)
        print(f"Invalid rows removed: {total_removed:,} of {len(df):,}")
        if len(report) > 0:
            print(report_table.to_string(index=False))
        else:
            print("  (no rule fired - the raw data passed every check)")

    return result, report_table

def confidence_to_level(value):
    if pd.isna(value):
        return None

    text = str(value).strip().lower()

    # VIIRS: letters
    if text == "l":
        return "low"
    if text == "n":
        return "nominal"
    if text == "h":
        return "high"

    # MODIS: a number from 0 to 100
    try:
        number = float(text)
    except ValueError:
        return None

    if number < 30:
        return "low"
    elif number < 80:
        return "nominal"
    else:
        return "high"
    
def normalize_confidence(df,verbose=True):
    result = df.copy()
    result["confidence_level"] = result["confidence"].apply(confidence_to_level)

    if verbose:
        print("Confidence levels:")
        print(result["confidence_level"].value_counts(dropna=False).to_string())
        if "instrument" in result.columns:
            print()
            print(pd.crosstab(result["instrument"], result["confidence_level"]).to_string())

    return result

def load_country_borders(verbose=True):
    import geopandas as gpd
    import requests

    path = config.BOUNDARIES_PATH

    if not path.exists():
        if verbose:
            print(f"Downloading country borders from {config.BOUNDARIES_URL} ...")
        path.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(config.BOUNDARIES_URL, timeout=120)
        response.raise_for_status()
        path.write_bytes(response.content)

    borders = gpd.read_file(path)

    borders = borders[["ADM0_A3", "geometry"]]
    borders = borders.rename(columns={"ADM0_A3": "country"})

    if verbose:
        print(f"Country borders loaded: {len(borders)} countries")

    return borders

def assign_country(df,borders=None,column="country",verbose=True):
    import geopandas as gpd
    from shapely.geometry import Point

    if borders is None:
        borders = load_country_borders(verbose=verbose)

    result = df.copy().reset_index(drop=True)

    points = []
    for lon, lat in zip(result["longitude"], result["latitude"]):
        points.append(Point(lon, lat))
    point_table = gpd.GeoDataFrame(result[[]], geometry=points, crs="EPSG:4326")

    joined = gpd.sjoin(point_table, borders.to_crs("EPSG:4326"),
                       how="left", predicate="within")

    joined = joined[~joined.index.duplicated(keep="first")]

    result[column] = joined["country"].values

    if verbose:
        n_found = result[column].notna().sum()
        print(f"Country found for {n_found:,} of {len(result):,} hotspots "
              f"({len(result) - n_found:,} are in the sea or outside all borders)")

    return result

def keep_study_countries(df,countries=None,column="country",verbose=True):
    if countries is None:
        countries = config.STUDY_COUNTRIES

    in_sea = df[column].isna()
    in_study = df[column].isin(countries)
    other_country = ~in_sea & ~in_study

    report = pd.DataFrame([
        {"reason": "in the sea / outside all borders", "rows_removed": int(in_sea.sum())},
        {"reason": "in another country", "rows_removed": int(other_country.sum())},
    ])

    result = df[in_study].reset_index(drop=True)

    if verbose:
        print(f"Kept {len(result):,} of {len(df):,} hotspots in {sorted(countries)}")
        print(report.to_string(index=False))
        if other_country.sum() > 0:
            print()
            print("Removed hotspots by country (top 5):")
            print(df.loc[other_country, column].value_counts().head().to_string())

    return result, report

def find_country_by_bbox(latitude,longitude):
    for code, box in config.COUNTRY_BBOX_APPROX.items():
        west, south, east, north = box
        if west <= longitude <= east and south <= latitude <= north:
            return code

    return None

def assign_country_bbox(df,column="country_bbox"):
    """Add a country column worked out from the rough boxes."""
    result = df.copy()
    result[column] = [
        find_country_by_bbox(lat, lon)
        for lat, lon in zip(result["latitude"], result["longitude"])
    ]
    return result

def compare_country_methods(df,reference="country",quick="country_bbox"):
    both = df[df[reference].notna() & df[quick].notna()]
    if len(both) == 0:
        return pd.DataFrame()

    agree = both[reference] == both[quick]
    summary = pd.DataFrame([{
        "comparable rows": len(both),
        "box agrees with borders": int(agree.sum()),
        "accuracy %": round(agree.sum() / len(both) * 100, 2),
    }])

    mistakes = both[~agree].groupby([reference, quick]).size()
    mistakes = mistakes.rename("rows").reset_index()
    mistakes = mistakes.rename(columns={reference: "real country", quick: "box says"})

    return summary, mistakes.sort_values("rows", ascending=False)

def clean_firms(df,countries=None,borders=None,verbose=True):
    report = {"rows_in": len(df)}

    result = standardize_time(df, verbose=verbose)

    result, n_duplicates = drop_duplicates_firms(result, verbose=verbose)
    report["duplicates_removed"] = n_duplicates

    result, invalid_report = filter_invalid(result, verbose=verbose)
    report["invalid_removed"] = int(invalid_report["rows_removed"].sum())

    result = normalize_confidence(result, verbose=verbose)

    result = assign_country(result, borders=borders, verbose=verbose)
    result, country_report = keep_study_countries(result, countries, verbose=verbose)
    report["outside_study_removed"] = int(country_report["rows_removed"].sum())

    report["rows_out"] = len(result)
    report["retained_percent"] = round(len(result) / report["rows_in"] * 100, 2)

    if verbose:
        print()
        print("=" * 60)
        for key in report:
            print(f"  {key:22s} {report[key]}")
        print("=" * 60)

    return result, report
    
def save_clean(df,path=None):
    if path is None:
        path = config.PROCESSED_DIR / "firms_clean.parquet"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    result = df.copy()

    if "confidence" in result.columns:
        result["confidence"] = result["confidence"].astype(str)

    for column in ["acq_datetime_utc", "acq_datetime_local", "date"]:
        if column in result.columns:
            if isinstance(result[column].dtype, pd.DatetimeTZDtype):
                result[column] = result[column].dt.tz_localize(None)

    result.to_parquet(path, index=False)
    print(f"Saved {len(result):,} rows -> {path}")

    return path