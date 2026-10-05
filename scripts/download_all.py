import logging
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import argparse 
import calendar

import config
import pipeline 

log=logging.getLogger("download_all")

def download_firms_batch(countries,start,end,force=False):
    import firms_api

    counts = {"ok": 0, "skipped": 0, "failed": 0}
    bbox = pipeline.bbox_for_countries(countries)
    label = "-".join(sorted(countries))      # e.g. "KHM-LAO-MMR-THA-VNM"
    chunks = pipeline.split_into_chunks(start, end, config.MAX_DAY_RANGE)

    log.info("FIRMS box for %s: %s", label, bbox)

    for chunk_start, days in chunks:
        key = f"{label}_{chunk_start}_{days}d"

        # Already downloaded? Skip it.
        if not force and pipeline.is_downloaded("firms", key):
            counts["skipped"] += 1
            continue

        folder = config.RAW_SUBDIRS["firms"] / str(chunk_start.year)
        arguments = {
            "source": config.DEFAULT_SOURCE,
            "bbox": bbox,
            "day_range": days,
            "date": str(chunk_start),
            "use_cache": not force,
            "verbose": False,
            "folder": folder,
        }

        try:
            table = pipeline.call_with_retry(firms_api.download_firms, arguments)
        except ValueError:
            raise   # wrong input: stop everything
        except Exception as error:
            log.warning("FIRMS %s failed: %s", key, error)
            pipeline.record_download("firms", key, status="failed", message=str(error)[:200])
            counts["failed"] += 1
            continue

        if table is None:
            log.warning("FIRMS %s returned nothing", key)
            pipeline.record_download("firms", key, status="failed", message="no data returned")
            counts["failed"] += 1
            continue

        # download_firms() already saved the file - just find out where
        saved_file = firms_api._cache_path(config.DEFAULT_SOURCE, bbox, days,
                                               str(chunk_start), folder)
        pipeline.record_download("firms", key, path=saved_file, status="ok")
        counts["ok"] += 1
        log.info("FIRMS %s -> %d rows", key, len(table))

    return counts

def months_between(start,end):
    first = pipeline.parse_date(start)
    last = pipeline.parse_date(end)

    months = []
    year = first.year
    month = first.month
    while (year, month) <= (last.year, last.month):
        months.append((year, month))
        month = month + 1
        if month > 12:
            month = 1
            year = year + 1

    return months

def download_era5_batch(regions,start,end,force=False):
    import era5_api

    counts = {"ok": 0, "skipped": 0, "failed": 0}
    variables = list(config.ERA5_VARIABLES.keys())

    for name in regions:
        west, south, east, north = pipeline.parse_bbox(regions[name])
        area = [north, west, south, east]   # Copernicus order, NOT the FIRMS order

        for year, month in months_between(start, end):
            key = f"{name}_{year}-{month:02d}"

            if not force and pipeline.is_downloaded("era5", key):
                counts["skipped"] += 1
                continue

            folder = config.RAW_SUBDIRS["era5"] / str(year)
            arguments = {
                "variables": variables,
                "area": area,
                "year": year,
                "month": month,
                "use_cache": not force,
                "verbose": False,
                "folder": folder,
            }

            try:
                dataset = pipeline.call_with_retry(era5_api.download_era5_month, arguments)
            except ValueError:
                raise
            except Exception as error:
                log.warning("ERA5 %s failed: %s", key, error)
                pipeline.record_download("era5", key, status="failed", message=str(error)[:200])
                counts["failed"] += 1
                continue

            if dataset is None:
                pipeline.record_download("era5", key, status="failed", message="no data returned")
                counts["failed"] += 1
                continue

            # download_era5_month() already saved the file - find its name
            n_days = calendar.monthrange(year, month)[1]
            saved_file = era5_api._cache_path(variables, area, year, month,
                                                  f"01to{n_days:02d}", folder)
            pipeline.record_download("era5", key, path=saved_file, status="ok")
            counts["ok"] += 1
            log.info("ERA5 %s -> ok", key)

    return counts

def download_worldcover_batch(regions,year,force=False):
    import worldcover_api

    counts = {"ok": 0, "skipped": 0, "failed": 0}
    folder = config.RAW_SUBDIRS["worldcover"] / str(year)

    for name in regions:
        key = f"{name}_{year}"

        if not force and pipeline.is_downloaded("worldcover", key):
            counts["skipped"] += 1
            continue

        west, south, east, north = pipeline.parse_bbox(regions[name])
        bbox = (west, south, east, north)

        try:
            result = worldcover_api.download_worldcover(bbox, year=year, use_cache=not force,
                                                        verbose=False, folder=folder)
        except ValueError:
            raise
        except Exception as error:
            log.warning("WorldCover %s failed: %s", key, error)
            pipeline.record_download("worldcover", key, status="failed", message=str(error)[:200])
            counts["failed"] += 1
            continue

        if result is None:
            pipeline.record_download("worldcover", key, status="failed", message="no data returned")
            counts["failed"] += 1
            continue

        data, transform = result
        saved_file = worldcover_api._cache_path(bbox, year, folder)
        pipeline.record_download("worldcover", key, path=saved_file, status="ok")
        counts["ok"] += 1
        log.info("WorldCover %s -> %s", key, data.shape)

    return counts

def build_parser():
    parser = argparse.ArgumentParser(
        description="Download raw wildfire-project data in bulk.",
        epilog="Run with --dry-run first. It takes 2 seconds and can save a week.",
    )
    parser.add_argument("--source", default="all",
                        choices=["all", "firms", "era5", "worldcover"],
                        help="which data source to download (default: all)")
    parser.add_argument("--countries", nargs="+", default=None,
                        help="country codes, e.g. THA VNM (default: config.STUDY_COUNTRIES)")
    parser.add_argument("--regions", nargs="+", default=None,
                        help="region names from config.STUDY_REGIONS (default: all)")
    parser.add_argument("--start", default=config.STUDY_START, help="YYYY-MM-DD")
    parser.add_argument("--end", default=config.STUDY_END, help="YYYY-MM-DD")
    parser.add_argument("--year", type=int, default=config.DEFAULT_YEAR,
                        help="WorldCover year (2020 or 2021)")
    parser.add_argument("--dry-run", action="store_true",
                        help="only estimate the size, do not download")
    parser.add_argument("--force", action="store_true",
                        help="download again even if already downloaded")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser

def main(argv=None):
    args = build_parser().parse_args(argv)
    log_file = pipeline.setup_logging(level=args.log_level)

    # Which countries?
    if args.countries:
        countries = args.countries
    else:
        countries = config.STUDY_COUNTRIES

    # Which regions?
    if args.regions:
        unknown = []
        for name in args.regions:
            if name not in config.STUDY_REGIONS:
                unknown.append(name)
        if len(unknown) > 0:
            raise SystemExit(f"Unknown region(s): {sorted(unknown)}. "
                             f"Known: {sorted(config.STUDY_REGIONS)}")
        regions = {}
        for name in args.regions:
            regions[name] = config.STUDY_REGIONS[name]
    else:
        regions = config.STUDY_REGIONS

    log.info("source=%s countries=%s regions=%s %s..%s",
             args.source, countries, list(regions), args.start, args.end)
    log.info("log file: %s", log_file)

    # --dry-run: estimate and stop
    if args.dry_run:
        print()
        print("=" * 74)
        print("DRY RUN - nothing will be downloaded")
        print("=" * 74)
        pipeline.estimate_all(countries, list(regions.values()), args.start, args.end)
        print()
        print("Run again without --dry-run to really download.")
        return 0

    totals = {"ok": 0, "skipped": 0, "failed": 0}

    try:
        if args.source in ["all", "firms"]:
            counts = download_firms_batch(countries, args.start, args.end, args.force)
            for key in totals:
                totals[key] += counts[key]

        if args.source in ["all", "worldcover"]:
            counts = download_worldcover_batch(regions, args.year, args.force)
            for key in totals:
                totals[key] += counts[key]

        if args.source in ["all", "era5"]:
            counts = download_era5_batch(regions, args.start, args.end, args.force)
            for key in totals:
                totals[key] += counts[key]

    except KeyboardInterrupt:
        log.warning("stopped by user - what was done so far is in the manifest")
    except ValueError as error:
        # fail-fast: a wrong input means everything else would be wrong too
        log.error("stopping: %s", error)
        return 2

    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"  downloaded : {totals['ok']}")
    print(f"  skipped    : {totals['skipped']}  (already done)")
    print(f"  failed     : {totals['failed']}")
    print(f"  log file   : {log_file}")

    summary = pipeline.manifest_summary()
    if len(summary) > 0:
        print()
        print(summary.to_string(index=False))

    if totals["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())