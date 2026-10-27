# Data dictionary

This document distinguishes the original NASA FIRMS fields, the cleaned
detection table produced by `src/firms_cleaning.py`, and the planned
grid-cell/day dataset in `src/schema.py`. The latter is a design, not a
completed integrated dataset.

## FIRMS input fields

| Field | Meaning | Unit / values | Interpretation |
|---|---|---|---|
| `latitude`, `longitude` | Center of the detected thermal-anomaly pixel | Degrees, EPSG:4326 | Not an exact fire location |
| `acq_date`, `acq_time` | Acquisition date and time | UTC; `YYYY-MM-DD` and `HHMM` | CSV parsing can remove leading zeros: `1` means 00:01 |
| `satellite`, `instrument` | Platform and sensor | e.g. `N`/`VIIRS`, `Terra`/`MODIS` | Retained for provenance and deduplication |
| `confidence` | Detection confidence class or value | VIIRS `l/n/h`; MODIS 0–100 | The two scales are not directly comparable probabilities |
| `type` | Heat-source category in Standard Processing data | 0, 1, 2, 3 | Only `0` (presumed vegetation fire) is retained |
| `frp` | Fire Radiative Power | MW | Radiative power of a detection, not the number of fires |
| `scan`, `track` | Approximate pixel dimensions | km | Pixel footprint varies with viewing geometry |
| `bright_ti4`, `bright_ti5` | VIIRS brightness temperatures | K | Thermal channels, not air temperature |
| `brightness`, `bright_t31` | MODIS brightness temperatures | K | Thermal channels, not air temperature |
| `daynight` | Observation period | `D` or `N` | Satellite observation context |
| `version` | FIRMS product version | Source-specific | Used for provenance |

See [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) for the source data
and sensor-specific field definitions.

## Cleaned detection table

The cleaning workflow preserves one row per retained detection and writes a
matching `.qa.json` report. It does not modify the raw CSV.

| Field | Type / values | Derivation |
|---|---|---|
| `source_dataset` | String | Source passed to `run_firms_cleaning()`, e.g. `VIIRS_SNPP_SP` |
| `satellite`, `instrument` | Strings | Source fields; instrument must match the selected source |
| `latitude`, `longitude` | Decimal degrees | Valid numeric coordinates |
| `acq_datetime_utc` | UTC timestamp | Strictly parsed `acq_date` + zero-padded `acq_time` |
| `date`, `year`, `month` | UTC calendar components | Derived from `acq_datetime_utc` |
| `country` | ISO-3 code or empty | Assigned only when exactly one country polygon covers the point |
| `country_match_status` | `matched`, `unmatched`, `ambiguous` | Result of point-in-polygon assignment |
| `confidence_raw` | String | Original source confidence value |
| `confidence_level` | `nominal` or `high` in retained rows | VIIRS: `n/h`; MODIS: `30–<80/≥80` |
| `frp_mw` | MW, non-negative | Numeric `frp` from the source |
| `daynight`, `type` | `D/N`; `0` | Observation period and retained vegetation-fire category |

The MODIS classification follows the [MODIS Collection 6 Fire User Guide](https://www.earthdata.nasa.gov/s3fs-public/imported/MODIS_C6_Fire_User_Guide_A.pdf):
`<30` is low, `30–<80` is nominal and `≥80` is high. VIIRS uses the
[FIRMS `l/n/h` classes](https://firms.modaps.eosdis.nasa.gov/content/descriptions/FIRMS_VIIRS_Firehotspots.html).
These labels are **within-sensor categories**, not a calibrated common
probability scale.

Country assignment uses the bundled
[Natural Earth Admin-0 1:10m](https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/)
subset. The boundaries are a *de facto* cartographic representation, not a
legal determination of sovereignty or borders. Unmatched and ambiguous
detections remain in the output with no guessed country.

## Planned grid-cell/day table

`src/schema.py` defines 23 fields with primary key `grid_id + date`, combining
location, a `fire` label, FIRMS summary fields, ERA5-Land weather and ESA
WorldCover land cover. No such integrated table is produced by the current
pipeline. In particular, `fire=0` example