# Data Dictionary

**Project:** Wildfire Risk Analysis in Southeast Asia Using Multi-Source Earth Observation Data
**Study area:** the 5 countries of mainland Southeast Asia (Thailand, Vietnam, Laos, Cambodia, Myanmar)
**Study period:** 2020-2025

This document describes three things:

- **Part 1** - the raw fields as they arrive from each of the three data sources.
- **Part 2** - the single analysis table those three sources are merged into.
- **Part 3** - the training sample drawn from that table, and the files the pipeline writes.

---

# PART 1 - RAW SOURCE FIELDS

## 1.1 NASA FIRMS - active fire detections

**Datasets used:** `VIIRS_SNPP_SP` (primary) and `MODIS_SP` (cross-check)

**How the data is requested:** through the FIRMS **Area** endpoint, with one bounding box around all study countries. FIRMS used to offer a **Country** endpoint, but it is no longer available (its documentation page returns an error, and the current FIRMS service list only has Area, KML Fire Footprints, Data Availability and Missing Data). Because a rectangle also catches neighbouring countries and the sea, the country of every hotspot is decided later from real borders (Natural Earth 1:50m, point-in-polygon), and only hotspots inside the study countries are kept.

Only **vegetation fires** are kept: FIRMS `type` 0. Static land heat sources (type 2: cement plants, kilns, flares) and offshore detections (type 3) burn all year, mostly at night, and would make an industrial town look like a wildfire hotspot.

Standard Processing (`_SP`) products are used rather than Near Real-Time (`_NRT`) because only `_SP` covers the full 2020-2025 study period; `_NRT` archives retain only the most recent months.

| Field | Meaning | Unit / Type | Must remember |
|---|---|---|---|
| `latitude` | Latitude of the detected pixel centre | degrees (float) | **Not the centre of the flame** - positional error reaches several hundred metres |
| `longitude` | Longitude of the detected pixel centre | degrees (float) | Same caveat as above |
| `brightness` *(MODIS)* | Brightness temperature, ~4 µm channel | Kelvin | Not air temperature |
| `bright_ti4` *(VIIRS)* | Brightness temperature, ~4 µm channel | Kelvin | VIIRS equivalent of MODIS `brightness` |
| `bright_t31` *(MODIS)* | Brightness temperature, ~11 µm channel (background) | Kelvin | Compared against the 4 µm channel |
| `bright_ti5` *(VIIRS)* | Brightness temperature, ~11 µm channel (background) | Kelvin | VIIRS equivalent of `bright_t31` |
| `scan` | Pixel footprint along the scan direction | km | Pixels near the swath edge are **much larger** than at nadir |
| `track` | Pixel footprint along the track direction | km | `scan × track` ≈ pixel area |
| `acq_date` | Acquisition date | `YYYY-MM-DD` | **UTC/GMT** |
| `acq_time` | Acquisition time | integer `HHMM` | **UTC, leading zeros stripped** (`1` = 00:01, `633` = 06:33) |
| `satellite` | Observing satellite | string | `Terra`/`Aqua` (MODIS) or `N`/`N20`/`N21` (VIIRS) |
| `instrument` | Sensor | string | `MODIS` or `VIIRS` |
| `confidence` | Detection confidence | **MODIS: 0-100 (numeric)**<br>**VIIRS: `l`/`n`/`h` (letters)** | The two scales are **not directly comparable** - normalised to `confidence_level` during cleaning |
| `version` | Algorithm version | string | Reveals whether the data is NRT or SP |
| `frp` | Fire Radiative Power | MW | Measures fire **intensity** - the most informative non-spatial field |
| `daynight` | Day or night overpass | `D` / `N` | |
| `type` *(SP only)* | Heat source class | 0/1/2/3 | `0` = vegetation fire, `1` = volcano, `2` = static land source, `3` = offshore → **used to filter noise** |

Measured values for these fields (ranges, missing values, confidence distribution, and a MODIS vs VIIRS comparison) are computed in `notebooks/01_firms_data_exploration.ipynb`.

VIIRS reports more detections than MODIS over the same area and date. This reflects its finer 375 m pixel (small fires fill more of the pixel and pass the detection threshold), i.e. higher **sensitivity**, not higher accuracy. Counts from the two sensors are therefore never pooled.

---

## 1.2 Copernicus ERA5-Land - weather reanalysis

**Dataset used:** `reanalysis-era5-land`, hourly, native resolution 0.1° (~11 km)

ERA5-Land is **reanalysis**, not direct measurement: a numerical weather model rerun over history and anchored to real observations through data assimilation. A value is therefore the model's estimate for a whole ~11 km grid cell, not a reading taken at a specific point inside it.

| Request name | Short name in file | Meaning | Native unit |
|---|---|---|---|
| `2m_temperature` | `t2m` | Air temperature at 2 m | Kelvin |
| `total_precipitation` | `tp` | Accumulated precipitation | **metres** (not mm) |
| `volumetric_soil_water_layer_1` | `swvl1` | Surface soil water (0-7 cm) | m³/m³ (0-1 ratio) |
| `10m_u_component_of_wind` | `u10` | East-west wind component | m/s |
| `10m_v_component_of_wind` | `v10` | North-south wind component | m/s |

**Three traps to remember:**

1. **Request names differ from names inside the file** - request `2m_temperature`, but the downloaded NetCDF exposes it as `t2m`. Always run `print(list(ds.data_vars))` before accessing a variable.
2. **Precipitation is accumulated, and resets at 00:00 UTC daily** - the value at any hour is the running total since that reset. Summing all 24 hourly values double-counts and overstates rainfall several times over. The value at 23:00 UTC *is* the daily total. The pipeline takes the **daily maximum** instead, which equals the 23:00 value but stays correct when an hourly row is missing.
3. **Wind is a vector, not a single number** - speed must be computed as `sqrt(u10² + v10²)` for **each hour first**, then averaged. Averaging `u10` and `v10` first lets opposite winds cancel out (12 h of 10 m/s east wind + 12 h of 10 m/s west wind would give 0 m/s).

Current downloads name the time dimension `valid_time` (older documentation says `time`), and carry scalar metadata coordinates `number` and `expver` that are not data axes.

---

## 1.3 ESA WorldCover - land cover

**Dataset used:** `v200` (2021), 10 m resolution, 11 classes

Accessed from a public AWS S3 bucket - no account, no API key, no licence acceptance. Tiles cover a fixed 3° × 3° grid and are named after their south-west corner (e.g. `N15E096` spans 15-18°N, 96-99°E).

| Code | Class | Standard colour |
|---|---|---|
| 10 | Tree cover | `#006400` |
| 20 | Shrubland | `#ffbb22` |
| 30 | Grassland | `#ffff4c` |
| 40 | Cropland | `#f096ff` |
| 50 | Built-up | `#fa0000` |
| 60 | Bare / sparse vegetation | `#b4b4b4` |
| 70 | Snow and ice | `#f0f0f0` |
| 80 | Permanent water bodies | `#0064c8` |
| 90 | Herbaceous wetland | `#0096a0` |
| 95 | Mangroves | `#00cf75` |
| 100 | Moss and lichen | `#fae6a0` |

**Two traps to remember:**

1. **An area of interest can straddle several tiles.** This project's Chiang Mai test box (`98,17,100,20`) - only 2° × 3° - needs **four** tiles: `N15E096`, `N15E099`, `N18E096`, `N18E099`. Reading only one tile silently truncates the map. Measured effect on this box: cropland reads as 3.8% from one tile but 11.4% from all four - a threefold underestimate of exactly the class where agricultural burning happens.
2. **v100 and v200 use different classification algorithms.** Differences between the two versions must not be interpreted as land cover having changed.

**Citation:** © ESA WorldCover project / Contains modified Copernicus Sentinel data (2021) processed by ESA WorldCover consortium. Licence CC-BY-4.0.

---

# PART 2 - THE FINAL ANALYSIS TABLE

> Designed **before** any bulk download. Designing first matters because discovering a schema mistake after downloading six years across several countries would mean re-downloading everything - and ERA5-Land requests queue for hours.

## 2.1 GRAIN - what does one row represent?

> **One row = ONE GRID CELL on ONE DAY.**

Not "one row = one hotspot detection". That alternative looks simpler but makes negative sampling impossible.

The classification model needs `fire = 0` records: cell-days where no hotspot occurred. Under a hotspot grain those records cannot exist - a fire that did **not** happen has no coordinate, no FRP, no detection to be a row at all. A grid cell on a given day always exists, so it carries `fire = 0` as easily as `fire = 1`.

The grain therefore determines whether negative sampling and model training are feasible at all. Data modelling is about looking ahead, not about serving today's need.

## 2.2 Spatial grid

The **ERA5-Land 0.1° grid** is used - the **coarsest** of the three sources.

Principle: always aggregate down to the coarsest source; never interpolate a coarse source finer than it really is. Computing "what percentage of this 11 km cell is forest" is legitimate; producing temperature at 10 m resolution when ERA5-Land only resolves 11 km would be fabricating data.

One grid cell at latitude 18°N:

| Metric | Value |
|---|---|
| Cell size | ~10.6 × 11.1 km (~118 km²) |
| WorldCover pixels contained (10 m) | **1,440,000** |
| VIIRS pixels contained (375 m) | ~838 |
| Weather values per day | 24 (hourly) |

## 2.3 Primary key

`(grid_id, date)` - must be **unique**. Verified by `schema.check_primary_key()`.

A duplicated key means the same cell-day was built twice, usually by a merge that fanned out, which quietly double-counts everything downstream.

`grid_id` names the cell centre, e.g. `'18.5_99.0'`, and is reversible via `schema.grid_id_to_latlon()`.

## 2.4 Aggregation rules

| Source | Native cadence | How it becomes daily |
|---|---|---|
| FIRMS | Instantaneous, UTC | Group the day's detections → count, take max and sum of FRP |
| ERA5-Land | 24 values/day | Temperature → **max** and **mean**; rainfall → **daily total**; wind → **mean** |
| WorldCover | No time dimension | Joined statically - the same value for every date | 

## 2.5 Unit and naming conventions

- Temperature: K → **°C** · Rainfall: m → **mm** · Wind: m/s → **km/h**
- Soil moisture stays as m³/m³ (already a 0-1 ratio, no conversion)
- Column names are `snake_case` with the **unit embedded in the name**: `temp_max_c`, `rainfall_mm`, `wind_speed_kmh`

Embedding the unit is a small habit with a large payoff: reading `rainfall_mm` tells you the unit without opening any documentation, and prevents repeating the "thought it was mm, actually metres" mistake that ERA5-Land invites.

## 2.6 Land cover grouping

The 11 WorldCover classes are collapsed into four groups:

| Group | WorldCover codes |
|---|---|
| `forest` | 10 (tree cover), 95 (mangroves) |
| `grassland` | 20 (shrubland), 30 (grassland) |
| `cropland` | 40 - where agricultural burning occurs |
| `other` | 50, 60, 70, 80, 90, 100 |

Each cell reports both the dominant group and the percentage of each group, since a single 11 km cell contains 1.44 million WorldCover pixels and is almost never one uniform class.

## 2.7 Full column list

| Column | Type | Unit | Source | Valid range | Description |
|---|---|---|---|---|---|
| `grid_id` | object | - | derived | - | Grid cell identifier, e.g. '18.5_99.0' |
| `date` | datetime64[ns] | - | derived | - | The day this row describes |
| `latitude` | float64 | degrees | derived | -90 .. 90 | Latitude of the grid cell centre |
| `longitude` | float64 | degrees | derived | -180 .. 180 | Longitude of the grid cell centre |
| `country` | object | - | derived | - | ISO-3 country code, e.g. 'THA' |
| `year` | int64 | - | derived | 2020 .. 2025 | Calendar year, for grouping |
| `month` | int64 | - | derived | 1 .. 12 | Calendar month, for seasonal analysis |
| `fire` | int64 | - | FIRMS | 0 .. 1 | LABEL for the classification model |
| `hotspot_count` | int64 | detections | FIRMS | 0 .. None | How many detections - a measure of extent, not of fire count |
| `frp_max` | float64 | MW | FIRMS | 0 .. None | Peak fire intensity in the cell that day |
| `frp_sum` | float64 | MW | FIRMS | 0 .. None | Total radiative power - scales with both size and intensity |
| `temp_max_c` | float64 | degrees Celsius | ERA5-Land | -90 .. 60 | Daily maximum air temperature |
| `temp_mean_c` | float64 | degrees Celsius | ERA5-Land | -90 .. 60 | Daily mean air temperature |
| `rainfall_mm` | float64 | mm | ERA5-Land | 0 .. None | Total precipitation that day |
| `rainfall_7d_mm` | float64 | mm | ERA5-Land | 0 .. None | Rain over the previous week - dry weeks precede fire seasons |
| `dry_days` | int64 | days | ERA5-Land | 0 .. None | Length of the current dry spell |
| `wind_speed_kmh` | float64 | km/h | ERA5-Land | 0 .. None | Daily mean wind speed - wind spreads fire |
| `soil_moisture` | float64 | m3/m3 | ERA5-Land | 0 .. 1 | Surface soil water content - already a ratio, no conversion |
| `land_cover_dominant` | object | - | WorldCover | - | Most common land-cover group in the cell |
| `forest_pct` | float64 | % | WorldCover | 0 .. 100 | Percent tree cover and mangroves |
| `cropland_pct` | float64 | % | WorldCover | 0 .. 100 | Percent cropland - where agricultural burning occurs |
| `grassland_pct` | float64 | % | WorldCover | 0 .. 100 | Percent grassland and shrubland |
| `other_pct` | float64 | % | WorldCover | 0 .. 100 | Percent built-up, bare, water, wetland and similar |

The columns above are the contract checked by `schema.validate_schema()`. The saved analysis table (`analysis_dataset/analysis_<year>.parquet`) carries six more columns:

| Column | Type | Unit | Source | Description |
|---|---|---|---|---|
| `landcover_coverage_pct` | float64 | % | WorldCover | Share of the cell covered by the land cover map; cells below 50% have empty land cover |
| `day_of_year` | int64 | day | derived | Calendar day, 1 .. 366 |
| `is_dry_season` | int64 | 0/1 | derived | 1 for January to May, the mainland Southeast Asia dry season (`config.DRY_SEASON_MONTHS`) |
| `dry_wind_interaction` | float64 | days × km/h | derived | `dry_days × wind_speed_kmh` - a long dry spell matters more when it is windy |
| `fire_weather_index` | float64 | - | derived | `temp_max_c × (wind_speed_kmh + 1) / ((rainfall_7d_mm + 1) × (soil_moisture + 0.05))` - a simple danger proxy, higher when hot, dry and windy. The small constants avoid division by zero. Not the official Canadian FWI |
| `is_extreme_heat` | int64 | 0/1 | derived | 1 when `temp_max_c ≥ 35` (`config.EXTREME_HEAT_C`) |

## 2.8 How the sources are joined

**Hotspot → grid cell.** Each hotspot is placed in the ERA5-Land cell that contains it by rounding its coordinates to the nearest 0.1°. Nearest-neighbour search was compared against it: inside the weather area the two agree (apart from exact ties), but outside it nearest-neighbour silently attaches the weather of the closest edge cell, however far away. Rounding leaves such hotspots visibly unmatched, so it is the method used. (`schema.latlon_to_grid_id` avoids Python's round-half-to-even and the floating-point error of dividing by 0.1.)

**Fire → weather.** Hotspots are first combined into one row per cell per day, then joined to the daily weather on `(grid_id, date)`. The join is a left join; rows that find no weather are never dropped silently, and the reason for each (cell outside the weather area, day outside the weather dates) is reported. Both sides use UTC dates.

**Country → cell.** Every cell gets the country containing its centre (point in polygon on Natural Earth 1:50m borders, `joins/country_join.py`). A coastal cell whose centre falls in the sea gets the nearest country within 15 km (`config.COASTAL_MAX_DISTANCE_KM`). The result, with the method used and an `in_study_area` flag, is saved in `cell_countries.parquet`.

**Land cover → cell.** Land cover is computed once per grid cell (percentage of each group among the valid pixels inside the cell) and joined to every day of that cell. The share of the cell the map actually covers is kept as `landcover_coverage_pct`; a cell covered by less than 50% is left empty. Land cover at individual hotspots (the pixel under the coordinate, and the pixels in a 375 m square around it) is computed separately for describing hotspots, because one pixel under a hotspot coordinate depends on exactly where inside the 375 m detection pixel the fire is.

**Resolution of the land cover maps.** WorldCover pixels are about 10 m (8.8 × 9.3 m at 18°N). To fit in memory each region's map is capped at about 20 million pixels with nearest-neighbour resampling, which keeps the class codes valid and gives pixels of roughly 60 m.

## 2.9 Known limitations

- **Weather covers fewer places than the fire data.** Only hotspots whose grid cell has weather can be joined, so the joined table describes the weather area, not every country studied. Hotspots outside it remain available for analysis that needs no weather.
- **Edge cells.** Cells on the border of a region are only partly covered by its land cover map; those covered by less than half are left empty.
- **WorldCover is a static 2021 snapshot** joined to every date from 2020-2025 - i.e. land cover is assumed unchanged across six years. In reality forest is cleared and cropland expands.
- **Aggregation discards information.** Many detections within one cell collapse into a handful of numbers; the individual detections are not recoverable from this table.
- **Hotspot counts are detection counts, not fire counts.** One large fire produces many detections across many cells and overpasses.
- **`fire = 0` means "nothing was detected", not "nothing burned".** Cloud, smoke, sub-canopy burning and gaps between overpasses all hide real fires, which weakens the negative class for the classification model.
- **The table covers the study countries only.** The weather grid is a rectangle that also covers parts of China, India, Bangladesh, Bhutan, Malaysia and Indonesia; hotspots there were removed during FIRMS cleaning, so those cells would always read `fire = 0`. Only cells whose centre lies in a study country are kept. Within the study area the table is the full cross product of every cell and every day: for 2020-2025, 16,383 cells × 2,192 days = 35,911,536 rows, stored as one file per year because the whole table does not fit in laptop memory. The region and years processed are set in `src/config.py` (`PROCESSING_REGION`, `PROCESSING_YEARS`).
- **Border cells belong to one country.** A cell's `country` is the country of its centre, so a border cell can hold hotspots of the neighbouring country (1.1% of fire cell-days). See `docs/data_quality_report.md`.

---

# PART 3 - TRAINING SAMPLE AND OUTPUT FILES

## 3.1 Training sample

Fire cell-days are rare (4.6% of the 2020-2025 table), so a model trained on the full table could score high accuracy by always predicting "no fire". `src/features/negative_sampling.py` builds a balanced sample instead:

1. keep **every** fire row;
2. exclude non-fire rows within **1 grid cell and 1 day** of a fire - a missed detection is most likely right next to a detected one, so those `fire = 0` labels are unreliable;
3. draw **3 non-fire rows per fire row** at random from the rest (fixed seed, so the sample is identical on every run).

The sample is built **one year at a time**: each year keeps its own fire rows and draws its negatives from the same year, so every year is represented in proportion to its fires. The buffer still crosses the turn of the year - a fire on 31 December blocks the neighbouring rows of 1 January in the next year's file. For 2020-2025 the sample has 6,601,312 rows (1,650,328 fire + 4,950,984 non-fire), and 8,213,872 non-fire rows were excluded by the buffer.

The ratio, buffer and seed are set in `src/config.py` (`NEGATIVE_RATIO`, `BUFFER_CELLS`, `BUFFER_DAYS`, `RANDOM_SEED`). The sample has every column of the analysis table plus:

| Column | Type | Description |
|---|---|---|
| `near_fire` | int64 | 1 if a non-fire row lies inside a fire buffer. Always 0 in the sample; kept so the rule stays visible and reversible |
| `sample_weight` | float64 | How many rows of the full table this row stands for: 1 for fire rows, (all non-fire rows) ÷ (sampled non-fire rows) for the others. Dividing the fire count by the summed weights gives back the true fire rate |

**Known limitations of the sample**

- Negatives far from fires are easier to tell apart than an average non-fire day, so scores measured on the sample are optimistic. Final evaluation should use the full table.
- The buffer removes most negatives from the peak burning season (in the Chiang Mai test region in March 2020 only 711 of 12,942 non-fire rows remained usable), which makes the calendar a stronger signal in the sample than in reality.
- Train/test splits must be made **by time**, never at random, so the model is never trained on days after the ones it is tested on.

## 3.2 Output files

`uv run scripts/build_dataset.py` writes every table to `data/processed/`:

| File | Grain | Made by |
|---|---|---|
| `firms_clean.parquet` | one hotspot detection | `cleaners/firms_clean.py` |
| `weather_daily.parquet` | one cell, one day | `cleaners/era5_clean.py` + `features/feature_engineering.py` |
| `fire_weather.parquet` | one cell, one day with fire | `joins/spatial_join.py` |
| `landcover_cells.parquet` | one cell | `joins/landcover_join.py` |
| `cell_countries.parquet` | one cell | `joins/country_join.py` |
| `fire_weather_landcover.parquet` | one cell, one day with fire | `joins/landcover_join.py` |
| `analysis_dataset/analysis_<year>.parquet` | one cell, one day (one file per year) | `features/dataset_build.py` + `features/feature_engineering.py` |
| `training_sample.parquet` | one cell, one day (sampled) | `features/negative_sampling.py` |