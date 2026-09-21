from config import BBOX_CHIANG_MAI,BBOX_CHIANG_MAI_CDS,DEFAULT_YEAR,LAND_COVER_CLASSES,DEFAULT_SOURCE,ERA5_VARIABLES,RAW_DIR
import datetime as dt
import numpy as np
import pandas as pd
import json
import firms_api,era5_api,worldcover_api
from pathlib import Path
import argparse

SOURCE_NAMES=("firms","era5","worldcover")
FIRMS_REQUIRED_COLUMNS={
    "latitude",
    "longitude",
    "acq_date",
    "acq_time",
    "frp"
}
ERA5_REQUIRED_VARIABLES={"t2m","tp","swvl1","u10","v10"}

def build_request_summary(sample_date,firms_bbox,era5_area,worldcover_year,sources,use_cache):
    return {
        "sample_date": sample_date,
        "firms_bbox_wsen": firms_bbox,
        "era5_area_nwse": list(era5_area),
        "worldcover_year": int(worldcover_year),
        "sources": list(sources),
        "use_cache": bool(use_cache)
    }
    
def _parse_firms_bbox(bbox):
    parts = str(bbox).split(",")
    if len(parts) != 4:
        raise ValueError("FIRMS bbox must contain west,south,east,north")

    try:
        west, south, east, north = (float(value) for value in parts)
    except ValueError as error:
        raise ValueError(f"FIRMS bbox contains a non-numeric value: {bbox!r}") from error

    if not (-180 <= west < east <= 180):
        raise ValueError("FIRMS bbox longitude must satisfy -180 <= west < east <= 180")
    if not (-90 <= south < north <= 90):
        raise ValueError("FIRMS bbox latitude must satisfy -90 <= south < north <= 90")
    return west, south, east, north

def validate_firms_output(dataframe,bbox):
    if not isinstance(dataframe, pd.DataFrame):
        raise TypeError("FIRMS output must be a pandas DataFrame")
    if dataframe.empty:
        raise ValueError("FIRMS output is empty")

    missing = sorted(FIRMS_REQUIRED_COLUMNS - set(dataframe.columns))
    if missing:
        raise ValueError(f"FIRMS output is missing columns: {missing}")

    west, south, east, north = _parse_firms_bbox(bbox)
    latitude = pd.to_numeric(dataframe["latitude"], errors="coerce")
    longitude = pd.to_numeric(dataframe["longitude"], errors="coerce")
    if latitude.isna().any() or longitude.isna().any():
        raise ValueError("FIRMS coordinates contain non-numeric values")
    if not latitude.between(south, north).all():
        raise ValueError("FIRMS latitude falls outside the requested bbox")
    if not longitude.between(west, east).all():
        raise ValueError("FIRMS longitude falls outside the requested bbox")

    return {
        "rows": int(len(dataframe)),
        "columns": int(len(dataframe.columns)),
        "date_min": str(dataframe["acq_date"].min()),
        "date_max": str(dataframe["acq_date"].max()),
    }
    
def validate_era5_output(dataset,expected_hours=24):
    if not hasattr(dataset, "data_vars") or not hasattr(dataset, "coords"):
        raise TypeError("ERA5-Land output must be an xarray Dataset")

    missing_variables = sorted(ERA5_REQUIRED_VARIABLES - set(dataset.data_vars))
    if missing_variables:
        raise ValueError(f"ERA5-Land output is missing variables: {missing_variables}")

    for coordinate in ("latitude", "longitude"):
        if coordinate not in dataset.coords:
            raise ValueError(f"ERA5-Land output is missing coordinate: {coordinate}")

    time_coordinate = next(
        (name for name in ("valid_time", "time") if name in dataset.coords),
        None,
    )
    if time_coordinate is None:
        raise ValueError("ERA5-Land output has no time coordinate")

    time_steps = int(dataset[time_coordinate].size)
    if time_steps != expected_hours:
        raise ValueError(f"Expected {expected_hours} hourly ERA5-Land steps, got {time_steps}")

    return {
        "time_coordinate": time_coordinate,
        "time_steps": time_steps,
        "latitude_cells": int(dataset["latitude"].size),
        "longitude_cells": int(dataset["longitude"].size),
        "variables": sorted(ERA5_REQUIRED_VARIABLES),
    }

def validate_worldcover_output(result):
    if not isinstance(result, tuple) or len(result) != 2:
        raise TypeError("WorldCover output must be a (data, transform) tuple")

    data, transform = result
    if not isinstance(data, np.ndarray):
        raise TypeError("WorldCover data must be a numpy array")
    if data.ndim != 2 or data.size == 0:
        raise ValueError("WorldCover data must be a non-empty two-dimensional array")
    if transform is None:
        raise ValueError("WorldCover output is missing its geographic transform")

    class_codes = {int(value) for value in np.unique(data)}
    known_codes = set(LAND_COVER_CLASSES) | {0}
    unknown_codes = sorted(class_codes - known_codes)
    if unknown_codes:
        raise ValueError(f"WorldCover output contains unknown class codes: {unknown_codes}")

    return {
        "rows": int(data.shape[0]),
        "columns": int(data.shape[1]),
        "class_codes": sorted(class_codes),
    }

def _close_result(result):
    close = getattr(result, "close", None)
    if callable(close):
        close()

def run_step(name,action,validator):
    started_at = dt.datetime.now(dt.UTC)
    result = None

    try:
        result = action()
        if result is None:
            raise RuntimeError("The source returned no data")
        details = validator(result)
    except Exception as error:
        finished_at = dt.datetime.now(dt.UTC)
        return {
            "source": name,
            "status": "failed",
            "error_type": type(error).__name__,
            "error": str(error),
            "started_at_utc": started_at.isoformat(),
            "finished_at_utc": finished_at.isoformat(),
            "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        }
    finally:
        _close_result(result)

    finished_at = dt.datetime.now(dt.UTC)
    return {
        "source": name,
        "status": "ok",
        "details": details,
        "started_at_utc": started_at.isoformat(),
        "finished_at_utc": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
    }

def collect_sample_data(
    sample_date="2025-03-15",
    firms_bbox=BBOX_CHIANG_MAI,
    era5_area=BBOX_CHIANG_MAI_CDS,
    worldcover_year=DEFAULT_YEAR,
    sources=SOURCE_NAMES,
    use_cache=True,
    worldcover_max_pixels=1000000
):
    date=dt.date.fromisoformat(sample_date)
    worldcover_bbox=_parse_firms_bbox(firms_bbox)
    selected_sources=tuple(dict.fromkeys(str(name).lower() for name in sources))
    unknown_sources=sorted(set(selected_sources)-set(SOURCE_NAMES))
    if unknown_sources:
        raise ValueError(f"Unknown sources: {unknown_sources}. Choose from {list(SOURCE_NAMES)}")

    steps = {
        "firms": (
            lambda: firms_api.download_firms(
                source=DEFAULT_SOURCE,
                bbox=firms_bbox,
                day_range=1,
                date=sample_date,
                use_cache=use_cache,
            ),
            lambda result: validate_firms_output(result, firms_bbox),
        ),
        "era5": (
            lambda: era5_api.download_era5(
                variables=list(ERA5_VARIABLES),
                area=list(era5_area),
                year=date.year,
                month=date.month,
                day=date.day,
                use_cache=use_cache,
            ),
            validate_era5_output,
        ),
        "worldcover": (
            lambda: worldcover_api.download_worldcover(
                bbox=worldcover_bbox,
                year=worldcover_year,
                use_cache=use_cache,
                max_pixels=worldcover_max_pixels,
            ),
            validate_worldcover_output,
        ),
    }

    return {
        name: run_step(name, *steps[name])
        for name in selected_sources
    }

def write_manifest(results,request,output_path=None):
    if output_path is None:
        safe_date = request["sample_date"].replace("-", "")
        output_path = RAW_DIR / "pipeline_runs" / f"sample_{safe_date}.json"

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": dt.datetime.now(dt.UTC).isoformat(),
        "request": request,
        "results": results,
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path

def print_summary(results):
    print("Sample collection status")
    for name, record in results.items():
        print(f"- {name}: {record['status'].upper()}")
        if record["status"] == "ok":
            details = ", ".join(
                f"{key}={value}" for key, value in record["details"].items()
            )
            print(f"  {details}")
        else:
            print(f"  {record['error_type']}: {record['error']}")
            
def _build_parser():
    """Create the command-line parser for the sample pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", default="2025-03-15", help="Sample date: YYYY-MM-DD")
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=SOURCE_NAMES,
        default=list(SOURCE_NAMES),
        help="Sources to run independently.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore existing cache files and request fresh data.",
    )
    parser.add_argument(
        "--no-manifest",
        action="store_true",
        help="Do not write the secret-free run manifest.",
    )
    return parser


def main(argv=None) -> int:
    """Run the command-line sample pipeline and return a process exit code."""
    args = _build_parser().parse_args(argv)
    use_cache = not args.no_cache
    results = collect_sample_data(
        sample_date=args.date,
        sources=args.sources,
        use_cache=use_cache,
    )
    print_summary(results)

    if not args.no_manifest:
        request = build_request_summary(
            sample_date=args.date,
            firms_bbox=BBOX_CHIANG_MAI,
            era5_area=BBOX_CHIANG_MAI_CDS,
            worldcover_year=DEFAULT_YEAR,
            sources=args.sources,
            use_cache=use_cache,
        )
        path = write_manifest(results, request)
        print(f"Manifest: {path}")

    return 0 if all(record["status"] == "ok" for record in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())