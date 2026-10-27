import pandas as pd
from pathlib import Path
import config
import schema
import time
import gc
import feature_engineering

def component_paths(processed_dir=None):
    if processed_dir is None:
        return (config.PROCESSED_FILES["weather_daily"],
                config.PROCESSED_FILES["landcover_cells"],
                config.PROCESSED_FILES["fire_weather_landcover"])

    processed_dir = Path(processed_dir)
    return (processed_dir / "weather_daily.parquet",
            processed_dir / "landcover_cells.parquet",
            processed_dir / "fire_weather_landcover.parquet")
    
def check_exists(path,what):
    if not Path(path).exists():
        raise FileNotFoundError(f"{what} not found at {path}. Run scripts/build_dataset.py first.")

def load_weather(year=None,processed_dir=None):
    weather_path, _, _ = component_paths(processed_dir)
    check_exists(weather_path, "Weather table")

    if year is None:
        return pd.read_parquet(weather_path)
    return pd.read_parquet(weather_path, filters=[("year", "==", year)])

def load_landcover_and_fires(processed_dir=None):
    _, landcover_path, fire_path = component_paths(processed_dir)
    check_exists(landcover_path, "Land cover table")
    check_exists(fire_path, "Fire table")
    return pd.read_parquet(landcover_path), pd.read_parquet(fire_path)

def load_clean_components(processed_dir=None,year=None,verbose=True):
    weather_df = load_weather(year, processed_dir)
    landcover_df, fire_df = load_landcover_and_fires(processed_dir)

    if verbose:
        print(f"Loaded weather panel:     {len(weather_df):,} daily grid-cell rows")
        print(f"Loaded land cover table:  {len(landcover_df):,} distinct grid cells")
        print(f"Loaded fire detections:   {len(fire_df):,} cell-days with fire")

    return weather_df, landcover_df, fire_df

def build_analysis_panel(weather_df,landcover_df,fire_df,verbose=True):
    lc_columns = [
        "grid_id",
        "land_cover_dominant",
        "forest_pct",
        "grassland_pct",
        "cropland_pct",
        "other_pct",
        "landcover_coverage_pct",
    ]
    available_lc_cols = [c for c in lc_columns if c in landcover_df.columns]
    lc_clean = landcover_df[available_lc_cols].drop_duplicates(subset=["grid_id"])

    panel = weather_df.merge(lc_clean, on="grid_id", how="left")

    fire_summary_cols = ["grid_id", "date", "fire", "hotspot_count", "frp_max", "frp_sum", "country"]
    available_fire_cols = [c for c in fire_summary_cols if c in fire_df.columns]
    fire_summary = fire_df[available_fire_cols].drop_duplicates(subset=["grid_id", "date"])

    panel = panel.merge(fire_summary, on=["grid_id", "date"], how="left")

    panel["fire"] = panel["fire"].fillna(0).astype("int64")
    panel["hotspot_count"] = panel["hotspot_count"].fillna(0).astype("int64")
    panel["frp_max"] = panel["frp_max"].fillna(0.0).astype("float64")
    panel["frp_sum"] = panel["frp_sum"].fillna(0.0).astype("float64")

    if "country" in panel.columns and "country" in fire_df.columns:
        cell_to_country = fire_df.groupby("grid_id")["country"].first().to_dict()
        panel["country"] = panel["country"].fillna(panel["grid_id"].map(cell_to_country))

    panel["date"] = pd.to_datetime(panel["date"])
    if "year" not in panel.columns:
        panel["year"] = panel["date"].dt.year
    if "month" not in panel.columns:
        panel["month"] = panel["date"].dt.month

    if "latitude" not in panel.columns or "longitude" not in panel.columns:
        coords = [schema.grid_id_to_latlon(gid) for gid in panel["grid_id"]]
        panel["latitude"] = [lat for lat, _ in coords]
        panel["longitude"] = [lon for _, lon in coords]

    panel = schema.apply_schema_dtypes(panel)

    if verbose:
        n_fire = int((panel["fire"] == 1).sum())
        n_no_fire = int((panel["fire"] == 0).sum())
        fire_rate = n_fire / len(panel) * 100
        print(f"Built master panel: {len(panel):,} total rows")
        print(f"  Fire days (fire = 1):     {n_fire:,} ({fire_rate:.2f}%)")
        print(f"  Non-fire days (fire = 0): {n_no_fire:,} ({100 - fire_rate:.2f}%)")

    return panel
    
def validate_analysis_dataset(df,verbose=True):
    pk_duplicates = schema.check_primary_key(df, verbose=False)
    problems = schema.validate_schema(df, verbose=False)

    if verbose:
        if len(pk_duplicates) == 0:
            print("Primary key check: PASSED (unique grid_id, date across all rows)")
        else:
            print(f"Primary key check: FAILED ({len(pk_duplicates)} duplicate rows found!)")

        if len(problems) == 0:
            print("Schema validation: PASSED (all schema columns and ranges valid)")
        else:
            print(f"Schema validation: {len(problems)} issues found:")
            for p in problems[:5]:
                print(f"  - {p}")

    return problems 
    
def analysis_year_path(year,folder=None):
    if folder is None:
        folder = config.PROCESSED_FILES["analysis_dataset"]
    return Path(folder) / f"analysis_{year}.parquet"
    
def save_analysis_dataset(df,year,folder=None,verbose=True):
    other_years = sorted(set(df["year"].unique().tolist()) - {year})
    if len(other_years) > 0:
        raise ValueError(f"Table for {year} also has rows from {other_years}. Save one year at a time.")

    path = analysis_year_path(year, folder)
    path.parent.mkdir(parents=True, exist_ok=True)

    df.to_parquet(path, index=False)

    if verbose:
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"Saved analysis dataset: {len(df):,} rows -> {path} ({size_mb:.2f} MB)")

    return path
    
def load_analysis_dataset(years=None,columns=None,folder=None):
    if years is None:
        years = config.PROCESSING_YEARS

    tables = []
    for year in years:
        path = analysis_year_path(year, folder)
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing. Run scripts/build_dataset.py first.")
        tables.append(pd.read_parquet(path, columns=columns))

    return pd.concat(tables, ignore_index=True)
    
def build_year(year,landcover_df,fire_df,processed_dir=None,verbose=True):
    weather_df = load_weather(year, processed_dir)
    if len(weather_df) == 0:
        raise ValueError(f"The weather table has no rows for {year}. Check config.PROCESSING_YEARS.")

    panel = build_analysis_panel(weather_df, landcover_df, fire_df, verbose=verbose)
    del weather_df

    dataset = feature_engineering.add_engineered_features(panel, verbose=False)
    del panel

    problems = validate_analysis_dataset(dataset, verbose=verbose)
    return dataset, problems
    
def build_all_years(years=None,processed_dir=None,save=True,verbose=True):
    if years is None:
        years = config.PROCESSING_YEARS

    landcover_df, fire_df = load_landcover_and_fires(processed_dir)

    report_rows = []
    for year in years:
        start = time.time()
        if verbose:
            print(f"--- {year} ---")

        dataset, problems = build_year(year, landcover_df, fire_df, processed_dir, verbose=verbose)
        if save:
            save_analysis_dataset(dataset, year, verbose=verbose)

        n_fire = int(dataset["fire"].sum())
        report_rows.append({
            "year": year,
            "rows": len(dataset),
            "grid_cells": dataset["grid_id"].nunique(),
            "fire_rows": n_fire,
            "fire_rate_pct": round(n_fire / len(dataset) * 100, 2),
            "schema_problems": len(problems),
            "seconds": round(time.time() - start, 1),
        })

        del dataset
        gc.collect()

    return pd.DataFrame(report_rows)
    
def build_full_pipeline(processed_dir=None,save=True,verbose=True):
    if verbose:
        print("=" * 65)
        print("BUILDING ANALYSIS DATASET")
        print("=" * 65)

    return build_all_years(processed_dir=processed_dir, save=save, verbose=verbose)

if __name__=="__main__":
    print(build_full_pipeline())
    
    