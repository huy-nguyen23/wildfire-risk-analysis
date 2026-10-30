import argparse
import logging
import sys 
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd 
import pipeline
import config

log=logging.getLogger("build_dataset")

STEPS = ["firms", "weather", "fire_weather", "landcover", "countries", "dataset", "sample"]

STEP_OUTPUTS = {
    "firms": ["firms_clean"],
    "weather": ["weather_daily"],
    "fire_weather": ["fire_weather"],
    "landcover": ["landcover_cells", "fire_weather_landcover"],
    "countries": ["cell_countries"],
    "dataset": ["analysis_dataset"],
    "sample": ["training_sample"],
}

def read_table(name,columns=None):
    path = config.PROCESSED_FILES[name]
    if not path.exists():
        raise FileNotFoundError(f"{path.name} is missing. Run the step that makes it first.")
    return pd.read_parquet(path, columns=columns)   

def step_is_done(step):
    if step == "dataset":
        from features import dataset_build
        for year in config.PROCESSING_YEARS:
            if not dataset_build.analysis_year_path(year).exists():
                return False
        return True

    for name in STEP_OUTPUTS[step]:
        if not config.PROCESSED_FILES[name].exists():
            return False
    return True

def log_report(report):
    for key in report:
        log.info("    %-28s %s", key, report[key])
    
def run_firms_step():
    from cleaners import firms_clean

    raw = firms_clean.load_raw_firms(verbose=False)
    clean, report = firms_clean.clean_firms(raw, verbose=False)
    firms_clean.save_clean(clean)
    return report

def run_weather_step():
    from cleaners import era5_clean
    from features import feature_engineering

    log.info("    region %s, years %s", config.PROCESSING_REGION, config.PROCESSING_YEARS)
    daily, report = era5_clean.clean_era5_folder(verbose=False)
    daily = feature_engineering.add_weather_features(daily, verbose=False)
    era5_clean.save_daily(daily)
    return report
    
def run_fire_weather_step():
    from joins import spatial_join

    firms = read_table("firms_clean")
    joined, unmatched, report = spatial_join.build_fire_weather_by_year(
        firms, config.PROCESSED_FILES["weather_daily"], config.PROCESSING_YEARS, verbose=False)
    spatial_join.save_fire_weather(joined)
    return report
    
def run_landcover_step():
    from joins import landcover_join

    grid_ids = read_table("weather_daily", columns=["grid_id"])["grid_id"].unique()
    fire_weather = read_table("fire_weather")

    maps = landcover_join.load_all_landcover(verbose=False)
    cells = landcover_join.landcover_for_cells(grid_ids, maps, verbose=False)
    landcover_join.save_landcover_cells(cells)

    final = landcover_join.add_landcover(fire_weather, cells, verbose=False)
    landcover_join.save_fire_weather_landcover(final)

    return {
        "cells": len(cells),
        "cells_with_landcover": int(cells["land_cover_dominant"].notna().sum()),
        "fire_rows": len(final),
        "fire_rows_without_landcover": int(final["land_cover_dominant"].isna().sum()),
    }
    
def run_countries_step():
    from joins import country_join

    grid_ids = read_table("weather_daily", columns=["grid_id"])["grid_id"].unique()
    cells = country_join.country_for_cells(grid_ids, max_distance_km=config.COASTAL_MAX_DISTANCE_KM,
                                           verbose=False)
    country_join.save_cell_countries(cells)

    report = {
        "cells": len(cells),
        "cells_in_study_area": int(cells["in_study_area"].sum()),
        "cells_outside": int((cells["in_study_area"] == 0).sum()),
        "coastal_nearest_country": int((cells["country_method"] == "nearest").sum()),
        "no_country": int((cells["country_method"] == "none").sum()),
    }
    for country, n in cells["country"].value_counts().items():
        report[f"cells_{country}"] = int(n)
    return report
    
def run_dataset_step():
    from features import dataset_build

    report = dataset_build.build_all_years(verbose=False)
    for row in report.to_dict("records"):
        log.info("    %d: %s rows, %s fire rows (%s%%), %s schema problem(s), %s s",
                 row["year"], f"{row['rows']:,}", f"{row['fire_rows']:,}",
                 row["fire_rate_pct"], row["schema_problems"], row["seconds"])
        log.info("          outside the study area: %s cells, %s rows removed (%s with fire)",
                 f"{row['cells_removed']:,}", f"{row['rows_removed']:,}", f"{row['fire_rows_removed']:,}")
        if row["schema_problems"] > 0:
            log.warning("    %d has schema problems - check it in notebooks/10_analysis_dataset.ipynb", row["year"])

    return {
        "years": len(report),
        "rows": int(report["rows"].sum()),
        "fire_rows": int(report["fire_rows"].sum()),
        "schema_problems": int(report["schema_problems"].sum()),
    }
    
    
def run_sample_step():
    from features import negative_sampling

    sample, yearly = negative_sampling.build_training_sample_by_year(
        ratio=config.NEGATIVE_RATIO,
        buffer_cells=config.BUFFER_CELLS,
        buffer_days=config.BUFFER_DAYS,
        seed=config.RANDOM_SEED,
        verbose=False,
    )
    for row in yearly.to_dict("records"):
        log.info("    %d: %s fire rows + %s negatives (%s excluded by the buffer)",
                 row["year"], f"{row['fire_rows']:,}", f"{row['negatives_sampled']:,}",
                 f"{row['excluded_near_fire']:,}")

    problems = negative_sampling.validate_training_sample(sample, verbose=False)
    for problem in problems:
        log.warning("    sample: %s", problem)

    negative_sampling.save_training_sample(sample, verbose=False)
    return {
        "years": len(yearly),
        "sample_rows": len(sample),
        "fire_rows": int(sample["fire"].sum()),
        "negatives_sampled": int((sample["fire"] == 0).sum()),
        "excluded_near_fire": int(yearly["excluded_near_fire"].sum()),
        "problems": len(problems),
    }
    
def run_step(step):
    if step == "firms":
        return run_firms_step()
    elif step == "weather":
        return run_weather_step()
    elif step == "fire_weather":
        return run_fire_weather_step()
    elif step == "landcover":
        return run_landcover_step()
    elif step == "countries":
        return run_countries_step()
    elif step == "dataset":
        return run_dataset_step()
    elif step == "sample":
        return run_sample_step()
    else:
        raise ValueError(f"Unknown step {step!r}. Known steps: {STEPS}")
    
    
def build_parser():
    parser = argparse.ArgumentParser(
        description="Build the wildfire analysis dataset from the raw downloads.",
    )
    parser.add_argument("--from", dest="from_step", choices=STEPS, default=None, help="redo this step and every step after it")
    parser.add_argument("--only", choices=STEPS, default=None, help="redo only this one step (e.g. firms, without the slow weather step)")
    parser.add_argument("--force", action="store_true", help="redo every step, even if its output exists")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    log_file = pipeline.setup_logging(level=args.log_level, name="build")

    if args.only is not None and (args.force or args.from_step is not None):
        raise ValueError("--only cannot be combined with --from or --force")

    if args.force:
        first_to_redo = 0
    elif args.from_step is not None:
        first_to_redo = STEPS.index(args.from_step)
    else:
        first_to_redo = len(STEPS)   # redo nothing that already exists

    log.info("build started - log file: %s", log_file)
    total_start = time.time()

    for number, step in enumerate(STEPS, start=1):
        position = number - 1
        if args.only is not None and step != args.only:
            continue
        if args.only is None and position < first_to_redo and step_is_done(step):
            log.info("[%d/%d] %s: skipped (output already exists)", number, len(STEPS), step)
            continue

        log.info("[%d/%d] %s: running", number, len(STEPS), step)
        step_start = time.time()
        try:
            report = run_step(step)
        except (FileNotFoundError, ValueError) as error:
            # Every later step needs this one, so there is no point going on
            log.error("[%d/%d] %s: FAILED - %s", number, len(STEPS), step, error)
            return 1

        log_report(report)
        log.info("[%d/%d] %s: done in %.1f s", number, len(STEPS), step, time.time() - step_start)

    log.info("build finished in %.1f s", time.time() - total_start)
    return 0


if __name__ == "__main__":
    sys.exit(main())