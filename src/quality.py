import gc
import pandas as pd
import config
import schema

from features import dataset_build

def missing_values(years=None):
    if years is None:
        years = config.PROCESSING_YEARS

    rows = []
    for year in years:
        table = dataset_build.load_analysis_dataset(years=[year])
        counts = table.isna().sum()
        row = {"year": year, "rows": len(table)}
        for column, n in counts.items():
            # the key "year" already holds the year itself
            if column != "year":
                row[column] = int(n)
        rows.append(row)
        del table
        gc.collect()

    result = pd.DataFrame(rows).set_index("year")
    keep = ["rows"]
    for column in result.columns:
        if column != "rows" and result[column].sum() > 0:
            keep.append(column)
    return result[keep]
    
def duplicate_keys(years=None):
    if years is None:
        years = config.PROCESSING_YEARS

    rows = []
    for year in years:
        keys = dataset_build.load_analysis_dataset(years=[year], columns=schema.PRIMARY_KEY)
        rows.append({
            "year": year,
            "rows": len(keys),
            "repeated_keys": int(keys.duplicated().sum()),
            "rows_from_other_years": int((keys["date"].dt.year != year).sum()),
        })
        del keys
        gc.collect()
    return pd.DataFrame(rows)

def rule_problems(years=None):
    if years is None:
        years = config.PROCESSING_YEARS

    rows = []
    for year in years:
        table = dataset_build.load_analysis_dataset(years=[year])
        for problem in schema.validate_schema(table, verbose=False):
            rows.append({"year": year, "problem": problem})
        del table
        gc.collect()
    return pd.DataFrame(rows, columns=["year", "problem"])
    
def extremes(column,n=3,largest=True,years=None):
    if years is None:
        years = config.PROCESSING_YEARS

    columns = ["grid_id", "date", "latitude", "longitude", "country", column]
    pieces = []
    for year in years:
        table = dataset_build.load_analysis_dataset(years=[year], columns=columns)
        if largest:
            pieces.append(table.nlargest(n, column))
        else:
            pieces.append(table.nsmallest(n, column))
        del table

    combined = pd.concat(pieces, ignore_index=True)
    if largest:
        return combined.nlargest(n, column).reset_index(drop=True)
    return combined.nsmallest(n, column).reset_index(drop=True)
    
def compare_with_neighbours(grid_id,date,column):
    from features import negative_sampling

    date = pd.Timestamp(date)
    table = dataset_build.load_analysis_dataset(years=[date.year], columns=["grid_id", "date", column])
    that_day = table[table["date"] == date].set_index("grid_id")[column]
    del table

    rows = []
    for cell in negative_sampling.neighbour_grid_ids(grid_id, buffer_cells=1):
        if cell in that_day.index:
            value = round(float(that_day[cell]), 2)
        else:
            value = None
        rows.append({"grid_id": cell, "is_checked_cell": cell == grid_id, column: value})
    return pd.DataFrame(rows)
    
def cells_by_country(cell_countries=None):
    if cell_countries is None:
        cell_countries = dataset_build.load_cell_countries()

    table = cell_countries.groupby("country", dropna=False).agg(
        cells=("grid_id", "count"), in_study_area=("in_study_area", "max"))
    table["share_pct"] = (table["cells"] / table["cells"].sum() * 100).round(1)
    return table.sort_values("cells", ascending=False).reset_index()
    
def hotspot_vs_cell_country(cell_countries=None):
    if cell_countries is None:
        cell_countries = dataset_build.load_cell_countries()

    fires = pd.read_parquet(config.PROCESSED_FILES["fire_weather_landcover"], columns=["grid_id", "date", "country"])
    fires = fires.rename(columns={"country": "hotspot_country"})
    fires = fires.merge(cell_countries[["grid_id", "country", "in_study_area"]], on="grid_id", how="left")
    fires = fires.rename(columns={"country": "cell_country"})

    table = fires.groupby(["hotspot_country", "cell_country"], dropna=False).size().reset_index(name="fire_cell_days")
    table["same_country"] = table["hotspot_country"] == table["cell_country"]
    return table.sort_values("fire_cell_days", ascending=False).reset_index(drop=True)
    
def counts_by_country_year(years=None,cell_countries=None):
    if years is None:
        years = config.PROCESSING_YEARS
    if cell_countries is None:
        cell_countries = dataset_build.load_cell_countries()

    firms = pd.read_parquet(config.PROCESSED_FILES["firms_clean"], columns=["country", "year"])
    hotspots = firms.groupby(["country", "year"]).size().rename("hotspots")
    del firms

    pieces = []
    for year in years:
        table = dataset_build.load_analysis_dataset(years=[year], columns=["country", "fire"])
        counts = table.groupby("country")["fire"].sum().rename("fire_cell_days").to_frame()
        counts["year"] = year
        pieces.append(counts.reset_index())
        del table
    fire_days = pd.concat(pieces, ignore_index=True).set_index(["country", "year"])

    in_area = cell_countries[cell_countries["in_study_area"] == 1]
    cells = in_area.groupby("country").size().rename("cells")

    result = fire_days.join(hotspots, how="left").reset_index()
    result = result.merge(cells, left_on="country", right_index=True, how="left")
    result["fire_days_per_cell"] = (result["fire_cell_days"] / result["cells"]).round(2)
    return result[["country", "year", "cells", "hotspots", "fire_cell_days", "fire_days_per_cell"]]