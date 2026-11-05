#!/usr/bin/env python3
"""Build a source-backed 2025 CONUS land-cover overview, without mobility scores.

Dependencies: numpy, rasterio. Run after context_boundaries.py.
The USGS WCS returns raw categorical values, not an RGB map. Its coarse output
is retained as a provider overview: neither 30 m point samples nor area-majority
classes are claimed. Every output coordinate comes from the returned GeoTIFF.

Example:
  python scripts/landcover_build.py --cache /tmp/conus-landcover
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.warp import transform


BASE = "https://dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data"
COVERAGE = "Land-Cover-Native_conus_year_data"
SOURCE_YEAR = 2025
TIME = "2025-01-01T00:00:00.000Z"
SOURCE_PAGE = "https://www.usgs.gov/data/annual-national-land-cover-database-nlcd-collection-1-products-ver-12-june-2026"
CLASS_PAGE = "https://www.mrlc.gov/data/type/land-cover"
METHOD_PAGE = "https://www.usgs.gov/centers/eros/science/annual-nlcd-land-cover-classification"
SERVICES_PAGE = "https://www.mrlc.gov/data-services-page"

# Official class codes and RGB palette. Class descriptions are concise summaries.
CLASS_DEFINITIONS = [
    (11, "Open water", "water", "Open-water land cover; no depth, current, seasonal stage, or drinking-water quality is inferred."),
    (12, "Perennial ice/snow", "snow_ice", "Persistent ice/snow land cover; this is not November snowfall or seasonal snow depth."),
    (21, "Developed, open space", "developed", "Mostly vegetation within developed settings; no individual building or road geometry."),
    (22, "Developed, low intensity", "developed", "A mixture of development and vegetation; no individual building or road geometry."),
    (23, "Developed, medium intensity", "developed", "A greater proportion of developed surface; no individual building or road geometry."),
    (24, "Developed, high intensity", "developed", "Predominantly developed surface; no individual building or road geometry."),
    (31, "Barren land (rock/sand/clay)", "barren", "Sparse vegetation over exposed rock or other earth materials; no soil-bearing strength is inferred."),
    (41, "Deciduous forest", "forest", "Forest dominated by seasonally leaf-shedding trees; trunk spacing and understory are not measured here."),
    (42, "Evergreen forest", "forest", "Forest dominated by evergreen trees; trunk spacing and understory are not measured here."),
    (43, "Mixed forest", "forest", "Forest containing both deciduous and evergreen trees; trunk spacing and understory are not measured here."),
    (52, "Shrub/scrub", "shrub", "Shrub vegetation, including some young or stunted trees; local stem density is unknown."),
    (71, "Grassland/herbaceous", "grassland", "Predominantly grasses and other non-woody vegetation; November height and ground condition are unknown."),
    (81, "Pasture/hay", "agriculture", "Managed forage vegetation; harvest, mowing, grazing, and November surface condition are unknown."),
    (82, "Cultivated crops", "agriculture", "Cultivated land, including some orchards and vineyards; November harvest and tillage status are unknown."),
    (90, "Woody wetlands", "wetland", "Woody vegetation associated with periodic saturation or inundation; current wetness and depth are unknown."),
    (95, "Emergent herbaceous wetlands", "wetland", "Non-woody wetland vegetation associated with periodic saturation or inundation; current wetness and depth are unknown."),
]
VALID_CODES = {row[0] for row in CLASS_DEFINITIONS}


def request_url(params: dict) -> str:
    return BASE + "/wcs?" + urllib.parse.urlencode(params, doseq=True)


def export_params(bbox: list[float], width: int, height: int, crs: str) -> dict:
    return {
        "service": "WCS", "version": "1.0.0", "request": "GetCoverage",
        "coverage": COVERAGE, "crs": crs, "response_crs": crs,
        "bbox": ",".join(str(v) for v in bbox), "width": width, "height": height,
        "format": "GeoTIFF", "time": TIME, "interpolation": "nearest neighbor",
    }


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def acquire(url: str, path: Path, offline: bool) -> dict:
    if not path.exists():
        if offline:
            raise RuntimeError(f"Offline input missing: {path}")
        req = urllib.request.Request(url, headers={"User-Agent": "CONUS-November-Atlas/0.3 public-data acquisition"})
        with urllib.request.urlopen(req, timeout=100) as response:
            raw = response.read()
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(raw)
        tmp.replace(path)
    return {
        "url": url, "cacheFile": path.name, "bytes": path.stat().st_size,
        "sha256": digest(path),
        "cachedAt": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
    }


def write_json(path: Path, obj: object, pretty: bool = False) -> None:
    text = json.dumps(obj, ensure_ascii=False, indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"), allow_nan=False) + "\n"
    path.write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/conus-landcover"))
    parser.add_argument("--outdir", type=Path, default=Path(__file__).resolve().parents[1] / "docs/data")
    parser.add_argument("--offline", action="store_true", help="Rebuild only from previously acquired raw inputs.")
    parser.add_argument("--skip-native-checks", action="store_true", help="Skip optional resolution diagnostics, not core validity checks.")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    args.outdir.mkdir(parents=True, exist_ok=True)
    cap_url = request_url({"service": "WCS", "version": "2.0.1", "request": "GetCapabilities"})
    describe_url = request_url({"service": "WCS", "version": "2.0.1", "request": "DescribeCoverage",
                                "coverageId": "mrlc_Land-Cover-Native_conus_year_data__" + COVERAGE})
    export_url = request_url(export_params([-125, 24, -66, 50], 1180, 520, "EPSG:4326"))
    inputs = []
    for name, url in [("usgs_wcs_cap.xml", cap_url), ("usgs_describe.xml", describe_url),
                      ("usgs_national_2025.tif", export_url)]:
        inputs.append(acquire(url, args.cache / name, args.offline))
    described = ET.fromstring((args.cache / "usgs_describe.xml").read_bytes())
    time_values = [n.text for n in described.iter() if n.tag.endswith("timePosition")]
    assert TIME in time_values, "The provider does not advertise the pinned source year."
    offset_vectors = [n.text for n in described.iter() if n.tag.endswith("offsetVector")]
    assert len(offset_vectors) == 2
    native_steps = [[float(v) for v in item.split()] for item in offset_vectors]
    assert np.allclose(native_steps, [[30, 0], [0, -30]], atol=0.001)

    raster_path = args.cache / "usgs_national_2025.tif"
    with rasterio.open(raster_path) as ds:
        assert ds.count == 1 and ds.dtypes[0] == "uint8", "Raw categorical one-band raster required."
        assert ds.crs.to_epsg() == 4326
        assert ds.nodata == 250
        raw = ds.read(1)
        height, width = raw.shape
        assert (width, height) == (1180, 520)
        assert set(np.unique(raw).tolist()) <= VALID_CODES | {250}
        affine = ds.transform
        assert affine.a > 0 and affine.e < 0 and affine.b == affine.d == 0
        lon = affine.c + (np.arange(width) + 0.5) * affine.a
        lat = affine.f + (np.arange(height) + 0.5) * affine.e
        bounds = list(ds.bounds)
        palette = ds.colormap(1)
        assert all(code in palette for code in VALID_CODES)

    boundary_path = args.outdir / "states.geojson"
    boundary = json.loads(boundary_path.read_text())
    assert len(boundary["features"]) == 49
    in_scope = geometry_mask([f["geometry"] for f in boundary["features"]],
                             out_shape=raw.shape, transform=affine, invert=True)
    # NLCD is already a CONUS product. Census cartographic land outlines would
    # remove genuine mapped water, including much of the Great Lakes, so retain
    # the source footprint and use the outline only as a validation reference.
    valid = raw != 250
    assert valid.sum() > 200000
    values = [int(v) if ok else None for v, ok in zip(raw.ravel(), valid.ravel())]
    counts = Counter(v for v in values if v is not None)
    assert set(counts) == VALID_CODES, "Expected all sixteen CONUS classes in the national overview."

    # These checks demonstrate the distinction between provider overviews and
    # individual native pixels. A mismatch is reported, never suppressed or
    # treated as evidence that one source class is an area-wide fact.
    checks = []
    if not args.skip_native_checks:
        points = []
        for code in [41, 42, 52, 71, 82, 90, 95]:
            candidates = np.argwhere(raw == code)
            row, col = candidates[len(candidates) // 2]
            x, y = transform("EPSG:4326", "EPSG:5070", [float(lon[col])], [float(lat[row])])
            points.append((code, int(row), int(col), x[0], y[0]))

        def native_check(point: tuple) -> dict:
            code, row, col, x, y = point
            params = export_params([x - 45, y - 45, x + 45, y + 45], 3, 3, "EPSG:5070")
            path = args.cache / f"check_native_{code}.tif"
            record = {"overviewClass": code, "row": row, "col": col,
                      "lon": float(lon[col]), "lat": float(lat[row])}
            try:
                source = acquire(request_url(params), path, args.offline)
                with rasterio.open(path) as ds:
                    assert ds.count == 1 and ds.crs.to_epsg() == 5070
                    assert np.allclose(ds.res, [30, 30], atol=0.1)
                    assert ds.bounds.left <= x <= ds.bounds.right and ds.bounds.bottom <= y <= ds.bounds.top
                    code_at_center = int(next(ds.sample([(x, y)]))[0])
                    assert code_at_center in VALID_CODES | {250}
                    record.update({"nativeClass": code_at_center, "nativeResolutionMeters": list(ds.res),
                                   "matchesOverview": code_at_center == code, "source": source})
            except Exception as exc:
                record["error"] = str(exc)
            return record

        with ThreadPoolExecutor(max_workers=3) as pool:
            checks = list(pool.map(native_check, points))

    now = datetime.now(timezone.utc).isoformat()
    classes = [{"value": code, "label": label, "color": "#" + "".join(f"{v:02x}" for v in palette[code][:3]),
                "group": group, "description": description, "overviewSampleCount": counts[code]}
               for code, label, group, description in CLASS_DEFINITIONS]
    limitations = [
        "Calendar-year 2025 land cover is separate from the November 2006–2025 climate baseline; it is not a November vegetation or harvest observation.",
        "The underlying NLCD source has 30 m cells. This downloadable display layer is a much coarser categorical service overview, with approximately 4–7 km spacing across CONUS.",
        "Nearest-neighbor interpolation was requested. The provider may use internal raster overviews whose generation method was not independently verified; output classes are neither validated native-pixel point samples nor area-majority classes.",
        "A class shown at an overview cell does not establish the class at every location within that cell. Narrow wetlands, wooded strips, small water bodies, and mixed landscapes can be omitted or generalized.",
        "Land-cover classes do not measure tree spacing, understory density, vegetation height at a specific date, soil strength, surface-water depth, or current wetness.",
        "Wetland classes indicate vegetation associated with periodic saturation or inundation, not observed water level. Open water carries no depth, crossing, bridge, or drinking-water-quality conclusion.",
        "Developed classes are retained as source land-cover categories; individual road and building layers are excluded.",
        "The valid USGS CONUS source footprint is preserved, including mapped inland and coastal water beyond generalized Census land outlines. Neither outline is an exact administrative or shoreline boundary. Null cells remain source NoData; they are not favorable conditions.",
        "Sample counts are overview grid counts, not estimates of national land-cover area. The geographic grid is not equal-area.",
    ]
    method = ("Request 2025 raw class-valued GeoTIFF from the official USGS MRLC WCS at 1180 × 520 pixels with nearest-neighbor interpolation. "
              "Use the returned affine coordinates, not the requested bounding box, because server reprojection expands the extent. "
              "Read integer band values directly, retain provider palette labels, and convert NoData 250 to null. Preserve the valid USGS CONUS footprint including inland and coastal water; use 2025 Census outlines as reference only. "
              "No color decoding, class averaging, gap filling, area-majority inference, or mobility scoring.")
    data = {
        "schemaVersion": 1,
        "metadata": {
            "id": "usgs-annual-nlcd-2025-overview", "title": "Land cover and wetlands",
            "source": "USGS Annual NLCD Collection 1.2 · MRLC raw WCS", "sourceUrl": SOURCE_PAGE,
            "sourceYear": SOURCE_YEAR, "snapshot": "2025 calendar-year land cover (Collection 1.2, June 2026)",
            "sourceRelease": "Collection 1.2, June 2026", "sourceDoi": "https://doi.org/10.5066/P94UXNTS",
            "nativeResolution": "30 m source cells", "nativeResolutionMeters": 30,
            "displaySupport": "Coarse categorical service overview; approximately 4–7 km spacing; local composition unknown",
            "overviewLabel": "2025 land cover · coarse service overview",
            "method": method, "limitations": limitations, "generatedAt": now,
            "sourceRetrievedAt": inputs[2]["cachedAt"], "license": "USGS data release: CC0 1.0 Universal",
            "classDocumentationUrl": CLASS_PAGE, "methodDocumentationUrl": METHOD_PAGE,
            "serviceDocumentationUrl": SERVICES_PAGE, "requestUrl": export_url,
            "mappedCells": int(valid.sum()), "missingWithinGeneralizedLandOutlineCells": int(np.sum(in_scope & (raw == 250))),
            "sourceValidOutsideGeneralizedLandOutlineCells": int(np.sum((raw != 250) & ~in_scope)),
            "overviewCountMeaning": "Counts of coarse geographic-grid cells, not land-area percentages.",
        },
        "classes": classes,
        "grid": {
            "crs": "EPSG:4326", "width": width, "height": height,
            "rowOrder": "north-to-south", "columnOrder": "west-to-east",
            "lon": [round(float(v), 9) for v in lon], "lat": [round(float(v), 9) for v in lat],
            "spacingDegrees": {"longitude": affine.a, "latitude": -affine.e},
            "bounds": bounds, "affine": list(affine)[:6], "registration": "Returned GeoTIFF cell centers",
            "support": "Provider overview classes; not per-cell majority or exact native-pixel samples",
            "scope": "Valid USGS CONUS source footprint; source NoData preserved",
            "outlineReferenceSource": boundary["metadata"]["url"],
            "values": {"landcover": values},
        },
    }
    out = args.outdir / "landcover.json"
    write_json(out, data)
    validation = {
        "schemaVersion": 1, "checkedAt": now, "status": "passed with explicit overview-resolution limitations",
        "sourceIsRawOneBandCategorical": True, "sourceNoData": 250, "expectedClassCodes": sorted(VALID_CODES),
        "observedClassCodes": sorted(counts), "allValuesRecognized": True, "valueCount": len(values),
        "expectedValueCount": width * height, "coordinateOrderChecked": True,
        "coordinatesFromReturnedGeoTiff": True, "paletteReadDirectly": True, "colorDecodingUsed": False,
        "providerAdvertises2025": True, "sourceNative30mVerifiedFromDescribeCoverage": True,
        "mappedCells": int(valid.sum()), "referenceOutlineCells": int(in_scope.sum()),
        "noDataWithinReferenceOutlineCells": int(np.sum(in_scope & (raw == 250))),
        "sourceValidOutsideGeneralizedLandOutline": int(np.sum((raw != 250) & ~in_scope)),
        "missingOrOutOfScopeCells": int((~valid).sum()), "classOverviewCounts": dict(sorted(counts.items())),
        "referenceOutlineFeatures": len(boundary["features"]), "referenceOutlineAppliedAsMask": False,
        "nativeResolutionDiagnostics": checks,
        "nativeDiagnosticMeaning": "Checks compare selected coarse overview cell centers to separate 30 m service requests. Differences demonstrate that local native-pixel classes cannot be assumed from this overview. These are not independent field validation or source-accuracy estimates.",
        "localLandCoverValidated": False, "areaMajorityValidated": False, "mobilityModelIncluded": False,
    }
    write_json(args.outdir / "landcover_validation.json", validation, pretty=True)
    manifest = {
        "schemaVersion": 1, "generatedAt": now, "sourceYear": SOURCE_YEAR,
        "dataRelease": SOURCE_PAGE, "classDocumentation": CLASS_PAGE, "servicesDocumentation": SERVICES_PAGE,
        "requestParameters": export_params([-125, 24, -66, 50], width, height, "EPSG:4326"),
        "inputs": inputs, "outlineReference": {"file": "states.geojson", "sha256": digest(boundary_path), "appliedAsMask": False, "metadata": boundary["metadata"]},
        "output": {"file": out.name, "bytes": out.stat().st_size, "sha256": digest(out)},
        "method": method, "limitations": limitations,
    }
    write_json(args.outdir / "landcover_manifest.json", manifest, pretty=True)
    print(json.dumps({"output": str(out), "bytes": out.stat().st_size, "width": width, "height": height,
                      "mappedCells": int(valid.sum()), "classes": len(counts), "nativeChecks": checks}, separators=(",", ":")))


if __name__ == "__main__":
    main()
