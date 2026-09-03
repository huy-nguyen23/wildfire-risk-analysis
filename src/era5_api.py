from config import CDSAPI_KEY,CDSAPI_URL,RAW_DIR,ERA5_DATASET,ERA5_VARIABLES,ALL_HOURS
import datetime as dt
import xarray as xr

_cdsapi=None

def _get_client():
    global _cdsapi
    if _cdsapi is None:
        import cdsapi as _cdsapi_module
        _cdsapi = _cdsapi_module

    if not CDSAPI_KEY:
        raise RuntimeError(
            "CDSAPI_KEY not found.\n"
            "  1. Log in at https://cds.climate.copernicus.eu/profile\n"
            "  2. Copy your Personal Access Token\n"
            "  3. Add CDSAPI_KEY=<token> to your .env file"
        )

    return _cdsapi.Client(url=CDSAPI_URL, key=CDSAPI_KEY, quiet=True)

def _diagnose_cds_error(err):
    msg = str(err).lower()

    if "required licences not accepted" in msg or "required licenses not accepted" in msg:
        return (
            "[LICENCE ERROR] The dataset's Terms of Use have not been accepted.\n"
            "  Visit https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land"
            "?tab=download, scroll to the bottom, and accept the licence there.\n"
            "  Accepting it on the /profile page is NOT the same step."
        )
    if "401" in msg or "credentials" in msg or "unauthorized" in msg:
        return "[AUTH ERROR] CDSAPI_KEY appears to be invalid. Re-check the token in .env."
    if "403" in msg:
        return f"[PERMISSION ERROR] Request was refused: {err}"
    return f"[ERROR] CDS request failed: {err}"

def check_cds_connection(verbose=True):
    try:
        client=_get_client()
    except RuntimeError as e:
        if verbose:
            print(f"[CONFIG ERROR] {e}")
        return False

    request = {
        "variable": ["2m_temperature"],
        "year": ["2024"],
        "month": ["01"],
        "day": ["01"],
        "time": ["00:00"],
        "area": [1, 100, 0, 101],  # tiny 1x1 degree box: North,West,South,East
        "data_format": "netcdf",
        "download_format": "unarchived",
    }
    
    tmp_target = RAW_DIR / "_connection_test.nc"

    try:
        client.retrieve(ERA5_DATASET, request, str(tmp_target))
    except Exception as err:
        if verbose:
            print(_diagnose_cds_error(err))
        return False

    if verbose:
        print("CDS connection OK: token is valid and the ERA5-Land licence is accepted.")

    tmp_target.unlink(missing_ok=True)
    return True    

def _validate_variables(variables):
    if isinstance(variables, str):
        variables = [variables]

    unknown = [v for v in variables if v not in ERA5_VARIABLES]
    if unknown:
        raise ValueError(
            f"Unknown variable(s): {unknown}. "
            f"Known variables: {list(ERA5_VARIABLES)}"
        )
    return list(variables)

def _validate_date(year, month, day):
    try:
        date = dt.date(int(year), int(month), int(day))
    except ValueError as err:
        raise ValueError(f"Not a real calendar date: {year}-{month}-{day} ({err})")

    if date < dt.date(1950, 1, 1):
        raise ValueError("ERA5-Land starts in January 1950")

    return date

def _validate_area(area):
    if len(area) != 4:
        raise ValueError(f"area needs exactly 4 numbers [North, West, South, East]. Got: {area!r}")

    north, west, south, east = (float(x) for x in area)

    if not (-90 <= north <= 90 and -90 <= south <= 90):
        raise ValueError("Latitude (North/South) must be between -90 and 90")
    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError("Longitude (West/East) must be between -180 and 180")
    if north <= south:
        raise ValueError("Wrong order: North must be GREATER THAN South [North,West,South,East]")
    if east <= west:
        raise ValueError("Wrong order: East must be GREATER THAN West [North,West,South,East]")

    return north, west, south, east
    
def _cache_path(variables, area, year, month, day):
    """Build a deterministic filename so one query always maps to one file."""
    var_part = "_".join(sorted(variables))
    area_part = "_".join(str(round(x, 2)) for x in area).replace(".", "p").replace("-", "m")
    return RAW_DIR / f"era5land_{var_part}_{area_part}_{year}{month:02d}{day:02d}.nc"



def download_era5(variables,area,year,month,day,hours=None,use_cache=True,verbose=True):
    variables=_validate_variables(variables)
    _validate_area(area)
    _validate_date(year,month,day)
    hours=hours or ALL_HOURS
    
    cache_file = _cache_path(variables, area, year, month, day)
    if use_cache and cache_file.exists():
        if verbose:
            print(f"[cache] Reading {cache_file.name}")
        return xr.open_dataset(cache_file)

    try:
        client = _get_client()
    except RuntimeError as err:
        print(f"[CONFIG ERROR] {err}")
        return None

    request = {
        "variable": variables,
        "year": [str(year)],
        "month": [f"{month:02d}"],
        "day": [f"{day:02d}"],
        "time": hours,
        "area": list(area),
        "data_format": "netcdf",
        "download_format": "unarchived",
    }

    if verbose:
        print(f"Submitting request to CDS - this can take from under a minute "
              f"to a few hours depending on server load ...")

    try:
        client.retrieve(ERA5_DATASET, request, str(cache_file))
    except Exception as err:
        print(_diagnose_cds_error(err))
        return None

    if verbose:
        print(f"[downloaded] {cache_file.name}")

    return xr.open_dataset(cache_file)