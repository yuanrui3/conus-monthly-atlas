#!/usr/bin/env python3
"""Build a dated, broad elevation context layer from public NOAA ETOPO1.

Install: python -m pip install numpy shapely
Run after context_boundaries.py. This is systematic sampling of the native
grid, not an area average and not a local terrain slope measurement.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.parse
import urllib.request

import numpy as np
from shapely import contains_xy, unary_union
from shapely.geometry import shape


QUERY = "altitude[(24):6:(50)][(-125):6:(-66)]"
URL = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180.csv?" + urllib.parse.quote(QUERY, safe=":,")
SOURCE_PAGE = "https://coastwatch.pfeg.noaa.gov/erddap/info/etopo180/index.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/november-context"))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "docs/data/elevation.json")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    raw_path = args.cache / "etopo1_stride6.csv"
    if not raw_path.exists():
        request = urllib.request.Request(URL, headers={"User-Agent": "CONUS-November-Atlas/0.1 (public-data acquisition)"})
        with urllib.request.urlopen(request, timeout=90) as response:
            raw_path.write_bytes(response.read())
    raw = raw_path.read_bytes()
    records = csv.reader(io.StringIO(raw.decode()))
    assert next(records) == ["latitude", "longitude", "altitude"]
    assert next(records) == ["degrees_north", "degrees_east", "m"]
    samples = np.asarray([[float(v) for v in row] for row in records], dtype=float)
    lon = np.unique(samples[:, 1])
    lat_asc = np.unique(samples[:, 0])
    width, height = len(lon), len(lat_asc)
    assert (height, width) == (261, 591)
    assert len(samples) == height * width
    assert np.allclose(np.diff(lat_asc), 0.1) and np.allclose(np.diff(lon), 0.1)
    assert np.allclose(samples[:, 0].reshape(height, width), lat_asc[:, None])
    assert np.allclose(samples[:, 1].reshape(height, width), lon[None, :])
    values = samples[:, 2].reshape(height, width)[::-1].copy()
    lat = lat_asc[::-1]
    boundaries_path = args.output.parent / "states.geojson"
    boundaries = json.loads(boundaries_path.read_text())
    assert len(boundaries["features"]) == 49
    land_outline = unary_union([shape(feature["geometry"]) for feature in boundaries["features"]])
    xx, yy = np.meshgrid(lon, lat)
    in_scope = contains_xy(land_outline, xx, yy)
    values[(values == 32767) | ~in_scope] = np.nan
    finite = np.isfinite(values)
    assert finite.sum() > 70000
    assert np.nanmax(values) < 5000 and np.nanmax(values) > 3000
    # Preserve below-sea-level values; zero is a real elevation, not missing.
    flattened = [int(v) if np.isfinite(v) else None for v in values.ravel()]
    retrieved = datetime.now(timezone.utc).isoformat()
    output = {
        "schemaVersion": 1,
        "source": {
            "id": "noaa-etopo1",
            "title": "NOAA ETOPO1 global relief model",
            "institution": "NOAA National Geophysical Data Center",
            "url": SOURCE_PAGE,
            "downloadUrl": URL,
            "accessedAt": retrieved,
            "vintage": 2009,
            "citation": "Amante, C. and B. W. Eakins (2009), ETOPO1 1 Arc-Minute Global Relief Model: Procedures, Data Sources and Analysis. NOAA Technical Memorandum NESDIS NGDC-24.",
            "documentationUrl": "https://www.ngdc.noaa.gov/mgg/global/relief/ETOPO1/docs/ETOPO1.pdf",
            "license": "Free use and redistribution; NOAA source terms apply.",
            "rawSHA256": hashlib.sha256(raw).hexdigest(),
        },
        "baseline": None,
        "grid": {
            "crs": "EPSG:4326",
            "verticalDatum": "Mean sea level",
            "width": width,
            "height": height,
            "lon": [round(float(v), 6) for v in lon],
            "lat": [round(float(v), 6) for v in lat],
            "nativeResolutionDegrees": 1 / 60,
            "displayResolutionDegrees": 0.1,
            "displayResolutionKmApprox": 11,
            "registration": "Grid-node samples displayed at their coordinates; row-major, north to south then west to east.",
            "method": "Select every sixth ETOPO1 grid point (0.1 degree spacing). No averaging or interpolation. Mask grid centers outside the Census 2025 generalized CONUS outlines.",
            "scopeMaskSource": boundaries["metadata"]["url"],
        },
        "variables": {
            "elevation": {
                "label": "Elevation context",
                "unit": "m",
                "values": flattened,
                "validCells": int(finite.sum()),
                "min": int(np.nanmin(values)),
                "max": int(np.nanmax(values)),
                "description": "Static relief from the 2009 ETOPO1 model, sampled at 0.1 degree spacing. These are broad context values, not a November average.",
                "aggregation": "Systematic spatial sampling; no temporal average.",
                "limitations": "Coarse relief cannot resolve local slope, surface roughness, obstacles, or traversal. Source includes bathymetry; generalized boundary masking can retain coastal or lake-edge samples. Negative values are preserved, not treated as missing.",
            }
        },
        "validation": {
            "sourceRows": int(len(samples)),
            "mappedGridCenters": int(finite.sum()),
            "missingOrOutOfScopeGridCenters": int((~finite).sum()),
            "coordinateOrderChecked": True,
            "regularSpacingChecked": True,
            "sourceUnitsChecked": True,
            "maskFeatureCount": 49,
            "maskDescription": "Generalized national cartographic outline, not an exact land/water classification.",
        },
    }
    args.output.write_text(json.dumps(output, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "bytes": args.output.stat().st_size, "width": width, "height": height,
                      "validCells": int(finite.sum()), "range": [int(np.nanmin(values)), int(np.nanmax(values))]}))


if __name__ == "__main__":
    main()
