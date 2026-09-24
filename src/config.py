import os 
from dotenv import load_dotenv

from pathlib import Path

BASE_DIR=Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR/".env") # read file .env
MAP_KEY=os.getenv("MAP_KEY")
CDSAPI_URL=os.getenv("CDSAPI_URL")
CDSAPI_KEY=os.getenv("CDSAPI_KEY")


if not MAP_KEY:
    raise RuntimeError("FIRMS MAP KEY NOT FOUND.")

DATA_DIR=BASE_DIR / "data"
RAW_DIR=DATA_DIR / "raw"
PROCESSED_DIR=DATA_DIR/ "processed"
FIGURES_DIR=BASE_DIR / "figures" 

DOCS_DIR = BASE_DIR / "docs"
REFERENCE_DIR = DATA_DIR / "reference"
COUNTRY_BOUNDARIES_PATH = REFERENCE_DIR / "sea_countries_10m.geojson"

RAW_SUBDIRS = {
    "firms": RAW_DIR / "firms",
    "era5": RAW_DIR / "era5",
    "worldcover": RAW_DIR / "worldcover",
}
MANIFEST_PATH = RAW_DIR / "manifest.csv"

RETRY_MAX_ATTEMPTS = 3
RETRY_BASE_DELAY_S = 1.0

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

for folder in (DATA_DIR,RAW_DIR,PROCESSED_DIR,FIGURES_DIR,REFERENCE_DIR):
    folder.mkdir(parents=True,exist_ok=True)
    
FIRMS_BASE="https://firms.modaps.eosdis.nasa.gov"

TRANSACTION_LIMIT=5000

STUDY_START="2020-01-01"
STUDY_END="2025-12-31"

MAX_DAY_RANGE=5 # the area and country endpoints accept at most 5 days per request

DEFAULT_SOURCE="VIIRS_SNPP_SP"
COMPARE_SOURCE="MODIS_SP"

SEA_BBOX = "92,-11,141,29"          # all of Southeast Asia
BBOX_CHIANG_MAI = "98,17,100,20"    # northern Thailand 
BBOX_TAY_NGUYEN = "107,11,109,14"   # Central Highlands, Vietnam

SEA_COUNTRIES = {
    "BRN": "Brunei",
    "KHM": "Cambodia",
    "IDN": "Indonesia",
    "LAO": "Laos",
    "MYS": "Malaysia",
    "MMR": "Myanmar",
    "PHL": "Philippines",
    "SGP": "Singapore",
    "THA": "Thailand",
    "TLS": "Timor-Leste",
    "VNM": "Vietnam",
}

LOCAL_TZ_OFFSET_HOURS=7

ERA5_DATASET="reanalysis-era5-land"

ERA5_VARIABLES = {
    "2m_temperature": "t2m",
    "total_precipitation": "tp",
    "volumetric_soil_water_layer_1": "swvl1",
    "10m_u_component_of_wind": "u10",
    "10m_v_component_of_wind": "v10",
}

BBOX_CHIANG_MAI_CDS = [20, 98, 17, 100]
BBOX_TAY_NGUYEN_CDS = [14, 107, 11, 109]

ALL_HOURS = [f"{h:02d}:00" for h in range(24)]

ACCUMULATION_RESET_HOUR_UTC=0

# WORLDCOVER DATA
WORLDCOVER_URL="https://esa-worldcover.s3.eu-central-1.amazonaws.com"

TILE_SIZE=3

DEFAULT_YEAR=2021
WORLDCOVER_VERSION={2020:"v100",2021:"v200"}

LAND_COVER_CLASSES = {
    10: ("Tree cover", "#006400"),
    20: ("Shrubland", "#ffbb22"),
    30: ("Grassland", "#ffff4c"),
    40: ("Cropland", "#f096ff"),
    50: ("Built-up", "#fa0000"),
    60: ("Bare / sparse vegetation", "#b4b4b4"),
    70: ("Snow and ice", "#f0f0f0"),
    80: ("Permanent water bodies", "#0064c8"),
    90: ("Herbaceous wetland", "#0096a0"),
    95: ("Mangroves", "#00cf75"),
    100: ("Moss and lichen", "#fae6a0"),
}

# Study scope
STUDY_COUNTRIES = ["THA", "VNM", "LAO", "KHM", "MMR"]

STUDY_REGIONS = {
    "chiang_mai": BBOX_CHIANG_MAI,
    "tay_nguyen": BBOX_TAY_NGUYEN,
}

COUNTRY_BBOX_APPROX = {
    "MMR": (92.2, 9.8, 101.2, 28.5),    # Myanmar
    "THA": (97.3, 5.6, 105.6, 20.5),    # Thailand
    "LAO": (100.1, 13.9, 107.7, 22.5),  # Laos
    "VNM": (102.1, 8.2, 109.5, 23.4),   # Vietnam
    "KHM": (102.3, 10.4, 107.6, 14.7),  # Cambodia
    "MYS": (99.6, 0.8, 119.3, 7.4),     # Malaysia
    "SGP": (103.6, 1.2, 104.1, 1.5),    # Singapore
    "BRN": (114.0, 4.0, 115.4, 5.1),    # Brunei
    "IDN": (95.0, -11.0, 141.0, 6.1),   # Indonesia
    "PHL": (116.9, 4.6, 126.6, 21.1),   # Philippines
    "TLS": (124.0, -9.5, 127.3, -8.1),  # Timor-Leste
}

# Clean data
FIRMS_DUPLICATE_KEY = [
    "latitude", "longitude", "acq_datetime_utc", "satellite", "instrument",
]

MODIS_CONFIDENCE_BINS = {"low": (0, 30), "nominal": (30, 80), "high": (80, 101)}
VIIRS_CONFIDENCE_MAP = {"l": "low", "n": "nominal", "h": "high"}

DRY_DAY_THRESHOLD_MM = 1.0

RAINFALL_WINDOW_DAYS = 7