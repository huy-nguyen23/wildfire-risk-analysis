import csv
import logging
import math
import time
import pandas as pd
from datetime import date,datetime,timedelta
from pathlib import Path

from config import LOG_DIR,MANIFEST_PATH,RAW_SUBDIRS,RETRY_BASE_DELAY_S,RETRY_MAX_ATTEMPTS,TRANSACTION_LIMIT,COUNTRY_BBOX_APPROX

log=logging.getLogger(__name__)

def setup_logging(level="INFO",log_dir=LOG_DIR,quiet_console=False):
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"download_{datetime.now():%Y%m%d}.log"

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))

    # Remove old handlers, otherwise running this twice prints every line twice
    logger.handlers.clear()

    line_format = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                                    datefmt="%H:%M:%S")

    to_file = logging.FileHandler(log_file, encoding="utf-8")
    to_file.setFormatter(line_format)
    logger.addHandler(to_file)

    if not quiet_console:
        to_screen = logging.StreamHandler()
        to_screen.setFormatter(line_format)
        logger.addHandler(to_screen)

    return log_file

def call_with_retry(function,arguments,max_attempts=RETRY_MAX_ATTEMPTS,base_delay=RETRY_BASE_DELAY_S):
    wait = base_delay

    for attempt in range(1, max_attempts + 1):
        try:
            return function(**arguments)

        except (ValueError, KeyboardInterrupt):
            raise   # my mistake, or I pressed Ctrl+C: stop now

        except Exception as error:
            if attempt == max_attempts:
                log.error("%s failed after %d attempts: %s",
                          function.__name__, max_attempts, error)
                raise
            log.warning("%s failed (attempt %d/%d): %s - retrying in %.0fs",
                        function.__name__, attempt, max_attempts, error, wait)
            time.sleep(wait)
            wait = wait * 2

def parse_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()

def split_into_chunks(start,end,chunk_days):
    start = parse_date(start)
    end = parse_date(end)
    if start > end:
        raise ValueError(f"start {start} is after end {end}")

    chunks = []
    current = start
    while current <= end:
        days_left = (end - current).days + 1
        days = min(chunk_days, days_left)
        chunks.append((current, days))
        current = current + timedelta(days=days)

    return chunks

def parse_bbox(text):
    """Turn "98,17,100,20" into four numbers (west, south, east, north)."""
    parts = str(text).split(",")
    return float(parts[0]), float(parts[1]), float(parts[2]), float(parts[3])

def bbox_for_countries(countries):
    if len(countries) == 0:
        raise ValueError("countries is empty")

    west, south, east, north = 180, 90, -180, -90
    for code in countries:
        if code not in COUNTRY_BBOX_APPROX:
            raise ValueError(f"No box for country {code!r}. Known: {sorted(COUNTRY_BBOX_APPROX)}")
        box = COUNTRY_BBOX_APPROX[code]
        west = min(west, box[0])
        south = min(south, box[1])
        east = max(east, box[2])
        north = max(north, box[3])

    return f"{west},{south},{east},{north}"

def count_days(start, end):
    return (parse_date(end) - parse_date(start)).days + 1

def estimate_firms(countries,start,end,chunk_days=5):
    days = count_days(start, end)
    requests = math.ceil(days / chunk_days)
    transactions = days
    minutes = transactions / TRANSACTION_LIMIT * 10

    return {
        "source": "FIRMS",
        "requests": requests,
        "transactions": transactions,
        "estimated_gb": round(requests * 0.05 / 1000, 4),   # the CSV files are tiny
        "estimated_minutes": round(minutes, 1),
        "note": f"1 box around {len(countries)} countries x {days} days, {chunk_days} days per request",
    }
    
def estimate_era5(bboxes,start,end,n_variables=5,grid_deg=0.1,minutes_per_request=30):
    days = count_days(start, end)
    hours = days * 24

    total_points = 0
    for bbox in bboxes:
        west, south, east, north = (float(x) for x in str(bbox).split(","))
        cols = (east - west) / grid_deg
        rows = (north - south) / grid_deg
        total_points += cols * rows

    values = total_points * hours * n_variables
    gb = values * 4 / 1e9  # float32

    # One request per month per box keeps individual downloads manageable.
    months = max(1, round(days / 30))
    requests = months * len(bboxes)

    return {
        "source": "ERA5-Land",
        "requests": requests,
        "transactions": requests,
        "estimated_gb": round(gb, 2),
        "estimated_minutes": round(requests * minutes_per_request, 1),
        "note": f"{total_points:,.0f} grid points x {hours:,} hours x {n_variables} variables",
    }
    
def estimate_worldcover(bboxes,tile_size_deg=3,mb_per_tile=44):
    import worldcover_api

    tiles = set()   # a set ignores tiles I already counted
    for bbox in bboxes:
        west, south, east, north = parse_bbox(bbox)
        for tile in worldcover_api.tiles_for_bbox(west, south, east, north, tile_size_deg):
            tiles.add(tile)

    return {
        "source": "WorldCover",
        "requests": len(tiles),
        "transactions": len(tiles),
        "estimated_gb": round(len(tiles) * mb_per_tile / 1000, 3),
        "estimated_minutes": round(len(tiles) * 0.5, 1),
        "note": f"{len(tiles)} distinct tiles (windowed reads fetch far less)",
    }

def estimate_all(countries,bboxes,start,end,verbose=True):
    import pandas as pd

    rows = [
        estimate_firms(countries, start, end),
        estimate_era5(bboxes, start, end),
        estimate_worldcover(bboxes),
    ]
    df = pd.DataFrame(rows)

    total = {
        "source": "TOTAL",
        "requests": df["requests"].sum(),
        "transactions": df["transactions"].sum(),
        "estimated_gb": round(df["estimated_gb"].sum(), 2),
        "estimated_minutes": round(df["estimated_minutes"].sum(), 1),
        "note": "",
    }
    df = pd.concat([df, pd.DataFrame([total])], ignore_index=True)

    if verbose:
        print(df.to_string(index=False))
        hours = total["estimated_minutes"] / 60
        print()
        print(f"Estimated wall clock: {hours:,.1f} hours "
              f"({hours/24:,.1f} days)")
        print(f"Estimated disk      : {total['estimated_gb']:,.1f} GB")

    return df

MANIFEST_COLUMNS = ["timestamp", "source", "key", "path", "status", "size_bytes", "message"]

def create_manifest(manifest_path=MANIFEST_PATH):
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if not manifest_path.exists():
        with open(manifest_path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(MANIFEST_COLUMNS)
            
def  record_download(source,key,path=None,status="OK",message="",manifest_path=MANIFEST_PATH):
    create_manifest(manifest_path)

    size = 0
    if path is not None and Path(path).exists():
        size = Path(path).stat().st_size

    if path is None:
        path_text = ""
    else:
        path_text = str(path)

    with open(manifest_path, "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            datetime.now().isoformat(timespec="seconds"),
            source, key, path_text, status, size, message,
        ])
        
def read_manifest(manifest_path=MANIFEST_PATH):
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return pd.DataFrame(columns=MANIFEST_COLUMNS)
    return pd.read_csv(manifest_path)

def is_downloaded(source,key,manifest_path=MANIFEST_PATH):
    table = read_manifest(manifest_path)
    if len(table) == 0:
        return False

    same_item = (table["source"] == source) & (table["key"] == key)
    succeeded = table["status"] == "ok"
    matches = table[same_item & succeeded]
    if len(matches) == 0:
        return False

    saved_path = matches.iloc[-1]["path"]
    if pd.isna(saved_path) or saved_path == "":
        return False

    return Path(saved_path).exists()

def manifest_summary(manifest_path=MANIFEST_PATH):
    table = read_manifest(manifest_path)
    if len(table) == 0:
        return table

    counts = table.groupby(["source", "status"]).size()
    return counts.rename("count").reset_index()

def raw_path(source,year,filename):
    if source not in RAW_SUBDIRS:
        raise ValueError(f"Unknown source {source!r}. Expected one of {list(RAW_SUBDIRS)}")

    folder = RAW_SUBDIRS[source] / str(year)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / filename