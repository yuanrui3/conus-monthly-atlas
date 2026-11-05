#!/usr/bin/env python3
"""Build a small, public-domain river/lake context overlay from Natural Earth.

This is 1:10,000,000-scale cartography, not measured seasonal water conditions.
Source ZIPs and HTTP metadata are cached outside the repository.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import urllib.request
import zipfile

import shapefile
import shapely
from shapely.geometry import MultiLineString, MultiPolygon, box, mapping, shape
from shapely.geometry.polygon import orient


EXTENT = [-125, 24, -66, 50]
VERSION = "5.0.0"
RIVER_PAGE = "https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-rivers-lake-centerlines/"
LAKE_PAGE = "https://www.naturalearthdata.com/downloads/10m-physical-vectors/10m-lakes/"
TERMS_PAGE = "https://www.naturalearthdata.com/about/terms-of-use/"
SOURCE_LAYERS = [
    ("ne_10m_lakes", "lake", "0803a06f9c3cb4671d89b68c48b142aad9366ba40f665245e12a913fbc61722a"),
    ("ne_10m_lakes_north_america", "lake", "96c824a2f2646ea8b16fe6711f7906ba690788a547f51e391654c8e94271ffba"),
    ("ne_10m_rivers_lake_centerlines", "river", "ded71b01870855ccfe19b51f2ec14c9bb48fae23c0e9f3c11974d426433b5c38"),
    ("ne_10m_rivers_north_america", "river", "7fbe85a2acbf1f3ef4361a16bb39677ad1ea86f888be1689f7a4caeafc7529e8"),
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(layer: str, cache: Path, expected_hash: str):
    url = f"https://naturalearth.s3.amazonaws.com/10m_physical/{layer}.zip"
    path = cache / f"{layer}.zip"
    metadata_path = cache / f"{layer}.http.json"
    if not path.exists():
        with urllib.request.urlopen(urllib.request.Request(url, headers={
            "User-Agent": "CONUS-November-Environmental-Atlas/1.0"
        }), timeout=90) as response:
            data = response.read()
            if response.headers.get("Content-Length"):
                assert len(data) == int(response.headers["Content-Length"])
            metadata = {
                "url": url, "retrievedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                "lastModified": response.headers.get("Last-Modified"), "etag": response.headers.get("ETag"),
            }
        path.write_bytes(data)
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    else:
        data = path.read_bytes()
        metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {"url": url}
    actual_hash = digest(data)
    if actual_hash != expected_hash:
        raise ValueError(f"Source archive changed; review before publishing: {layer}")
    return path, {**metadata, "bytes": len(data), "sha256": actual_hash}


def rounded_coordinates(value):
    if isinstance(value, (float, int)):
        assert math.isfinite(value)
        return round(value, 6)
    return [rounded_coordinates(child) for child in value]


def coordinate_pairs(value):
    if isinstance(value[0], (int, float)):
        yield value
    else:
        for child in value:
            yield from coordinate_pairs(child)


def keep_geometry_type(geometry, kind):
    accepted = ("Polygon", "MultiPolygon") if kind == "lake" else ("LineString", "MultiLineString")
    if geometry.geom_type in accepted:
        return geometry
    if geometry.geom_type == "GeometryCollection":
        parts = []
        for child in geometry.geoms:
            child = keep_geometry_type(child, kind)
            if child is None or child.is_empty:
                continue
            parts.extend(child.geoms if child.geom_type.startswith("Multi") else [child])
        if parts:
            return MultiPolygon(parts) if kind == "lake" else MultiLineString(parts)
    return None


def source_id(value, row_number):
    if value is None or value == "":
        return f"source-record-{row_number}"
    if isinstance(value, (int, float)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def atomic_json(path: Path, value: dict, pretty=False):
    content = json.dumps(value, ensure_ascii=False, allow_nan=False,
                         indent=2 if pretty else None,
                         separators=None if pretty else (",", ":")).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(content)
    temporary.replace(path)
    return {"file": path.name, "bytes": len(content), "sha256": digest(content)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("docs/data"))
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    clip = box(*EXTENT)
    features = []
    sources = []
    excluded = []
    precision_fallbacks = []
    source_id_counts = collections.Counter()
    vertices = 0
    for layer, kind, expected_hash in SOURCE_LAYERS:
        path, source = fetch(layer, args.cache_dir, expected_hash)
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            version = archive.read(f"{layer}.VERSION.txt").decode().strip()
            projection = archive.read(f"{layer}.prj").decode()
            assert version == VERSION
            assert 'GCS_WGS_1984' in projection
            reader = shapefile.Reader(
                shp=io.BytesIO(archive.read(f"{layer}.shp")),
                shx=io.BytesIO(archive.read(f"{layer}.shx")),
                dbf=io.BytesIO(archive.read(f"{layer}.dbf")), encoding="utf-8",
            )
            stats = collections.Counter()
            class_counts = collections.Counter()
            retained_classes = collections.Counter()
            for row_number, record in enumerate(reader.iterShapeRecords()):
                stats["sourceRecords"] += 1
                if record.shape.shapeType == 0:
                    stats["nullSourceGeometries"] += 1
                    continue
                west, south, east, north = record.shape.bbox
                if east < EXTENT[0] or west > EXTENT[2] or north < EXTENT[1] or south > EXTENT[3]:
                    stats["outsideExtent"] += 1
                    continue
                properties = record.record.as_dict()
                geometry = shape(record.shape.__geo_interface__)
                if not geometry.intersects(clip):
                    stats["outsideExtent"] += 1
                    continue
                stats["sourceRecordsIntersectingExtent"] += 1
                feature_class = properties.get("featurecla", "")
                class_counts[feature_class] += 1
                identifier = source_id(properties.get("ne_id"), row_number)
                if kind == "river" and feature_class not in ("River", "River (Intermittent)"):
                    stats["omittedNonRiverClass"] += 1
                    continue
                if not geometry.is_valid:
                    stats["invalidSourceGeometry"] += 1
                    excluded.append({"layer": layer, "sourceId": identifier, "reason": "invalid_source_geometry"})
                    continue
                clipped = keep_geometry_type(geometry.intersection(clip), kind)
                if clipped is None or clipped.is_empty:
                    stats["emptyAfterClip"] += 1
                    continue
                if kind == "lake":
                    if clipped.geom_type == "Polygon":
                        clipped = orient(clipped, sign=1.0)
                    else:
                        clipped = MultiPolygon([orient(part, sign=1.0) for part in clipped.geoms])
                mapped = mapping(clipped)
                mapped["coordinates"] = rounded_coordinates(mapped["coordinates"])
                rounded = shape(mapped)
                if not rounded.is_valid or rounded.is_empty:
                    # Very short source line parts can collapse at six decimal places.
                    # Keep their original precision instead of deleting or inventing geometry.
                    mapped = mapping(clipped)
                    rounded = clipped
                    assert rounded.is_valid and not rounded.is_empty
                    precision_fallbacks.append({"layer": layer, "sourceId": identifier})
                for longitude, latitude in coordinate_pairs(mapped["coordinates"]):
                    assert EXTENT[0] <= longitude <= EXTENT[2] and EXTENT[1] <= latitude <= EXTENT[3]
                    vertices += 1
                label = rounded.representative_point() if kind == "lake" else rounded.interpolate(0.5, normalized=True)
                name = properties.get("name") or properties.get("name_en") or None
                scale_rank = properties.get("scalerank")
                if scale_rank is not None:
                    scale_rank = int(scale_rank)
                features.append({
                    "type": "Feature", "id": f"{layer}:{identifier}:{row_number}",
                    "properties": {
                        "kind": kind, "name": name, "featureClass": feature_class,
                        "sourceLayer": layer, "sourceId": identifier, "scaleRank": scale_rank,
                        "labelPoint": [round(label.x, 6), round(label.y, 6)],
                    },
                    "geometry": mapped,
                })
                source_id_counts[identifier] += 1
                retained_classes[feature_class] += 1
                stats["retainedFeatures"] += 1
            sources.append({
                **source, "layer": layer, "version": version, "projectionWkt": projection,
                "documentation": LAKE_PAGE if kind == "lake" else RIVER_PAGE,
                "statistics": dict(stats), "sourceClassesInExtent": dict(class_counts),
                "retainedClasses": dict(retained_classes),
            })

    ids = [feature["id"] for feature in features]
    assert len(ids) == len(set(ids)), "Output feature IDs must be unique."
    counts = dict(collections.Counter(f["properties"]["kind"] for f in features))
    classes = dict(collections.Counter(f["properties"]["featureClass"] for f in features))
    geometry_types = dict(collections.Counter(f["geometry"]["type"] for f in features))
    names = {f["properties"]["name"] for f in features}
    great_lakes = ["Lake Superior", "Lake Michigan", "Lake Huron", "Lake Erie", "Lake Ontario"]
    assert all(name in names for name in great_lakes)
    assert all(name in names for name in ["Mississippi", "Missouri", "Ohio", "Columbia", "Colorado"])
    data = {"type": "FeatureCollection", "bbox": EXTENT, "features": features}
    output = atomic_json(args.out_dir / "hydro_overview.geojson", data)
    assert output["bytes"] < 5_000_000, output["bytes"]
    metadata = {
        "version": 1, "title": "Overview rivers, lakes and reservoirs — Natural Earth 1:10m",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "license": "Public domain", "licenseUrl": TERMS_PAGE,
        "attribution": "Made with Natural Earth. North America supplement derived from the North American Environmental Atlas / Commission for Environmental Cooperation.",
        "crs": "EPSG:4326", "coordinateOrder": "longitude,latitude", "clipBounds": EXTENT,
        "scope": "Contiguous-US map extent including adjacent Canada and Mexico for geographic context; all five Great Lakes are retained.",
        "sourceVersion": VERSION, "nativeCartographicScale": "1:10,000,000",
        "sourceObservationDate": None,
        "temporalNote": "Static cartography with mixed/unspecified observation dates. Source archive HTTP modification dates are December 8, 2021; those are file dates, not observation dates. This is not a November climatology or current water-extent product.",
        "sources": sources, "featureCounts": counts, "featureClasses": classes,
        "geometryTypes": geometry_types, "coordinatePairs": vertices,
        "schema": {
            "id": "Layer plus source ID plus source record index; source IDs can repeat across river parts",
            "kind": "river or lake; lake includes source lake, reservoir and alkaline-lake classes",
            "name": "Source name, falling back to source English name; null if neither is supplied",
            "featureClass": "Original Natural Earth feature class; River (Intermittent) is preserved",
            "sourceLayer": "Original Natural Earth layer basename",
            "sourceId": "Source ne_id as a string; source-record index only if no ID exists",
            "scaleRank": "Source cartographic importance rank, not a water measurement",
            "labelPoint": "Derived map-label anchor: representative point for polygons, line midpoint by coordinate length for rivers; not a surveyed feature center",
        },
        "processing": [
            "Read original Natural Earth WGS84 shapefiles from the official public S3 distribution and verify pinned archive checksums and CRCs.",
            "Combine base river/lake data with the North America supplements and clip geometry to the stated geographic rectangle.",
            "Keep source River and River (Intermittent) lines; omit lake-centerline connectors and canal records from the river layer.",
            "Retain lake/reservoir polygons and their interior holes; orient polygon rings for GeoJSON and preserve multipart geometry.",
            "No additional line simplification is applied. Source geometry is already cartographically generalized; coordinates are rounded to six decimal places unless that would invalidate geometry, in which case original coordinate precision is retained and reported.",
            "Derive optional label anchors for display only; do not infer water width, depth, level, flow, availability, blockage or suitability.",
        ],
        "validation": {
            "sourceArchivesChecksumAndCrcChecked": len(sources), "outputFeatures": len(features),
            "allCoordinatesFiniteAndInClipExtent": True, "allOutputGeometriesValid": True,
            "uniqueOutputIds": len(set(ids)), "greatLakesPresent": great_lakes,
            "prominentRiverNamesPresent": ["Mississippi", "Missouri", "Ohio", "Columbia", "Colorado"],
            "repeatedSourceIds": {key: n for key, n in source_id_counts.items() if n > 1},
            "excludedInvalidGeometries": excluded,
            "originalPrecisionRetainedToPreserveGeometry": precision_fallbacks,
        },
        "limitations": [
            "Natural Earth is a generalized, incomplete map reference at 1:10-million scale, not local hydrography or surveyed shorelines.",
            "River strokes are map symbols, not measured channel widths; lake outlines are generalized and may differ from present or seasonal extents.",
            "The intermittent class does not predict November wetness; absence from the layer does not establish absence of water.",
            "No seasonal discharge, flooding, depth, ice, water quality, safe drinking-water availability or crossing conditions are established by this overlay.",
            "The base and North America supplement contain upstream cartographic adjustments; line endpoints and confluences are not a validated routing network.",
            "No infrastructure joins, crossing recommendations, routes, or mobility scores are produced.",
        ],
        "software": {"python": platform.python_version(), "pyshp": shapefile.__version__, "shapely": shapely.__version__},
        "output": output,
    }
    atomic_json(args.out_dir / "hydro_overview_metadata.json", metadata, pretty=True)
    print(json.dumps({"featureCounts": counts, "featureClasses": classes, "geometryTypes": geometry_types,
                      "coordinatePairs": vertices, "output": output, "excludedInvalidGeometries": len(excluded)}))


if __name__ == "__main__":
    main()
