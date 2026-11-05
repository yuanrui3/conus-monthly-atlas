#!/usr/bin/env python3
"""Build a documented November 2006–2025 climate overview from NOAA COGs.

Usage:
  python -m pip install -r scripts/climate_requirements.txt
  python scripts/climate_build.py --cache /tmp/conus-climate-cache

All inputs are free public NOAA/NIDIS Cloud-Optimized GeoTIFFs. Raw rasters
are cached outside this repository. No vehicle performance is estimated.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request

import numpy as np
import rasterio


YEARS = tuple(range(2006, 2026))
MONTH = 11
SOURCE_URL = "https://www.drought.gov/data-maps-tools/gridded-climate-datasets-noaas-nclimgrid-monthly"
BUCKET = "https://storage.googleapis.com/noaa-ncei-nclimgrid-monthly"
DATA_TEMPLATE = BUCKET + "/cog/{year}/nclimgrid-monthly-{year}11.tif"
LAYERS = [
    {
        "id": "mean_temp_c", "band": "tavg", "label": "Mean temperature", "unit": "°C",
        "description": "Mean of the 20 November monthly mean air temperatures, 2006–2025.",
        "palette": "temperature",
    },
    {
        "id": "min_temp_c", "band": "tmin", "label": "Mean daily minimum", "unit": "°C",
        "description": "Mean of November's monthly average daily minimum air temperature in each of the 20 years. This is not the coldest observed temperature.",
        "palette": "temperature",
    },
    {
        "id": "max_temp_c", "band": "tmax", "label": "Mean daily maximum", "unit": "°C",
        "description": "Mean of November's monthly average daily maximum air temperature in each of the 20 years. This is not the hottest observed temperature.",
        "palette": "temperature",
    },
    {
        "id": "precip_mm", "band": "precip", "label": "Total precipitation", "unit": "mm/month",
        "description": "Mean of the 20 November precipitation totals, 2006–2025; liquid-equivalent precipitation, not soil moisture or snow depth.",
        "palette": "precipitation",
    },
]


def fetch(year: int, cache: Path) -> tuple[int, Path, dict]:
    url = DATA_TEMPLATE.format(year=year)
    target = cache / f"{year}11.tif"
    sidecar = cache / f"{year}11.json"
    if target.exists() and sidecar.exists():
        record = json.loads(sidecar.read_text())
        if hashlib.sha256(target.read_bytes()).hexdigest() == record["sha256"]:
            print(f"Cached {year}: {target.stat().st_size:,} bytes", flush=True)
            return year, target, record
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "CONUS-November-Environmental-Atlas/0.1"})
            with urllib.request.urlopen(request, timeout=70) as response:
                content = response.read()
                headers = dict(response.headers)
            if len(content) < 1_000_000 or content[:4] not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
                raise ValueError(f"Invalid TIFF response for {url}")
            temporary = target.with_suffix(".part")
            temporary.write_bytes(content)
            temporary.replace(target)
            record = {
                "year": year, "month": MONTH, "url": url,
                "retrievedAt": datetime.now(timezone.utc).isoformat(),
                "lastModified": headers.get("Last-Modified"),
                "etag": headers.get("ETag"), "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            sidecar.write_text(json.dumps(record, indent=2) + "\n")
            print(f"Downloaded {year}: {len(content):,} bytes", flush=True)
            return year, target, record
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def array_json(a: np.ndarray, digits: int = 2) -> list:
    rounded = np.round(a, digits).reshape(-1)
    return [None if not np.isfinite(v) else float(v) for v in rounded]


def verify_units_reference(november_2025: Path) -> dict:
    """Check COG units and band mapping against retained original NOAA records.

    These records were read directly from NOAA's 2025 monthly .pnt files.
    Their README specifies degrees Celsius and millimetres. This is a data
    conversion check, not independent validation of the climate estimates.
    """
    path = Path(__file__).with_name("climate_unit_reference.json")
    reference = json.loads(path.read_text())
    max_error = 0.0
    results = []
    with rasterio.open(november_2025) as raster:
        for record in reference["records"]:
            band = raster.descriptions.index(record["band"])
            for point in record["points"]:
                actual = float(next(raster.sample([(point["lon"], point["lat"])]))[band])
                difference = abs(actual - point["november2025"])
                if not np.isfinite(difference) or difference >= 0.00001:
                    raise ValueError(f"Unit reference changed for {record['band']} at {point}; inspect source revision before publishing")
                max_error = max(max_error, difference)
            results.append({"band": record["band"], "unit": record["unit"], "sourceUrl": record["sourceUrl"], "matchedPointCount": len(record["points"]), "sampleSha256": record["sampleSha256"]})
    return {
        "passed": True, "pointComparisons": sum(r["matchedPointCount"] for r in results),
        "tolerance": 0.00001, "maximumAbsoluteDifference": max_error,
        "documentationUrl": reference["documentationUrl"],
        "referenceFileSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "purpose": reference["purpose"], "results": results,
    }


def aggregate(a: np.ndarray, weights: np.ndarray, factor: int) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted mean of available native cells; no spatial interpolation.

    Cell area is proportional to sin(north)-sin(south) on this regular
    longitude grid. A padded partial east-edge group retains only actual cells.
    """
    h, w = a.shape
    hp = ((h + factor - 1) // factor) * factor
    wp = ((w + factor - 1) // factor) * factor
    valid = np.isfinite(a)
    padded = np.zeros((hp, wp), dtype=np.float64)
    weighted = np.zeros((hp, wp), dtype=np.float64)
    count = np.zeros((hp, wp), dtype=np.uint8)
    broadcast_weights = np.broadcast_to(weights[:, None], a.shape)
    padded[:h, :w] = np.where(valid, a * broadcast_weights, 0)
    weighted[:h, :w] = np.where(valid, broadcast_weights, 0)
    count[:h, :w] = valid.astype(np.uint8)
    shape = (hp // factor, factor, wp // factor, factor)
    sums = padded.reshape(shape).sum(axis=(1, 3))
    denominators = weighted.reshape(shape).sum(axis=(1, 3))
    cells = count.reshape(shape).sum(axis=(1, 3))
    result = np.full(sums.shape, np.nan)
    np.divide(sums, denominators, out=result, where=denominators > 0)
    return result, cells


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/conus-climate-cache"))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "docs/data/climate.json")
    parser.add_argument("--factor", type=int, default=2)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.factor < 1 or args.factor > 8:
        raise ValueError("factor must be 1–8")
    args.cache.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    acquired = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(fetch, year, args.cache) for year in YEARS]
        for future in as_completed(futures):
            year, path, record = future.result()
            acquired[year] = (path, record)

    unit_verification = verify_units_reference(acquired[2025][0])
    reference = None
    band_arrays = {layer["id"]: [] for layer in LAYERS}
    file_checks = []
    for year in YEARS:
        path, record = acquired[year]
        with rasterio.open(path) as source:
            signature = (source.width, source.height, tuple(source.transform), source.crs.to_epsg(), source.descriptions)
            if reference is None:
                reference = signature
                native_w, native_h = source.width, source.height
                transform = source.transform
                native_bounds = list(source.bounds)
                original_metadata = {"tags": source.tags(), "descriptions": source.descriptions, "scales": source.scales, "offsets": source.offsets, "crs": str(source.crs)}
                assert source.crs.to_epsg() == 4326, "Expected WGS84 geographic grid"
                assert transform.a > 0 and transform.e < 0 and transform.b == transform.d == 0
                assert set(source.descriptions) == {"precip", "tmin", "tmax", "tavg"}
            if signature != reference:
                raise ValueError(f"Grid or band alignment changed in {year}; cannot average without explicit resampling")
            values_this_year = {}
            for layer in LAYERS:
                band = source.descriptions.index(layer["band"]) + 1
                arr = source.read(band, masked=True).astype(np.float64).filled(np.nan)
                arr = arr * source.scales[band - 1] + source.offsets[band - 1]
                values_this_year[layer["id"]] = arr
                band_arrays[layer["id"]].append(arr)
            assert np.nanmin(values_this_year["precip_mm"]) >= 0, f"Negative precipitation in {year}"
            valid = np.isfinite(values_this_year["mean_temp_c"])
            assert np.all(values_this_year["min_temp_c"][valid] <= values_this_year["mean_temp_c"][valid] + 0.02)
            assert np.all(values_this_year["mean_temp_c"][valid] <= values_this_year["max_temp_c"][valid] + 0.02)
            file_checks.append({"year": year, "nativeValidCells": int(valid.sum()), "gridAligned": True, "temperatureOrderValid": True})

    lat_north = transform.f + np.arange(native_h) * transform.e
    lat_south = lat_north + transform.e
    weights = np.sin(np.deg2rad(lat_north)) - np.sin(np.deg2rad(lat_south))
    grid_values, grid_counts, grid_stddev = {}, {}, {}
    layers = []
    native_incomplete = {}
    source_cell_count = None
    annual_summary = {year: {"year": year} for year in YEARS}
    for layer in LAYERS:
        key = layer["id"]
        stack = np.stack(band_arrays.pop(key), axis=0)
        native_counts = np.isfinite(stack).sum(axis=0)
        complete = native_counts == len(YEARS)
        native_incomplete[key] = int(((native_counts > 0) & ~complete).sum())
        # A native cell with any missing November is excluded from the full-baseline estimate.
        numerator = np.where(np.isfinite(stack), stack, 0).sum(axis=0)
        native_mean = np.full((native_h, native_w), np.nan)
        native_mean[complete] = numerator[complete] / len(YEARS)
        overview, cells = aggregate(native_mean, weights, args.factor)
        if source_cell_count is None:
            source_cell_count = cells
        elif not np.array_equal(cells, source_cell_count):
            raise ValueError("Variable masks differ; require variable-specific contributor counts")
        grid_values[key] = array_json(overview)
        grid_counts[key] = np.where(np.isfinite(overview), len(YEARS), 0).reshape(-1).tolist()
        finite = overview[np.isfinite(overview)]
        stats = {
            "min": round(float(finite.min()), 2), "max": round(float(finite.max()), 2),
            "p02": round(float(np.percentile(finite, 2)), 2), "p98": round(float(np.percentile(finite, 98)), 2),
            "validCells": len(finite),
        }
        layers.append({**layer, **stats})
        # Compute variation across annual November summaries, not daily variation.
        annual_overview = []
        for year_index, year in enumerate(YEARS):
            year_native = np.where(complete, stack[year_index], np.nan)
            year_grid, year_cells = aggregate(year_native, weights, args.factor)
            assert np.array_equal(year_cells, cells)
            if key in ("mean_temp_c", "precip_mm"):
                annual_overview.append(year_grid)
            w = np.broadcast_to(weights[:, None], year_native.shape)
            valid = np.isfinite(year_native)
            annual_summary[year][key] = round(float((year_native[valid] * w[valid]).sum() / w[valid].sum()), 3)
        if annual_overview:
            annual_stack = np.stack(annual_overview)
            centered = np.where(np.isfinite(annual_stack), annual_stack - overview[None, :, :], 0)
            sd = np.sqrt((centered ** 2).sum(axis=0) / (len(YEARS) - 1))
            sd[~np.isfinite(overview)] = np.nan
            grid_stddev[key] = array_json(sd)
        print(f"Computed {key}: {stats}", flush=True)

    out_h, out_w = source_cell_count.shape
    display_x = transform.a * args.factor
    display_y = -transform.e * args.factor
    lon = transform.c + (np.arange(out_w) + 0.5) * display_x
    lat = transform.f - (np.arange(out_h) + 0.5) * display_y
    source_records = [acquired[year][1] for year in YEARS]
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "title": "CONUS November environmental atlas — climate foundation",
        "version": "0.1", "builtAt": now,
        "source": {
            "id": "noaa_nclimgrid_monthly_nidis_cog",
            "title": "NOAA nClimGrid-Monthly, distributed as COGs by NOAA/NIDIS",
            "url": SOURCE_URL, "bucketUrl": BUCKET, "urlTemplate": DATA_TEMPLATE,
            "accessedAt": now,
            "documentationUrls": [SOURCE_URL, "https://www.drought.gov/data-download", "https://www.ncei.noaa.gov/access/metadata/landing-page/bin/iso?id=gov.noaa.ncdc:C00332"],
            "unitsDocumentationUrl": unit_verification["documentationUrl"],
            "unitsVerification": "All four COG bands match 64 original NOAA November 2025 point values each (256 comparisons), within float32 rounding. NOAA's monthly point-file README documents temperatures in °C and precipitation in mm.",
            "datasetCitation": "Vose et al. (2014), NOAA Monthly U.S. Climate Gridded Dataset (NClimGrid), Version 1. Subset: November 2006–2025. NOAA NCEI. doi:10.7289/V5SX6B56. Accessed 2026-11-04.",
            "license": "NOAA public data; this derived overview is not an unaltered NOAA product or a NOAA-endorsed product.",
            "processingStatus": "Retrieved current archive; final/preliminary status is not encoded in these COGs. Future source revisions may change values.",
        },
        "period": {"month": MONTH, "monthName": "November", "startYear": YEARS[0], "endYear": YEARS[-1], "expectedYears": len(YEARS), "completeYears": list(YEARS), "label": "November 2006–2025", "type": "custom 20-year climatology, not an official 30-year climate normal"},
        "resolution": {
            "nativeDegrees": {"x": transform.a, "y": -transform.e},
            "displayDegrees": {"x": display_x, "y": display_y},
            "nativeNominalKm": 5, "displayNominalKm": 9,
            "aggregationFactor": args.factor,
            "description": "Approximately 9 km overview from a nominal 5 km source grid; geographic cell size varies with latitude.",
            "nativeWidth": native_w, "nativeHeight": native_h, "nativeBounds": native_bounds,
        },
        "method": {
            "temporal": "Equal-weight arithmetic mean of 20 individually dated November monthly values. Precipitation inputs are already monthly totals. Temperature inputs are monthly means of daily means, minima, or maxima.",
            "spatial": f"{args.factor}×{args.factor} native-cell blocks, weighted by spherical cell area proportional to sin(north)-sin(south). Available full-baseline native cells only. No interpolation across missing cells; partial coastal and east-edge blocks retain only available contributors.",
            "completeness": "A native cell must have all 20 November values for a full-baseline estimate. Zero is a legitimate value; null indicates no full-baseline value. Source-cell counts expose partial blocks.",
            "interannualStdDev": "Sample standard deviation (n−1 denominator) of the 20 annual November values after the same spatial aggregation. This describes year-to-year variability, not model error, daily extremes, or a confidence interval.",
            "precision": "Values are rounded to 0.01 for file size and inspection. This formatting does not imply 0.01 measurement accuracy.",
        },
        "coverage": {"expectedYears": len(YEARS), "acquiredYears": len(source_records), "gridCells": out_h * out_w, "validGridCells": int((source_cell_count > 0).sum()), "nativeCompleteCells": int(source_cell_count.sum()), "nativeIncompleteCells": native_incomplete, "outsideMask": "Native source nodata is preserved; coastal overview cells may contain fewer than four valid native cells."},
        "limitations": [
            "The mapped variables describe outdoor climatology; they do not measure a tank's cabin temperature, HVAC effectiveness, or crew heat strain.",
            "Monthly temperature summaries cannot establish daily extreme temperatures, freeze–thaw counts, or exposure duration.",
            "Precipitation is not soil moisture, bearing strength, flooding depth, snow depth, or terrain trafficability.",
            "Source grid resolution does not represent local obstacles, buildings, bridge capacity, or road condition.",
            "This layer does not produce vehicle traversal difficulty, route recommendations, or a validated combined environmental score.",
        ],
    }
    output = {
        "schemaVersion": 1, "metadata": metadata, "layers": layers,
        "grid": {"crs": "EPSG:4326", "width": out_w, "height": out_h, "rowOrder": "north-to-south", "columnOrder": "west-to-east", "lat": np.round(lat, 8).tolist(), "lon": np.round(lon, 8).tolist(), "values": grid_values, "validYears": grid_counts, "sourceCellCount": source_cell_count.reshape(-1).tolist(), "interannualStdDev": grid_stddev},
        "annualNationalSummary": {"method": "Area-weighted mean over valid native cells; precipitation is an average depth, not an area-integrated volume.", "values": [annual_summary[year] for year in YEARS]},
    }
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    temporary.replace(args.output)
    data_hash = hashlib.sha256(args.output.read_bytes()).hexdigest()
    manifest = {"schemaVersion": 1, "generatedAt": now, "source": metadata["source"], "inputs": source_records, "output": {"path": args.output.name, "sha256": data_hash, "bytes": args.output.stat().st_size}, "sourceRasterMetadata": original_metadata, "validation": {"fileChecks": file_checks, "years": len(YEARS), "allGridAlignmentsMatch": True, "allTemperatureOrdersValid": True, "precipitationNonnegative": True, "allSerializedValuesFiniteOrNull": True, "sourceNativeCellCount": int(source_cell_count.sum()), "incompleteNativeCellCounts": native_incomplete, "unitsReference": unit_verification}}
    args.output.with_name("climate_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size, "sha256": data_hash, "coverage": metadata["coverage"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
