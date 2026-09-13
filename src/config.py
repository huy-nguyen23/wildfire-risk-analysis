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

for folder in (DATA_DIR,RAW_DIR,PROCESSED_DIR,FIGURES_DIR):
    folder.mkdir(parents=True,exist_ok=True)
    
FIRMS_BASE="https://firms.modaps.eosdis.nasa.gov/"

STUDY_START="2020-01-01"
STUDY_END="2025-12-31"

MAX_DAY_RANGE=5 # the area and country endpoints accept at most 5 days per request

DEFAULT_SOURCE="VIIRS_SNPP_SP"
COMPARE_SOURCE="MODIS_SP"

SEA_BBOX = "92,-11,141,29"          # all of Southeast Asia
BBOX_CHIANG_MAI = "98,17,100,20"    # northern Thailand 
BBOX_TAY_NGUYEN = "107,11,109,14"   # Central Highlands, Vietnam

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