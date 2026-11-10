import pandas as pd
import config
from features import dataset_build

WEATHER_COLUMNS = ["temp_max_c", "rainfall_7d_mm", "dry_days", "wind_speed_kmh", "soil_moisture"]

WEATHER_LABELS = {
    "temp_max_c": "Max temperature (°C)",
    "rainfall_7d_mm": "Rainfall, last 7 days (mm)",
    "dry_days": "Consecutive dry days",
    "wind_speed_kmh": "Wind speed (km/h)",
    "soil_moisture": "Soil moisture (m³/m³)",
}

def sample_cell_days(years=None,fraction=0.05,seed=config.RANDOM_SEED,columns=None,verbose=True):
    if years is None:
        years = config.PROCESSING_YEARS
    if columns is None:
        columns = ["grid_id", "date", "year", "month", "country", "fire"] + WEATHER_COLUMNS

    pieces = []
    for year in years:
        table = dataset_build.load_analysis_dataset(years=[year], columns=columns)
        pieces.append(table.sample(frac=fraction, random_state=seed + year))
        del table

    sample = pd.concat(pieces, ignore_index=True)
    if verbose:
        n_fire = int(sample["fire"].sum())
        print(f"Random sample: {len(sample):,} cell-days ({fraction:.0%} of each year), "
              f"{n_fire:,} with fire ({n_fire / len(sample) * 100:.2f}%)")
    return sample

def monthly_country_weather(years=None,verbose=True):    
    if years is None:
        years = config.PROCESSING_YEARS
    columns = ["country", "year", "month", "fire"] + WEATHER_COLUMNS

    pieces = []
    for year in years:
        table = dataset_build.load_analysis_dataset(years=[year], columns=columns)
        means = table.groupby(["country", "year", "month"])[["fire"] + WEATHER_COLUMNS].mean()
        means = means.rename(columns={"fire": "fire_rate"}).reset_index()
        pieces.append(means)
        del table

    monthly = pd.concat(pieces, ignore_index=True)
    monthly["fire_rate_pct"] = (monthly["fire_rate"] * 100).round(2)
    monthly = monthly.drop(columns="fire_rate")
    if verbose:
        print(f"Monthly table: {len(monthly)} rows ({monthly['country'].nunique()} countries x "
              f"{len(monthly) // monthly['country'].nunique()} months)")
    return monthly

def compare_fire_days(table,columns=None):
    if columns is None:
        columns = WEATHER_COLUMNS
    fire = table[table["fire"] == 1]
    no_fire = table[table["fire"] == 0]

    rows = []
    for column in columns:
        difference = fire[column].mean() - no_fire[column].mean()
        rows.append({
            "variable": column,
            "median_no_fire": round(no_fire[column].median(), 2),
            "median_fire": round(fire[column].median(), 2),
            "mean_no_fire": round(no_fire[column].mean(), 2),
            "mean_fire": round(fire[column].mean(), 2),
            "difference_in_sd": round(difference / table[column].std(), 2),
        })
    return pd.DataFrame(rows)

def compare_by_month(table,column):
    medians = table.groupby(["month", "fire"])[column].median().unstack("fire")
    counts = table.groupby("month")["fire"].sum()
    result = pd.DataFrame({
        "fire_days_in_sample": counts,
        "median_no_fire": medians[0].round(2),
        "median_fire": medians[1].round(2),
    })
    return result.reset_index()
    
def correlation_with_fire(table,columns=None):
    if columns is None:
        columns = WEATHER_COLUMNS
    fire_ranks = table["fire"].rank()
    rows = []
    for column in columns:
        rows.append({
            "variable": column,
            "pearson": round(table[column].corr(table["fire"]), 3),
            "spearman": round(table[column].rank().corr(fire_ranks), 3),
        })
    result = pd.DataFrame(rows)
    result["strength_rank"] = result["spearman"].abs().rank(ascending=False).astype("int64")
    return result.sort_values("strength_rank").reset_index(drop=True)
    
def correlation_matrix(table,columns=None):
    if columns is None:
        columns = WEATHER_COLUMNS + ["fire"]
    ranks = table[columns].rank()
    return ranks.corr().round(2)
    
def fire_rate_by_bins(table,column,n_bins=10):   
    groups = pd.qcut(table[column], q=n_bins, duplicates="drop")
    result = table.groupby(groups, observed=True).agg(
        rows=("fire", "count"),
        fire_days=("fire", "sum"),
        median_value=(column, "median"),
    )
    result["fire_rate_pct"] = (result["fire_days"] / result["rows"] * 100).round(2)
    result = result.reset_index().rename(columns={column: "group"})
    result["group"] = result["group"].astype(str)
    return result