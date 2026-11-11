import pandas as pd
from analysis import weather_links

LANDCOVER_COLUMNS = ["land_cover_dominant", "forest_pct"]

POINT_COLUMNS = ["heat_points", "rain_points", "soil_points", "wind_points", "landcover_points"]

LEVELS = ["Low", "Medium", "High"]

SCORE_RULES = pd.DataFrame([
    {"component": "heat_points", "variable": "temp_max_c", "0 points": "below 30 °C", "1 point": "30 to 34 °C", "2 points": "34 °C or more"},
    {"component": "rain_points", "variable": "rainfall_7d_mm", "0 points": "more than 20 mm", "1 point": "2 to 20 mm", "2 points": "2 mm or less"},
    {"component": "soil_points", "variable": "soil_moisture", "0 points": "0.30 or more", "1 point": "below 0.30", "2 points": "-"},
    {"component": "wind_points", "variable": "wind_speed_kmh", "0 points": "below 3 or above 9 km/h", "1 point": "3 to 9 km/h", "2 points": "-"},
    {"component": "landcover_points", "variable": "forest_pct, land_cover_dominant", "0 points": "dense forest, cleared or built-up land", "1 point": "20-90% forest, or mostly grassland", "2 points": "-"},
])

def sample_for_scoring(years=None,fraction=0.05,verbose=True):
    columns = (["grid_id", "date", "year", "month", "country", "fire"] + weather_links.WEATHER_COLUMNS + LANDCOVER_COLUMNS + ["fire_weather_index"])
    return weather_links.sample_cell_days(years=years, fraction=fraction, columns=columns, verbose=verbose)
    
def heat_points(temp_max_c,mild=30,hot=34):
    points = pd.Series(0, index=temp_max_c.index)
    points[temp_max_c >= mild] = 1
    points[temp_max_c >= hot] = 2
    return points
    
def rain_points(rainfall_7d_mm,little=20,almost_none=2):
    points = pd.Series(0, index=rainfall_7d_mm.index)
    points[rainfall_7d_mm <= little] = 1
    points[rainfall_7d_mm <= almost_none] = 2
    return points
    
def soil_points(soil_moisture,dry=0.30):
    return (soil_moisture < dry).astype("int64")
    
def wind_points(wind_speed_kmh,low=3,high=9):
    return wind_speed_kmh.between(low, high).astype("int64")
    
def landcover_points(table,forest_low=20,forest_high=90):
    mixed = table["forest_pct"].between(forest_low, forest_high)
    grassland = table["land_cover_dominant"] == "grassland"
    return (mixed | grassland).astype("int64")
    
def add_risk_score(table):
    result = table.copy()
    result["heat_points"] = heat_points(result["temp_max_c"])
    result["rain_points"] = rain_points(result["rainfall_7d_mm"])
    result["soil_points"] = soil_points(result["soil_moisture"])
    result["wind_points"] = wind_points(result["wind_speed_kmh"])
    result["landcover_points"] = landcover_points(result)
    result["risk_score"] = result[POINT_COLUMNS].sum(axis=1)
    return result
    
def risk_level(score,medium_from=3,high_from=5):
    level = pd.Series("Low", index=score.index)
    level[score >= medium_from] = "Medium"
    level[score >= high_from] = "High"
    return pd.Categorical(level, categories=LEVELS, ordered=True)
    
def explain_score(row):
    rows = []
    for component, variable in zip(POINT_COLUMNS, SCORE_RULES["variable"]):
        values = []
        for name in variable.split(", "):
            if isinstance(row[name], float):
                values.append(f"{row[name]:.2f}")
            else:
                values.append(str(row[name]))
        rows.append({"component": component, "value": ", ".join(values), "points": int(row[component])})
    rows.append({"component": "risk_score", "value": str(row["risk_level"]), "points": int(row["risk_score"])})
    return pd.DataFrame(rows)
    
def fire_rate_by_group(table,group):
    result = table.groupby(group, observed=True)["fire"].agg(cell_days="count", fire_days="sum")
    result["share_of_cell_days_pct"] = (result["cell_days"] / result["cell_days"].sum() * 100).round(1)
    result["share_of_fires_pct"] = (result["fire_days"] / result["fire_days"].sum() * 100).round(1)
    result["fire_rate_pct"] = (result["fire_days"] / result["cell_days"] * 100).round(2)
    return result.reset_index()
    
def compare_thresholds(table,options,score_column="risk_score"):
    total_fires = table["fire"].sum()
    rows = []
    for medium_from, high_from in options:
        level = risk_level(table[score_column], medium_from, high_from)
        high = table[level == "High"]
        low = table[level == "Low"]
        rows.append({
            "medium_from": medium_from,
            "high_from": high_from,
            "high_share_of_days_pct": round(len(high) / len(table) * 100, 1),
            "fires_caught_by_high_pct": round(high["fire"].sum() / total_fires * 100, 1),
            "fire_rate_in_high_pct": round(high["fire"].mean() * 100, 2),
            "fires_missed_in_low_pct": round(low["fire"].sum() / total_fires * 100, 1),
            "fire_rate_in_low_pct": round(low["fire"].mean() * 100, 2),
        })
    return pd.DataFrame(rows)
    
def ranking_quality(table,score_column):
    ranks = table[score_column].rank()
    n_fire = int(table["fire"].sum())
    n_no_fire = len(table) - n_fire
    fire_rank_sum = ranks[table["fire"] == 1].sum()
    return (fire_rank_sum - n_fire * (n_fire + 1) / 2) / (n_fire * n_no_fire)
    
def compare_scores(table,score_columns):
    rows = []
    for column in score_columns:
        rows.append({"score": column, "ranking_quality": round(ranking_quality(table, column), 3)})
    return pd.DataFrame(rows)

def same_alarm_comparison(table,other_columns,level_column="risk_level"):
    total_fires = table["fire"].sum()
    high = table[table[level_column] == "High"]
    rows = [{
        "method": "risk score: High",
        "days_flagged_pct": round(len(high) / len(table) * 100, 1),
        "fires_caught_pct": round(high["fire"].sum() / total_fires * 100, 1),
    }]
    for column in other_columns:
        top = table.nlargest(len(high), column)
        rows.append({
            "method": f"top {column}",
            "days_flagged_pct": round(len(top) / len(table) * 100, 1),
            "fires_caught_pct": round(top["fire"].sum() / total_fires * 100, 1),
        })
    return pd.DataFrame(rows)
    
def monthly_risk_vs_fire(table,level_column="risk_level"):
    rows = []
    for month, part in table.groupby("month"):
        rows.append({
            "month": month,
            "high_share_pct": round((part[level_column] == "High").mean() * 100, 1),
            "mean_score": round(part["risk_score"].mean(), 2),
            "fire_rate_pct": round(part["fire"].mean() * 100, 2),
        })
    return pd.DataFrame(rows)