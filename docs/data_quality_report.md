# Data Quality Report

**Dataset:** analysis table `data/processed/analysis_dataset/analysis_<year>.parquet`
**Region:** mainland Southeast Asia — Thailand, Vietnam, Laos, Cambodia, Myanmar
**Period:** 2020-01-01 to 2025-12-31 (2,192 days)
**Size after checks:** 16,383 grid cells × 2,192 days = **35,911,536 cell-days**, of which 1,650,328 (4.6%) have fire
**Evidence:** every number below is produced by `notebooks/12_data_quality.ipynb` with the functions in `src/quality.py`

## Summary

The checks found one **blocking** problem: 36% of the grid cells lay outside the five study countries, and their `fire = 0` labels were wrong. A second, major problem came from the descriptive analysis: industrial heat sources were counted as fires. Both were traced to their cause and fixed in the pipeline. After the fix, every rule in `src/schema.py` passes for every year, no key is duplicated, no value is missing, and the remaining findings are minor and documented.

**Verdict: the dataset is ready for the risk analysis and modelling stage.**

| # | Finding | Severity | Decision |
|---|---|---|---|
| 1 | 9,321 of 25,704 grid cells (36.3%) outside the study countries, always labelled `fire = 0` | Blocking | Fixed — cells outside removed |
| 2 | `country` taken from hotspots: empty for cells that never burned | Major | Fixed — country from borders |
| 3 | Land-cover sum rule flagged cells left empty by design | Minor (rule error) | Rule fixed |
| 4 | Soil moisture of about −7.7 × 10⁻²¹ | Minor (float noise) | Rule tolerance added, data unchanged |
| 5 | One isolated 46.8 °C cell-day on the southern Thai coast | Minor | Kept, flagged |
| 6 | 1.1% of fire cell-days in border cells whose centre lies in another country | Minor | Accepted |
| 7 | 11.5% of hotspots have `low` confidence; MODIS not used | Note | Kept; to be tested at the model stage |
| 8 | 22,247 hotspots flagged by FIRMS as static land sources or offshore, counted as fires | Major | Fixed — vegetation fires (type 0) only |

## Method

The table is too large to load at once (56 million rows before the fix), so every check reads one year at a time and only the columns it needs.

| Dimension | Question | Function | Result |
|---|---|---|---|
| Completeness | Are values missing? | `missing_values()` | No missing value in any column or year |
| Uniqueness | Is `(grid_id, date)` unique? | `duplicate_keys()` | 0 repeated keys; no row in the wrong year's file |
| Validity | Do values obey the schema rules? | `rule_problems()` | 0 violations in all six years |
| Coverage | Do the cells belong to the study area? | `cells_by_country()` | Finding 1 |
| Plausibility | Are extreme values believable? | `extremes()`, `compare_with_neighbours()` | Findings 5 and the table below |
| Consistency | Do hotspot and cell agree on the country? | `hotspot_vs_cell_country()` | 98.9% agree (finding 6) |
| Volume | Records per country and year | `counts_by_country_year()` | See "Volume" |

## Findings

### 1. Grid cells outside the study area (blocking, fixed)

**How it was found.** The lowest daily maximum temperature in the first version of the table was −17.3 °C, in cell `28.0_92.6` (24 January 2020). That cell is in Arunachal Pradesh, India.

**Cause.** ERA5-Land and WorldCover were downloaded for a rectangle (92–109.5 °E, 5.5–28.5 °N). Besides the five study countries it covers parts of China (7,240 cells), India (1,758), Malaysia (156), Bangladesh (147), Indonesia (13) and Bhutan (5). FIRMS hotspots outside the study countries were removed during cleaning, so these cells read `fire = 0` on every day, including days when they burned.

**Impact before the fix.** 45.4% of the non-fire rows in the training sample came from such cells. A model could have learned "cold, mountainous, Chinese or Indian cell → no fire" from wrong labels. The comparison of fire rates by land cover was also distorted: forest looked less fire-prone than it is, because Chinese and Indian forest cells counted as never burning.

**Fix.** `src/joins/country_join.py` gives every cell the country containing its centre (point in polygon, Natural Earth 1:50m). The 177 coastal cells whose centre falls in the sea get the nearest country within 15 km; 2 cells have no country. Only cells of the study countries are kept (`dataset_build.keep_study_area()`), and the removal is reported:

| | Cells | Cell-days |
|---|---|---|
| Kept | 16,383 | 35,911,536 |
| Removed | 9,321 | 20,431,632 |
| Fire cell-days removed | — | 2,603 of 1,652,931 (0.16%) |

The fire cell-days removed are border cells whose centre lies in a neighbouring country.

### 2. Country taken from hotspots (major, fixed)

`country` used to come from the hotspots inside each cell, so 404 cells inside the study countries that never burned in 2020–2025 had no country. Country is now the country of the cell centre for every cell, which also makes per-country statistics comparable (same rule for burned and unburned cells). After the fix no row has an empty `country`.

### 3. Land-cover percentage rule (rule error, fixed)

The rule "the four land-cover percentages add up to 100" flagged about 730 rows per year. They belong to two cells covered by less than half of the land-cover map (26.6% and 29.0%), whose percentages are left empty on purpose. The rule now skips rows where all four values are empty and still flags rows where only some are. Both cells lie in China and are outside the study area anyway.

### 4. Negative soil moisture (float noise, rule fixed)

Seven cell-days had soil moisture of about −7.7 × 10⁻²¹, which is zero within floating-point precision. Range checks now allow a tolerance of 10⁻⁹ (`schema.RANGE_TOLERANCE`); a real negative value such as −0.01 is still reported. The data was not changed.

### 5. Extreme values (plausibility)

| Value | Where and when | Evidence | Decision |
|---|---|---|---|
| 618 mm of rain in one day | Hà Tĩnh – Quảng Bình, Vietnam, 20 Oct 2020 | All neighbouring cells 450–590 mm: the October 2020 central Vietnam floods | Real, kept |
| −17.4 °C daily maximum | Far north of Myanmar (28.5 °N, 97.6 °E), 17 Jan 2022 | High Himalayan terrain around Hkakabo Razi | Real, kept |
| **46.8 °C daily maximum** | Coastal cell `8.1_98.8`, southern Thailand, 16 May 2020 | Every neighbour with data 33.4–33.9 °C; the only cell above 45 °C in 2020 | **Suspicious**, kept and flagged |
| 62.7 km/h daily mean wind | Northern Vietnam coast, 7 Sep 2024 | Landfall of Typhoon Yagi | Real, kept |
| 197 consecutive dry days | Magway, central Myanmar, ending 11 May 2023 | Myanmar's Dry Zone has a long dry season | Plausible, kept |
| 2,317 MW fire radiative power | Shan State, Myanmar, 24 Mar 2020 | Peak of the burning season | Plausible, kept |

A real weather event covers many neighbouring cells; a value far from all of its neighbours is more likely an error. The 46.8 °C value is most likely an ERA5-Land artefact at the land–sea edge. It affects one cell-day out of 35.9 million and is left in place, documented here.

### 6. Hotspot country vs cell country (minor, accepted)

1,634,213 of 1,652,931 fire cell-days (98.9%) have hotspots in the same country as the cell centre. The rest are border cells (for example Myanmar hotspots in a cell centred in Thailand). This is the expected effect of an 11 km grid on borders and is accepted.

### 7. Confidence and sensors (note)

All 5,007,866 cleaned hotspots are VIIRS (S-NPP); MODIS was not used. 11.5% have `low` confidence and are kept. Whether dropping them changes the model will be tested at the modelling stage.

### 8. Static land sources counted as fires (major, fixed)

**How it was found.** In the descriptive analysis (`notebooks/13_descriptive_analysis.ipynb`) a few cells in Saraburi, central Thailand, had a hotspot on about 183 days a year, twice as many as the most fire-prone forest cells. Saraburi is Thailand's cement-making centre: the kilns are hot all year round and the satellite sees them as permanent thermal anomalies.

**Cause.** FIRMS gives every VIIRS detection a `type`: 0 presumed vegetation fire, 1 active volcano, 2 other static land source, 3 offshore. The cleaning kept all types. In the five study countries 20,329 hotspots were type 2 (industrial sites such as cement plants) and 1,918 type 3 (offshore, mostly gas platforms).

**Fix.** `cleaners/firms_clean.keep_vegetation_fires()` keeps type 0 only and reports the rows removed by type (`config.FIRMS_FIRE_TYPES`). After the rebuild 12,080 fire cell-days changed to `fire = 0` (1,662,408 → 1,650,328 in the study area). Because these sources burn every day, they had a large effect on single cells and on the cell rankings, but a small one on country totals.

## Volume by country and year

Fire cell-days per grid cell (fire cell-days divided by the country's number of cells):

| Country | Cells | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|---|---|
| Cambodia (KHM) | 1,508 | 38.18 | 30.75 | 18.58 | 26.66 | 32.82 | 23.99 |
| Laos (LAO) | 1,956 | 22.86 | 18.52 | 16.53 | 32.27 | 25.25 | 18.79 |
| Myanmar (MMR) | 5,787 | 21.87 | 18.39 | 13.64 | 21.55 | 18.01 | 15.47 |
| Thailand (THA) | 4,331 | 19.55 | 11.76 | 7.29 | 16.01 | 13.86 | 10.05 |
| Vietnam (VNM) | 2,801 | 11.38 | 9.68 | 7.23 | 10.19 | 10.52 | 7.95 |

- Every country has its lowest value in 2022, so the dip is regional (2022 was the third consecutive La Niña year) rather than a data gap in one country. Thailand's 2022 value is 37% of its 2020 value, the largest relative drop.
- Myanmar has the most hotspots in total, but Cambodia has the most fire days per cell in five of the six years: totals and densities rank countries differently.

## Remaining limitations

- `fire = 0` means "no hotspot detected", not "no fire": cloud, smoke and overpass timing hide fires.
- WorldCover is a single 2021 map applied to all six years.
- Border cells are assigned to one country by their centre.
- The 46.8 °C cell-day (finding 5) remains in the data.

## How to reproduce

```bash
uv run scripts/build_dataset.py --force   # rebuild every step from the raw downloads
uv run jupyter nbconvert --to notebook --execute notebooks/12_data_quality.ipynb
```