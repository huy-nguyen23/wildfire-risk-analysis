from config import TILE_SIZE,DEFAULT_YEAR,WORLDCOVER_VERSION,WORLDCOVER_URL,RAW_DIR
from rasterio.merge import merge 
import math
import rasterio


def _tile_name(latitude,longitude,tile_size=TILE_SIZE):
    tile_lat = math.floor(latitude / tile_size) * tile_size
    tile_lon = math.floor(longitude / tile_size) * tile_size
    lat_str = f"N{tile_lat:02d}" if tile_lat >= 0 else f"S{abs(tile_lat):02d}"
    lon_str = f"E{tile_lon:03d}" if tile_lon >= 0 else f"W{abs(tile_lon):03d}"
    return f"{lat_str}{lon_str}"

def tiles_for_bbox(west,south,east,north,tile_size=TILE_SIZE):
    """List every tile whose 3x3 degree cell overlaps a bounding box.

    Checking only the four corners of the box is NOT enough: a box wide
    enough to span three or more tiles in one direction would skip the
    middle tile(s) if only the two end corners were checked. This walks
    every grid line the box crosses instead.

    Args:
        west, south, east, north: bounding box in degrees (FIRMS bbox order,
            matching Session 2's convention).
        tile_size: degrees per tile edge (3 for WorldCover).

    Returns:
        Sorted list of tile name strings, e.g. ['N15E096', 'N15E099', ...].
    """
    lat_start = math.floor(south / tile_size) * tile_size
    lat_stop = math.ceil(north / tile_size) * tile_size
    lon_start = math.floor(west / tile_size) * tile_size
    lon_stop = math.ceil(east / tile_size) * tile_size

    tiles = []
    for lat in range(int(lat_start), int(lat_stop), tile_size):
        for lon in range(int(lon_start), int(lon_stop), tile_size):
            tiles.append(_tile_name(lat, lon, tile_size))

    return sorted(tiles)

def tile_url(tile_name,year=DEFAULT_YEAR):
    """Build the public HTTPS URL for one WorldCover tile.

    Args:
        tile_name: e.g. 'N15E096'.
        year: 2020 or 2021.

    Returns:
        Full HTTPS URL string.

    Raises:
        ValueError: if year is not a supported WorldCover release.
    """
    if year not in WORLDCOVER_VERSION:
        raise ValueError(f"year must be one of {sorted(WORLDCOVER_VERSION)}, got {year}")
    version=WORLDCOVER_VERSION[year]
    filename=f"ESA_WorldCover_10m_{year}_{version}_{tile_name}_Map.tif"
    return f"{WORLDCOVER_URL}/{version}/{year}/map/{filename}"

def open_tile(tile_name,year=DEFAULT_YEAR):
    """Open a remote WorldCover tile with rasterio, without downloading it.

    Thanks to the Cloud-Optimized GeoTIFF format, opening a dataset only
    reads a small amount of metadata over the network - the pixel data is
    fetched later, and only for the region actually requested (see
    read_window()).

    Args:
        tile_name: e.g. 'N15E096'.
        year: 2020 or 2021.

    Returns:
        An open rasterio dataset. Caller is responsible for closing it
        (use a `with` block, or call .close()).
    """
    return rasterio.open(tile_url(tile_name,year))

def _decimated_shape(width_px,height_px,max_pixels):
    native_pixels=width_px*height_px
    if native_pixels<=max_pixels:
        return None
    scale=math.sqrt(native_pixels/max_pixels)
    return (max(1,int(height_px/scale)),max(1,int(width_px/scale)) )

def rasterio_scale(x_scale, y_scale):
    """Return an affine scaling transform (thin wrapper for readability)."""
    from affine import Affine

    return Affine.scale(x_scale, y_scale)

def read_window(tile_name,bbox,year=DEFAULT_YEAR,max_pixels=20000000):
    """Read just the pixels of one tile that fall inside a bounding box.

    Args:
        tile_name: e.g. 'N15E096'.
        bbox: (west, south, east, north) in degrees.
        year: 2020 or 2021.
        max_pixels: safety cap on the output array size (default ~20 million,
            about 20MB as uint8). If the native-resolution window would
            exceed this, the read is automatically downsampled - using
            nearest-neighbour resampling, since this is CATEGORICAL data:
            averaging class code 10 (tree cover) with 80 (water) would
            produce 45, a code that names no real class. Pass None to force
            full native ~10m resolution (only for genuinely small areas).

    Returns:
        (data, transform): a 2D numpy array of class codes, and the affine
        transform mapping its pixel (row, col) indices to real coordinates.
    """
    from rasterio.enums import Resampling
    from rasterio.windows import Window

    west, south, east, north = bbox

    with open_tile(tile_name, year) as src:
        window = src.window(west, south, east, north)

        window = window.intersection(Window(0, 0, src.width, src.height))

        out_shape = None
        if max_pixels is not None:
            out_shape = _decimated_shape(window.width, window.height, max_pixels)

        if out_shape:
            data = src.read(1, window=window, out_shape=out_shape, resampling=Resampling.nearest)
            transform = src.window_transform(window) * rasterio_scale(
                window.width / out_shape[1], window.height / out_shape[0]
            )
        else:
            data = src.read(1, window=window)
            transform = src.window_transform(window)

    return data, transform

def mosaic_tiles(tile_names,bbox,year=DEFAULT_YEAR,max_pixels=20000000):
    """Merge several tiles into one array, clipped to a bounding box.

    Needed whenever tiles_for_bbox() returns more than one tile - the usual
    case for any area of interest that happens to straddle the fixed 3x3
    degree grid, exactly as it does for this project's Chiang Mai test box.

    Args:
        tile_names: list of tile name strings, e.g. from tiles_for_bbox().
        bbox: (west, south, east, north) in degrees.
        year: 2020 or 2021.
        max_pixels: safety cap on the output array size (default ~20 million).
            See read_window() for why this matters: this project's own
            Chiang Mai bbox is about 2x3 degrees, which at native ~10m
            resolution merges to roughly 740 million pixels - large enough
            to crash a typical laptop's Jupyter kernel outright. Pass None
            to force full native ~10m resolution.

    Returns:
        (mosaic, transform): a single 2D numpy array covering the full bbox,
        and its affine transform.
    """
    west,south,east,north=bbox
    datasets=[open_tile(t,year) for t in tile_names]
    
    res=None
    if max_pixels is not None:
        native_res_x= datasets[0].transform.a 
        native_res_y=-datasets[0].transform.e 
        native_cols=(east-west)/native_res_x
        native_rows=(north-south)/native_res_y
        if native_cols*native_rows> max_pixels:
            scale=math.sqrt((native_cols*native_rows)/max_pixels)
            res=(native_res_x*scale,native_res_y*scale)        
        
    try:
        mosaic,out_transform=merge(datasets,bounds=(west,south,east,north),res=res)
    finally:
        for ds in datasets:
            ds.close()
    
    return mosaic[0], out_transform
        
def _validate_bbox(bbox):
    if len(bbox) != 4:
        raise ValueError(f"bbox needs exactly 4 numbers (west,south,east,north). Got: {bbox!r}")

    west, south, east, north = (float(x) for x in bbox)

    if not (-180 <= west <= 180 and -180 <= east <= 180):
        raise ValueError("Longitude must be between -180 and 180")
    if not (-90 <= south <= 90 and -90 <= north <= 90):
        raise ValueError("Latitude must be between -90 and 90")
    if west >= east:
        raise ValueError("Wrong order: west must be LESS THAN east (west,south,east,north)")
    if south >= north:
        raise ValueError("Wrong order: south must be LESS THAN north (west,south,east,north)")

    return west, south, east, north


def _validate_year(year):
    if year not in WORLDCOVER_VERSION:
        raise ValueError(f"year must be one of {sorted(WORLDCOVER_VERSION)}, got {year}")


def _cache_path(bbox, year):
    safe_bbox = "_".join(str(round(x, 3)) for x in bbox).replace(".", "p").replace("-", "m")
    return RAW_DIR / f"worldcover_{year}_{safe_bbox}.tif"

def download_worldcover(bbox,year=DEFAULT_YEAR,use_cache=True,verbose=True,max_pixels=20000000):
    """Download and mosaic every WorldCover tile covering a bounding box.

    This is the production entry point for the project, reused from later
    sessions onward - the same role download_firms() and download_era5()
    play for their sources.

    Args:
        bbox: (west, south, east, north) in degrees.
        year: 2020 or 2021.
        use_cache: read a previously saved mosaic instead of re-downloading.
        verbose: print progress messages.
        max_pixels: safety cap on the output array size (default ~20
            million). See mosaic_tiles() for why this matters - without it,
            a multi-degree bbox at WorldCover's native ~10m resolution can
            produce an array large enough to crash the kernel outright. Pass
            None to force full native ~10m resolution.

    Returns:
        (data, transform): a 2D numpy array of class codes covering the full
        bbox, and its affine transform. None if the download failed.

    Raises:
        ValueError: if bbox or year are invalid - programming mistakes worth
            catching before any network request, not runtime conditions.
    """
    west, south, east, north = _validate_bbox(bbox)
    _validate_year(year)

    cache_file = _cache_path(bbox, year)
    if use_cache and cache_file.exists():
        if verbose:
            print(f"[cache] Reading {cache_file.name}")
        with rasterio.open(cache_file) as src:
            return src.read(1), src.transform

    tiles = tiles_for_bbox(west, south, east, north)
    if verbose:
        print(f"Area needs {len(tiles)} tile(s): {tiles}")

    try:
        data, transform = mosaic_tiles(
            tiles, (west, south, east, north), year, max_pixels=max_pixels,
        )
    except Exception as err:
        print(f"[ERROR] Could not read WorldCover tiles: {err}")
        print("  Common causes: no internet reaching AWS S3, or a tile name "
              "that does not exist (area over open ocean far from any tile).")
        return None

    # Cache the merged result as a small GeoTIFF so a rerun is instant.
    with rasterio.open(
        cache_file, "w", driver="GTiff",
        height=data.shape[0], width=data.shape[1], count=1,
        dtype=data.dtype, crs="EPSG:4326", transform=transform,
        compress="deflate",
    ) as dst:
        dst.write(data, 1)

    if verbose:
        print(f"[downloaded] {cache_file.name} - shape {data.shape}")

    return data, transform
    
    
    
    
    