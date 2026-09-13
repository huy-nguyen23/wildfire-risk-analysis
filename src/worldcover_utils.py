import  numpy as np
import pandas as pd
from matplotlib.colors import BoundaryNorm,ListedColormap
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import math
import worldcover_api as wc
from config import DEFAULT_YEAR,LAND_COVER_CLASSES

def _categorical_cmap_norm():
    codes=sorted(LAND_COVER_CLASSES.keys())
    colors=[LAND_COVER_CLASSES[c][1] for c in codes]
    cmap=ListedColormap(colors)
    
    mids=[(codes[i]+codes[i+1])/2 for i in range(len(codes)-1)]
    first_gap=codes[1]-codes[0]
    last_gap=codes[-1]-codes[-2]
    boundaries=[codes[0]-first_gap/2]+mids+[codes[-1]+last_gap/2]
    
    norm=BoundaryNorm(boundaries,cmap.N)
    return cmap,norm,codes,colors

def plot_landcover(data, title="Land cover", out_path=None):
    """Plot a WorldCover class-code array with the standard categorical legend.

    Args:
        data: 2D numpy array of class codes (e.g. from download_worldcover()).
        title: plot title.
        out_path: optional path to save a PNG.

    Returns:
        (figure, axes) tuple from matplotlib.
    """
    cmap, norm, codes, colors = _categorical_cmap_norm()

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(data, cmap=cmap, norm=norm, interpolation="nearest")
    ax.set_title(title)
    ax.set_xlabel("column (pixel)")
    ax.set_ylabel("row (pixel)")

    present = set(np.unique(data).tolist())
    handles = [
        mpatches.Patch(color=LAND_COVER_CLASSES[c][1], label=LAND_COVER_CLASSES[c][0])
        for c in codes
        if c in present
    ]
    ax.legend(handles=handles, bbox_to_anchor=(1.02, 1), loc="upper left",
              fontsize=9, frameon=False)

    if out_path:
        fig.savefig(out_path, dpi=120, bbox_inches="tight")
        print(f"Saved figure: {out_path}")

    return fig, ax

def sample_landcover(lat,lon,year=None):
    if year is None:
        year=DEFAULT_YEAR
    
    tile_name = wc._tile_name(
        math.floor(lat / 3) * 3,
        math.floor(lon / 3) * 3,
    )
    try:
        with wc.open_tile(tile_name, year) as src:
            value = next(src.sample([(lon, lat)]))[0]
    except Exception as err:
        print(f"[ERROR] Could not sample ({lat}, {lon}): {err}")
        return None

    code = int(value)
    name, color = LAND_COVER_CLASSES.get(code, (f"Unknown code {code}", "#000000"))
    return {"code": code, "class_name": name, "color": color}

def landcover_stats(data):
    """Compute the percentage of each land-cover class in a raster array.

    Args:
        data: 2D numpy array of class codes.

    Returns:
        DataFrame with columns code, class, pixels, percent - sorted by
        percent descending. Codes not in LAND_COVER_CLASSES (unexpected
        values) are still reported, labelled 'Unknown (<code>)', rather than
        silently dropped.
    """
    values, counts = np.unique(data, return_counts=True)
    total = int(counts.sum())

    rows = []
    for v, c in zip(values, counts):
        code = int(v)
        name, _color = LAND_COVER_CLASSES.get(code, (f"Unknown ({code})", "#000000"))
        rows.append({
            "code": code,
            "class": name,
            "pixels": int(c),
            "percent": round(c / total * 100, 2),
        })

    df = pd.DataFrame(rows).sort_values("percent", ascending=False).reset_index(drop=True)
    return df