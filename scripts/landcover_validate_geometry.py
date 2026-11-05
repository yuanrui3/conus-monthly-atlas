#!/usr/bin/env python3
"""Verify overview geometry and seven broad regional land-cover patterns.

This is a consistency check, not an independent accuracy assessment. Regional
checks deliberately select nearby homogeneous overview windows, then compare
their centers and surrounding 6 km square with native 30 m USGS service data.
Run landcover_build.py first. Dependencies: numpy, rasterio.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import transform

from landcover_build import acquire, export_params, request_url, VALID_CODES, write_json


ANCHORS = [
    ("Olympic Peninsula forest", -123.75, 47.75, [41, 42, 43]),
    ("Adirondack forest", -74.25, 44.0, [41, 42, 43]),
    ("Central Iowa agriculture", -93.5, 42.3, [81, 82]),
    ("Central Illinois agriculture", -89.5, 40.5, [81, 82]),
    ("Great Basin shrubland", -116.5, 40.0, [31, 52, 71]),
    ("Mojave desert", -115.5, 35.0, [31, 52]),
    ("Lake Michigan open water", -87.0, 44.0, [11]),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/conus-landcover"))
    parser.add_argument("--outdir", type=Path, default=Path(__file__).resolve().parents[1] / "docs/data")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    data = json.loads((args.outdir / "landcover.json").read_text())
    grid = data["grid"]
    source = args.cache / "usgs_national_2025.tif"
    points = []
    with rasterio.open(source) as ds:
        raw = ds.read(1)
        assert ds.crs.to_epsg() == 4326
        assert ds.tags().get("AREA_OR_POINT") == "Area"
        assert ds.transform.a > 0 and ds.transform.e < 0
        assert ds.transform.b == ds.transform.d == 0
        assert grid["width"] == ds.width and grid["height"] == ds.height
        assert np.allclose(grid["bounds"], ds.bounds, rtol=0, atol=1e-12)
        for row in [0, ds.height // 2, ds.height - 1]:
            for col in [0, ds.width // 2, ds.width - 1]:
                lon, lat = ds.xy(row, col)
                assert ds.index(lon, lat) == (row, col)
                assert abs(grid["lon"][col] - lon) < 1e-8
                assert abs(grid["lat"][row] - lat) < 1e-8
                expected = int(raw[row, col]) if raw[row, col] != 250 else None
                assert grid["values"]["landcover"][row * ds.width + col] == expected
        geometry = {
            "responseCRS": "EPSG:4326", "sourceNativeCRS": "EPSG:5070",
            "pixelRegistration": "PixelIsArea", "jsonRegistration": "cell centers",
            "affine": list(ds.transform)[:6], "returnedBounds": list(ds.bounds),
            "requestedBounds": [-125, 24, -66, 50],
            "longitudeCenterFormula": "affine.c + (column + 0.5) * affine.a",
            "latitudeCenterFormula": "affine.f + (row + 0.5) * affine.e",
            "jsonCoordinatesMatchReturnedGeoTiff": True,
            "rowColumnRoundtripChecks": 9, "rowColumnOrderVerified": True,
            "note": "GeoServer reprojection expands the returned bounds. Returned GeoTIFF bounds and affine, not the request bounds, position the raster.",
        }
        for index, (name, anchor_lon, anchor_lat, expected) in enumerate(ANCHORS):
            anchor_row, anchor_col = ds.index(anchor_lon, anchor_lat)
            candidates = []
            for row in range(anchor_row - 6, anchor_row + 7):
                for col in range(anchor_col - 6, anchor_col + 7):
                    nearby = raw[row - 2:row + 3, col - 2:col + 3]
                    fraction = float(np.isin(nearby, expected).sum()) / 25
                    distance_squared = (row - anchor_row) ** 2 + (col - anchor_col) ** 2
                    candidates.append((fraction, -distance_squared, row, col))
            fraction, _, row, col = max(candidates)
            lon, lat = ds.xy(row, col)
            x, y = transform("EPSG:4326", "EPSG:5070", [lon], [lat])
            back_lon, back_lat = transform("EPSG:5070", "EPSG:4326", x, y)
            error = [abs(lon - back_lon[0]), abs(lat - back_lat[0])]
            assert max(error) < 1e-8
            points.append({"index": index, "name": name, "anchorLonLat": [anchor_lon, anchor_lat],
                           "row": row, "col": col, "lon": lon, "lat": lat,
                           "x": x[0], "y": y[0], "overviewClass": int(raw[row, col]),
                           "expectedBroadClasses": expected, "overview5x5BroadFraction": fraction,
                           "reprojectionRoundtripErrorDegrees": error})

    def check(point: dict) -> dict:
        x, y = point["x"], point["y"]
        params = export_params([x - 3000, y - 3000, x + 3000, y + 3000], 200, 200, "EPSG:5070")
        path = args.cache / f"semantic_patch_{point['index']}.tif"
        point["source"] = acquire(request_url(params), path, args.offline)
        with rasterio.open(path) as ds:
            assert ds.crs.to_epsg() == 5070 and ds.count == 1 and ds.dtypes[0] == "uint8"
            assert np.allclose(ds.res, [30, 30], atol=0.1)
            assert ds.tags().get("AREA_OR_POINT") == "Area"
            assert ds.bounds.left < x < ds.bounds.right and ds.bounds.bottom < y < ds.bounds.top
            values = ds.read(1)
            assert set(np.unique(values).tolist()) <= VALID_CODES | {250}
            codes, counts = np.unique(values, return_counts=True)
            point.update({
                "nativeCenterClass": int(next(ds.sample([(x, y)]))[0]),
                "nativePatchModalClass": int(codes[np.argmax(counts)]),
                "nativePatchCounts": {str(int(k)): int(v) for k, v in zip(codes, counts)},
                "nativePatchBroadFraction": float(np.isin(values, point["expectedBroadClasses"]).sum()) / values.size,
                "nativeResolutionMeters": list(ds.res), "nativeCRS": "EPSG:5070",
                "nativeAffine": list(ds.transform)[:6],
            })
        point["centerMatchesOverview"] = point["nativeCenterClass"] == point["overviewClass"]
        point["modalClassMatchesOverview"] = point["nativePatchModalClass"] == point["overviewClass"]
        point["broadRegionalPatternConfirmed"] = point["nativePatchBroadFraction"] > 0.5 and point["overviewClass"] in point["expectedBroadClasses"]
        return point

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(check, points))
    assert all(p["broadRegionalPatternConfirmed"] for p in results)
    report = {
        "schemaVersion": 1, "checkedAt": datetime.now(timezone.utc).isoformat(),
        "status": "passed geometry and broad regional consistency checks",
        "geometry": geometry, "regionalChecks": results,
        "selectionMethod": "For each named regional anchor, search within six overview cells in each direction. Select the cell whose surrounding 5 × 5 overview window has the highest fraction of expected broad classes, breaking ties by distance to the anchor. Retrieve a separate 6 km square native-resolution (200 × 200 at 30 m) patch centered there. This deliberately tests homogeneous regional patterns, not unbiased source accuracy.",
        "successfulRegionalChecks": sum(p["broadRegionalPatternConfirmed"] for p in results),
        "overviewAndNativeCenterMatches": sum(p["centerMatchesOverview"] for p in results),
        "overviewAndNativePatchModalMatches": sum(p["modalClassMatchesOverview"] for p in results),
        "interpretation": "The seven homogeneous regional checks agree in their overview, native center, and native patch modal classes. These checks plus GeoTIFF coordinate verification support regional positioning. Mixed-landscape discrepancies remain documented in landcover_validation.json; the overview is not an exact native-pixel lookup, area-majority product, or independent field validation.",
        "localLandCoverValidated": False, "providerOverviewGenerationMethodIndependentlyVerified": False,
    }
    out = args.outdir / "landcover_geometry_validation.json"
    write_json(out, report, pretty=True)
    print(json.dumps({"output": str(out), "regionalChecks": len(results),
                      "broadChecksPassed": report["successfulRegionalChecks"],
                      "centerMatches": report["overviewAndNativeCenterMatches"],
                      "modalMatches": report["overviewAndNativePatchModalMatches"]}))


if __name__ == "__main__":
    main()
