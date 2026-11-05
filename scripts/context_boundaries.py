#!/usr/bin/env python3
"""Acquire the public Census 2025 generalized CONUS state outlines.

Install: python -m pip install pyshp pyproj
Run: python scripts/context_boundaries.py --cache /tmp/november-context

The 1:20,000,000 outlines are cartographic context, not surveyed coastlines,
land/water masks, or a statement about access or traversal conditions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

import shapefile
from pyproj import CRS, Transformer


URL = "https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_state_20m.zip"
EXPECTED_CODES = set("AL AZ AR CA CO CT DE DC FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/november-context"))
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1] / "docs/data/states.geojson")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    archive_path = args.cache / "states.zip"
    if not archive_path.exists():
        request = urllib.request.Request(URL, headers={"User-Agent": "CONUS-November-Atlas/0.1 (public-data acquisition)"})
        with urllib.request.urlopen(request, timeout=60) as response:
            archive_path.write_bytes(response.read())
    raw = archive_path.read_bytes()
    archive = zipfile.ZipFile(io.BytesIO(raw))
    prefix = "cb_2025_us_state_20m"
    reader = shapefile.Reader(
        shp=io.BytesIO(archive.read(prefix + ".shp")),
        shx=io.BytesIO(archive.read(prefix + ".shx")),
        dbf=io.BytesIO(archive.read(prefix + ".dbf")),
    )
    source_crs = CRS.from_wkt(archive.read(prefix + ".prj").decode())
    transformer = Transformer.from_crs(source_crs, CRS.from_epsg(4326), always_xy=True)

    def convert(coordinates):
        if isinstance(coordinates[0], (int, float)):
            x, y = transformer.transform(*coordinates[:2])
            assert -125.0 <= x <= -66.0 and 24.0 <= y <= 50.0, (x, y)
            return [round(x, 6), round(y, 6)]
        return [convert(child) for child in coordinates]

    features = []
    for record in reader.iterShapeRecords():
        attributes = record.record.as_dict()
        if attributes["STUSPS"] not in EXPECTED_CODES:
            continue
        geometry = record.shape.__geo_interface__
        features.append({
            "type": "Feature",
            "id": attributes["GEOID"],
            "properties": {
                "name": attributes["NAME"],
                "STUSPS": attributes["STUSPS"],
                "GEOID": attributes["GEOID"],
            },
            "geometry": {"type": geometry["type"], "coordinates": convert(geometry["coordinates"])},
        })
    features.sort(key=lambda feature: feature["properties"]["GEOID"])
    assert len(features) == 49
    assert {feature["properties"]["STUSPS"] for feature in features} == EXPECTED_CODES
    result = {
        "type": "FeatureCollection",
        "name": "Contiguous US states and District of Columbia",
        "metadata": {
            "source": "US Census Bureau, 2025 Cartographic Boundary Files",
            "url": URL,
            "vintage": 2025,
            "scale": "1:20,000,000",
            "sourceCRS": "EPSG:4269 (NAD83)",
            "outputCRS": "EPSG:4326 (WGS 84 longitude/latitude)",
            "coordinateProcessing": "Transformed with pyproj/PROJ, then rounded to 6 decimal places. No additional simplification.",
            "retrievedAt": datetime.now(timezone.utc).isoformat(),
            "archiveSHA256": hashlib.sha256(raw).hexdigest(),
            "scope": "48 contiguous states plus District of Columbia",
            "limitations": "Generalized map outlines only; unsuitable as detailed shoreline, waterbody, or parcel boundaries.",
        },
        "features": features,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "features": len(features), "bytes": args.output.stat().st_size,
                      "archiveSHA256": result["metadata"]["archiveSHA256"]}))


if __name__ == "__main__":
    main()
