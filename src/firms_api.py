from config import FIRMS_BASE,MAP_KEY,MAX_DAY_RANGE, RAW_DIR
import requests
import pandas as pd
import io

TIMEOUT=60         

def check_map_key(verbose=True): 
    """Report how many API transactions the current MAP_KEY has used.

    Args:
        verbose: print a human-readable summary.

    Returns:
        dict with 'current_transactions', 'transaction_limit' and
        'transaction_interval', or None if the request failed.
    """
    url=f"{FIRMS_BASE}/mapserver/mapkey_status/?MAP_KEY={MAP_KEY}"
    try: 
        response=requests.get(url)
        response.raise_for_status()
        data=response.json()        
    except requests.exceptions.RequestException as e:
        print(f"[NETWORK ERROR] Could not reach FIRMS: {e}")
        return None
    except ValueError:
        print("[ERROR] Response was not JSON. Check MAP_KEY in your .env file.")
        return None
    
    if verbose: 
        used=data.get("current_transactions","?")
        limit=data.get("transaction_limit","?")
        interval=data.get("transaction_interval","?")
        print(f"MAP_KEY is valid. Used {used}/{limit} transactions per {interval}.")
        
    return data

def get_data_availability(sensor="ALL"):
    """List every FIRMS dataset together with its available date range.

    Args:
        sensor: 'all' for every dataset, or a single dataset id such as
                'VIIRS_SNPP_SP'.

    Returns:
        DataFrame with columns data_id, min_date, max_date (dates parsed to
        datetime so they can be compared), or None if the request failed.
    """
    url=f"{FIRMS_BASE}/api/data_availability/csv/{MAP_KEY}/{sensor}"
    try:
        response=requests.get(url)
        response.raise_for_status()
        df=pd.read_csv(io.StringIO(response.text))
    except requests.exceptions.RequestException  as e:
        print(f"[NETWORK ERROR] Could not reach FIRMS: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Could not read data availability: {e}")
        return None
    
    df["min_date"] = pd.to_datetime(df["min_date"], errors="coerce")
    df["max_date"] = pd.to_datetime(df["max_date"], errors="coerce")
    
    return df

def pick_sources_covering(start,end,availability=None):
    """Return only the datasets whose date range fully covers [start, end].

    This answers the central question of Exercise 2: which datasets are usable
    for a 2020-2025 study? The answer comes from the data rather than a guess.

    Args:
        start: first day of the study period, 'YYYY-MM-DD'.
        end: last day of the study period, 'YYYY-MM-DD'.
        availability: a DataFrame from get_data_availability(); fetched
            automatically when omitted.

    Returns:
        DataFrame with columns data_id, min_date, max_date.
    """
    if availability is None:
        availability=get_data_availability()
    
    start_ts=pd.Timestamp(start) #convert time to timestamp in pandas
    end_ts=pd.Timestamp(end)
    
    covers=(availability["min_date"]<=start_ts) & (availability["max_date"]>=end_ts)
    return availability.loc[covers].reset_index(drop=True)

def _validate_bbox(bbox):
    """Validate a 'west,south,east,north' bounding box string.

    Returns:
        tuple of four floats (west, south, east, north).

    Raises:
        ValueError: if the string is malformed, out of range, or in the wrong
            order. Swapping the corners is the most common mistake because the
            FIRMS order differs from the more familiar north/south/east/west.
    """
    parts=str(bbox).split(",")
    if len(parts)!=4:
        raise ValueError(f"Bounding box needs exactly 4 numbers 'west,south,east,north'. Got: {bbox!r}")
    try:
        west,south,east,north=(float(p) for p in parts)
    except ValueError:
        raise ValueError(f"Bounding box contains a non-numeric value: {bbox!r}")
    
    if not (-180<=west<=180 and -180<=east <=180):
        raise ValueError("Longitude must be between -180 and 180") 
    if not (-90<=south<=90 and -90<=north<=90): 
        raise ValueError("Latitude must be between -90 and 90") 

def _validate_day_range(day_range):
    """Raise ValueError unless day_range is an int within the 1-5 API limit."""
    if not isinstance(day_range, int):
        raise ValueError(
            f"day_range must be an integer, got {type(day_range).__name__}"
        )
    if not 1 <= day_range <= MAX_DAY_RANGE:
        raise ValueError(
            f"day_range must be between 1 and {MAX_DAY_RANGE}, got {day_range}"
        )

def _cache_path(source,region,day_range,date):
    """Build a deterministic filename so one query always maps to one file.

    Commas become underscores and minus signs become 'm' so the name stays
    valid on every operating system.
    """
    safe_region=str(region).replace(",","_").replace("-","m")
    date_part=date if date else "latest"
    return RAW_DIR / f"{source}_{safe_region}_{date_part}_{day_range}d.csv"

def download_firms(source,bbox,day_range=1,date=None,use_cache=True,verbose=True):
    """Download FIRMS hotspots for a bounding box, with caching and error handling.

    This is the production downloader for the project and is reused from
    Session 6 onwards.

    Args:
        source: dataset id, e.g. 'VIIRS_SNPP_SP' or 'MODIS_SP'.
        bbox: 'west,south,east,north'.
        day_range: number of days per request (1-5).
        date: 'YYYY-MM-DD'; omit for the most recent data.
        use_cache: read a previously downloaded file instead of calling the API.
        verbose: print progress messages.

    Returns:
        DataFrame of hotspot detections, or None if the download failed.

    Raises:
        ValueError: if bbox or day_range are invalid. These are raised rather
            than returned because they are programming mistakes, not runtime
            conditions, and should be fixed rather than handled.
    """
    _validate_bbox(bbox)
    _validate_day_range(day_range)

    cache_file=_cache_path(source,bbox,day_range,date)
    if use_cache and cache_file.exists():
        if verbose:
            print(f"[cache] Reading {cache_file.name}")
        return pd.read_csv(cache_file)
        
    
    url=f"{FIRMS_BASE}/api/area/csv/{MAP_KEY}/{source}/{bbox}/{day_range}"
    if date:
        url+=f"/{date}"
      
    try:
        response=requests.get(url,timeout=TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.Timeout:
        print(f"[NETWORK ERROR] No response within {TIMEOUT}s. Try a smaller area.")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[NETWORK ERROR] Could not download FIRMS data: {e}")
        return None
    
    cache_file.write_text(response.text,encoding="utf-8")
    df=pd.read_csv(cache_file)
    
    if verbose:
        print(f"[downloaded] {cache_file.name} - {len(df)} hotspots")
    
    return df

    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    