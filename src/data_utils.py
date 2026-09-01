import pandas as pd 
from config import LOCAL_TZ_OFFSET_HOURS

def describe_firms(df,name="dataset"):
    print("=" * 64)
    print(f"OVERVIEW: {name}")
    print("=" * 64)

    print(f"\n[1] Shape: {df.shape[0]} rows x {df.shape[1]} columns")

    print("\n[2] Column data types:")
    print(df.dtypes.to_string())

    print("\n[3] Missing values per column:")
    missing = df.isna().sum()
    if missing.sum() == 0:
        print("    None.")
    else:
        print(missing[missing > 0].to_string())

    print("\n[4] Categorical columns:")
    for col in ["confidence", "satellite", "instrument", "daynight", "version", "type"]:
        if col in df.columns:
            counts = df[col].value_counts(dropna=False)
            print(f"\n  {col}  ({df[col].dtype})")
            print("    " + counts.to_string().replace("\n", "\n    "))

    print("\n[5] Numeric columns:")
    numeric_cols = [c for c in ["bright_ti4", "bright_ti5", "brightness", "bright_t31",
                                "frp", "scan", "track"] if c in df.columns]
    if numeric_cols:
        print(df[numeric_cols].describe().round(2).to_string())

    print("\n" + "=" * 64)
    
def add_datetime_columns(df,tz_offset_hours=LOCAL_TZ_OFFSET_HOURS):
    df = df.copy()

    # zfill(4) restores the stripped leading zeros: 1 -> '0001', 633 -> '0633'.
    time_str = df["acq_time"].astype(int).astype(str).str.zfill(4)

    df["acq_datetime_utc"] = pd.to_datetime(
        df["acq_date"].astype(str) + " " + time_str,
        format="%Y-%m-%d %H%M",
        utc=True,
    )

    df["acq_datetime_local"] = df["acq_datetime_utc"] + pd.Timedelta(hours=tz_offset_hours)

    df["acq_date_local"] = df["acq_datetime_local"].dt.date
    df["year"] = df["acq_datetime_utc"].dt.year
    df["month"] = df["acq_datetime_utc"].dt.month
    df["hour_local"] = df["acq_datetime_local"].dt.hour

    return df

def count_date_shifts(df,verbose=True):
    if "acq_datetime_local" not in df.columns:
        df = add_datetime_columns(df)

    shifted = (df["acq_datetime_utc"].dt.date != df["acq_datetime_local"].dt.date).sum()
    total = len(df)
    pct = shifted / total * 100 if total else 0

    if verbose:
        print(f"Records that change calendar day when converted to local time: "
              f"{shifted}/{total} ({pct:.1f}%)")

    return int(shifted)

def sensor_summary(df,name):
    bright_col = "bright_ti4" if "bright_ti4" in df.columns else "brightness"

    return {
        "Sensor": name,
        "Hotspot count": len(df),
        "Median FRP (MW)": round(df["frp"].median(), 2),
        "Max FRP (MW)": round(df["frp"].max(), 2),
        f"Mean {bright_col} (K)": round(df[bright_col].mean(), 2),
        "Mean pixel area (km2)": round((df["scan"] * df["track"]).mean(), 3),
    }
    
def compare_sensors(df_modis,df_viirs):
    rows = [
        sensor_summary(df_modis, "MODIS"),
        sensor_summary(df_viirs, "VIIRS"),
    ]
    return pd.DataFrame(rows).set_index("Sensor").T

def filter_hotspots(df,min_confidence="n",vegetation_only=True,verbose=True):
    before = len(df)
    out = df.copy()

    if "confidence" in out.columns:
        # Detect the scale by dtype rather than by sensor name, and use
        # is_numeric_dtype instead of comparing against `object`: from pandas
        # 3.0 text columns are stored as StringDtype, so the older
        # `dtype == object` check misclassifies VIIRS data as MODIS.
        if pd.api.types.is_numeric_dtype(out["confidence"]):
            # MODIS: 0-100 scale
            threshold = min_confidence if isinstance(min_confidence, (int, float)) else 50
            out = out[out["confidence"] >= threshold]
        else:
            # VIIRS: l (low) / n (nominal) / h (high)
            keep = {"h"} if min_confidence == "h" else {"n", "h"}
            out = out[out["confidence"].astype(str).str.lower().isin(keep)]

    if vegetation_only and "type" in out.columns:
        # 0 = presumed vegetation fire, 1 = active volcano,
        # 2 = other static land source, 3 = offshore
        out = out[out["type"] == 0]

    if verbose:
        after = len(out)
        pct = after / before * 100 if before else 0
        print(f"Before filtering: {before} -> after: {after} ({pct:.1f}% retained)")

    return out

def plot_hotspots(df,title="Hotspot map",out_path=None):
    import matplotlib.pyplot as plt
    from matplotlib.colors import LogNorm

    frp = df["frp"].clip(lower=0.01)
    vmin, vmax = frp.min(), frp.max()
    norm = LogNorm(vmin=vmin, vmax=vmax) if vmin < vmax else None

    fig, ax = plt.subplots(figsize=(8, 8))
    scatter = ax.scatter(
        df["longitude"], df["latitude"],
        c=frp, s=18, cmap="inferno", alpha=0.9,
        edgecolors="white", linewidths=0.4, norm=norm,
    )
    fig.colorbar(scatter, ax=ax, label="FRP (MW, log scale)")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    ax.set_aspect("equal", adjustable="datalim")

    if out_path:
        fig.savefig(out_path, dpi=120, bbox_inches="tight")
        print(f"Saved figure: {out_path}")

    return fig, ax