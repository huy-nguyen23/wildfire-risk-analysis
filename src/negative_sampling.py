import pandas as pd
from pathlib import Path
import config 
import schema
import gc
import dataset_build

def neighbour_grid_ids(grid_id,buffer_cells=1):
    if buffer_cells < 0:
        raise ValueError(f"buffer_cells must be 0 or more, got {buffer_cells}")

    lat, lon = schema.grid_id_to_latlon(grid_id)
    lat_step = schema.snap_to_grid(lat)
    lon_step = schema.snap_to_grid(lon)

    neighbours = []
    for d_lat in range(-buffer_cells, buffer_cells + 1):
        for d_lon in range(-buffer_cells, buffer_cells + 1):
            cell_lat = (lat_step + d_lat) * schema.GRID_SIZE_DEG
            cell_lon = (lon_step + d_lon) * schema.GRID_SIZE_DEG
            neighbours.append(f"{cell_lat:.1f}_{cell_lon:.1f}")
    return neighbours

def mark_near_fire(df,buffer_cells=1,buffer_days=1,fire_rows=None,verbose=True):
    if buffer_days < 0:
        raise ValueError(f"buffer_days must be 0 or more, got {buffer_days}")

    result = df.copy()
    result["date"] = pd.to_datetime(result["date"])

    if fire_rows is None: 
        fire_rows = result[result["fire"] == 1]

    # Step 1: collect every (grid_id, date) that lies inside some fire's buffer
    blocked_keys = set()
    for grid_id, date in zip(fire_rows["grid_id"], fire_rows["date"]):
        cells = neighbour_grid_ids(grid_id, buffer_cells)
        for day_shift in range(-buffer_days, buffer_days + 1):
            shifted_date = date + pd.Timedelta(days=day_shift)
            for cell in cells:
                blocked_keys.add((cell, shifted_date))

    # Step 2: flag the non-fire rows whose key is in that set
    near_fire = []
    for grid_id, date, fire in zip(result["grid_id"], result["date"], result["fire"]):
        if fire == 0 and (grid_id, date) in blocked_keys:
            near_fire.append(1)
        else:
            near_fire.append(0)
    result["near_fire"] = near_fire
    result["near_fire"] = result["near_fire"].astype("int64")

    if verbose:
        n_negative = int((result["fire"] == 0).sum())
        n_near = int(result["near_fire"].sum())
        print(f"Buffer: {buffer_cells} cell(s) (~{buffer_cells * 11} km), {buffer_days} day(s)")
        print(f"  Non-fire rows:            {n_negative:,}")
        print(f"  Inside a fire buffer:     {n_near:,} ({n_near / n_negative * 100:.1f}%)")
        print(f"  Usable as negatives:      {n_negative - n_near:,}")

    return result

def sample_negatives(df,n_wanted,seed=42,verbose=True):
    if "near_fire" not in df.columns:
        raise ValueError("Column 'near_fire' is missing. Run mark_near_fire() first.")

    pool = df[(df["fire"] == 0) & (df["near_fire"] == 0)]

    if n_wanted > len(pool):
        if verbose:
            print(f"  WARNING: asked for {n_wanted:,} negatives, only {len(pool):,} available. Using all.")
        return pool.copy()

    return pool.sample(n=n_wanted, random_state=seed)

def build_training_sample(df,ratio=3,buffer_cells=1,buffer_days=1,seed=42,fire_rows=None,verbose=True):
    if ratio <= 0:
        raise ValueError(f"ratio must be positive, got {ratio}")

    marked = mark_near_fire(df, buffer_cells, buffer_days,fire_rows=fire_rows, verbose=verbose)

    positives = marked[marked["fire"] == 1].copy()
    n_negative_total = int((marked["fire"] == 0).sum())
    n_near_fire = int(marked["near_fire"].sum())

    n_wanted = int(round(len(positives) * ratio))
    negatives = sample_negatives(marked, n_wanted, seed=seed, verbose=verbose)

    positives["sample_weight"] = 1.0
    negatives["sample_weight"] = n_negative_total / len(negatives)

    sample = pd.concat([positives, negatives], ignore_index=True)
    sample = sample.sort_values(["date", "grid_id"]).reset_index(drop=True)

    report = {
        "panel_rows": len(marked),
        "fire_rows": len(positives),
        "non_fire_rows": n_negative_total,
        "excluded_near_fire": n_near_fire,
        "negative_pool": n_negative_total - n_near_fire,
        "negatives_sampled": len(negatives),
        "negatives_not_used": n_negative_total - len(negatives),
        "sample_rows": len(sample),
        "ratio_requested": ratio,
        "ratio_actual": round(len(negatives) / len(positives), 2),
        "fire_rate_panel_pct": round(len(positives) / len(marked) * 100, 2),
        "fire_rate_sample_pct": round(len(positives) / len(sample) * 100, 2),
    }

    if verbose:
        print(f"Training sample: {len(sample):,} rows")
        print(f"  Fire rows (all kept):     {len(positives):,}")
        print(f"  Non-fire rows sampled:    {len(negatives):,} (ratio 1 : {report['ratio_actual']})")
        print(f"  Fire rate: panel {report['fire_rate_panel_pct']}% -> sample {report['fire_rate_sample_pct']}%")

    return sample, report

def class_balance(df,by="month"):
    if by not in df.columns:
        raise ValueError(f"Column '{by}' not found in the table")

    table = df.groupby(by)["fire"].agg(["count", "sum"])
    table = table.rename(columns={"count": "rows", "sum": "fire_rows"})
    table["non_fire_rows"] = table["rows"] - table["fire_rows"]
    table["fire_rate_pct"] = (table["fire_rows"] / table["rows"] * 100).round(1)
    return table.reset_index()

def compare_ratios(df,ratios,buffer_cells=1,buffer_days=1,seed=42):
    marked = mark_near_fire(df, buffer_cells, buffer_days, verbose=False)
    n_fire = int((marked["fire"] == 1).sum())
    n_pool = int(((marked["fire"] == 0) & (marked["near_fire"] == 0)).sum())
    del marked

    rows = []
    for ratio in ratios:
        n_wanted = int(round(n_fire * ratio))
        if n_wanted > n_pool:
            n_negatives = n_pool   # the pool runs out: every usable negative is taken
        else:
            n_negatives = n_wanted

        sample_rows = n_fire + n_negatives
        rows.append({
            "ratio": f"1:{ratio}",
            "sample_rows": sample_rows,
            "fire_rows": n_fire,
            "negatives_sampled": n_negatives,
            "fire_rate_pct": round(n_fire / sample_rows * 100, 2),
            "share_of_pool_used_pct": round(n_negatives / n_pool * 100, 1),
        })
    return pd.DataFrame(rows)

def validate_training_sample(sample,verbose=True):
    problems = []

    duplicates = schema.check_primary_key(sample, verbose=False)
    if duplicates is not None and len(duplicates) > 0:
        problems.append(f"{len(duplicates)} rows share a (grid_id, date) key")

    n_buffered = int(((sample["fire"] == 0) & (sample["near_fire"] == 1)).sum())
    if n_buffered > 0:
        problems.append(f"{n_buffered} negatives come from inside a fire buffer")

    labels = sorted(sample["fire"].unique().tolist())
    if labels != [0, 1]:
        problems.append(f"Expected labels [0, 1], found {labels}")

    schema_problems = schema.validate_schema(sample, verbose=False)
    for problem in schema_problems:
        problems.append(problem)

    if verbose:
        if len(problems) == 0:
            print(f"Training sample check: OK - {len(sample):,} rows")
        else:
            print(f"Training sample check: {len(problems)} problem(s)")
            for problem in problems:
                print(f"  - {problem}")

    return problems

def fires_near_year(fire_df,year,buffer_days=1):
    dates = pd.to_datetime(fire_df["date"])
    first_day = pd.Timestamp(year=year, month=1, day=1) - pd.Timedelta(days=buffer_days)
    last_day = pd.Timestamp(year=year, month=12, day=31) + pd.Timedelta(days=buffer_days)
    keep = (dates >= first_day) & (dates <= last_day)
    return pd.DataFrame({"grid_id": fire_df.loc[keep, "grid_id"], "date": dates[keep]})

def build_training_sample_by_year(years=None,ratio=3,buffer_cells=1,buffer_days=1,seed=42,verbose=True):
    if years is None:
        years = config.PROCESSING_YEARS

    # All fire cell-days of every year (small table), for the buffers
    fire_df = pd.read_parquet(config.PROCESSED_FILES["fire_weather_landcover"], columns=["grid_id", "date"])

    samples = []
    report_rows = []
    for year in years:
        if verbose:
            print(f"--- {year} ---")

        panel = dataset_build.load_analysis_dataset(years=[year])
        nearby_fires = fires_near_year(fire_df, year, buffer_days)

        sample, report = build_training_sample(
            panel, ratio=ratio, buffer_cells=buffer_cells, buffer_days=buffer_days,
            seed=seed, fire_rows=nearby_fires, verbose=verbose,
        )
        report["year"] = year
        report_rows.append(report)
        samples.append(sample)

        # Free this year's panel before the next one is read
        del panel
        gc.collect()

    full_sample = pd.concat(samples, ignore_index=True)
    full_sample = full_sample.sort_values(["date", "grid_id"]).reset_index(drop=True)

    report_table = pd.DataFrame(report_rows)
    first_columns = ["year", "panel_rows", "fire_rows", "excluded_near_fire",
                     "negatives_sampled", "sample_rows", "fire_rate_panel_pct"]
    other_columns = [c for c in report_table.columns if c not in first_columns]
    report_table = report_table[first_columns + other_columns]

    if verbose:
        print(f"Training sample, all years: {len(full_sample):,} rows "
              f"({int(full_sample['fire'].sum()):,} fire rows)")

    return full_sample, report_table
    
def save_training_sample(sample,path=None,verbose=True):
    if path is None:
        path = config.PROCESSED_FILES["training_sample"]

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sample.to_parquet(path, index=False)

    if verbose:
        size_mb = path.stat().st_size / (1024 * 1024)
        print(f"Saved training sample: {len(sample):,} rows -> {path} ({size_mb:.2f} MB)")

    return path

if __name__=="__main__":
    training_sample, sampling_report = build_training_sample_by_year(
        ratio=config.NEGATIVE_RATIO, buffer_cells=config.BUFFER_CELLS,
        buffer_days=config.BUFFER_DAYS, seed=config.RANDOM_SEED,
    )
    print(sampling_report)
    validate_training_sample(training_sample)
    save_training_sample(training_sample)