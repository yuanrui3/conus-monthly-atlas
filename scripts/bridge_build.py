#!/usr/bin/env python3
"""Build public NBI bridge locations and supplied descriptions, with no suitability data.

Uses only the Python standard library. Raw downloads belong in an external cache.
The 2025 CSV ZIP is substantially smaller than the converted national GeoJSON.
"""

from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
from pathlib import Path
import urllib.request
import zipfile


SOURCE_URL = "https://www.fhwa.dot.gov/bridge/nbi/2025hwybronefiledel.zip"
SOURCE_PAGE = "https://www.fhwa.dot.gov/bridge/nbi/ascii2025.cfm"
FORMAT_URL = "https://www.fhwa.dot.gov/bridge/nbi/format.cfm"
DC_URL = "https://www.fhwa.dot.gov/bridge/nbi/2025/GeoJSON/DC25.geojson"
SNAPSHOT_DATE = "2025-06-15"
SOURCE_SHA256 = "bee3b363a1f51095d0f9fb731f01a83bc30fb35243e1176955057c016e5f656e"
EXPECTED_TOTAL = 624193
EXPECTED_CONUS = 618895
FIELDS = ["id", "lon", "lat", "carried", "below", "location"]
# Published on the FHWA 2025 download page; excludes Alaska, Hawaii and territories.
EXPECTED_COUNTS = {
    "AL": 16181, "AZ": 8587, "AR": 12978, "CA": 25975, "CO": 8990,
    "CT": 4363, "DE": 874, "DC": 261, "FL": 13070, "GA": 15090,
    "ID": 4646, "IL": 26927, "IN": 19542, "IA": 23716, "KS": 24891,
    "KY": 14590, "LA": 12684, "ME": 2542, "MD": 5500, "MA": 5311,
    "MI": 11397, "MN": 13551, "MS": 16711, "MO": 24647, "MT": 5235,
    "NE": 15412, "NV": 2123, "NH": 2549, "NJ": 6825, "NM": 4033,
    "NY": 17666, "NC": 19343, "ND": 4250, "OH": 26713, "OK": 22926,
    "OR": 8329, "PA": 23314, "RI": 787, "SC": 9504, "SD": 5883,
    "TN": 20374, "TX": 56951, "UT": 3144, "VT": 2866, "VA": 14143,
    "WA": 8520, "WV": 7345, "WI": 14498, "WY": 3138,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(url: str, path: Path) -> dict:
    """Cache source bytes and HTTP provenance without putting raw files in dist."""
    metadata_path = path.with_suffix(path.suffix + ".http.json")
    headers = {"User-Agent": "CONUS-November-Environmental-Atlas/1.0"}
    if not path.exists():
        temporary = path.with_suffix(path.suffix + ".partial")
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as response:
            expected = response.headers.get("Content-Length")
            with temporary.open("wb") as output:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    output.write(chunk)
            if expected and temporary.stat().st_size != int(expected):
                raise ValueError(f"Incomplete source download: {url}")
            metadata = {
                "url": url,
                "retrievedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                "lastModified": response.headers.get("Last-Modified"),
                "etag": response.headers.get("ETag"),
            }
        temporary.replace(path)
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    elif metadata_path.exists():
        metadata = json.loads(metadata_path.read_text())
    else:
        # An already acquired source can be reused; do not invent a retrieval time.
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers, method="HEAD"), timeout=45) as response:
            metadata = {
                "url": url,
                "cachedFileCheckedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                "lastModified": response.headers.get("Last-Modified"),
                "etag": response.headers.get("ETag"),
            }
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return {**metadata, "bytes": path.stat().st_size, "sha256": sha256(path)}


def dms(value: str, degree_digits: int) -> float:
    """NBI latitude DDMMSSss / longitude DDDMMSSss; reject impossible components."""
    value = value.strip()
    if not value:
        raise ValueError("missing_coordinate")
    value = value.zfill(degree_digits + 6)
    if len(value) != degree_digits + 6 or not value.isdigit():
        raise ValueError("invalid_coordinate_format")
    degrees = int(value[:degree_digits])
    minutes = int(value[degree_digits:degree_digits + 2])
    seconds = int(value[degree_digits + 2:]) / 100
    if minutes >= 60 or seconds >= 60:
        raise ValueError("invalid_dms_component")
    return degrees + minutes / 60 + seconds / 3600


def compact_write(path: Path, value: dict) -> dict:
    content = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_bytes(content)
    temporary.replace(path)
    return {"file": path.name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def coordinate_pairs(coordinates):
    if isinstance(coordinates[0], (int, float)):
        yield coordinates
    else:
        for child in coordinates:
            yield from coordinate_pairs(child)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("docs/data"))
    parser.add_argument("--states", type=Path, default=Path("docs/data/states.geojson"))
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    state_features = json.loads(args.states.read_text())["features"]
    states = {
        feature["properties"]["GEOID"]: feature["properties"]
        for feature in state_features
    }
    state_bounds = {}
    for feature in state_features:
        coordinates = list(coordinate_pairs(feature["geometry"]["coordinates"]))
        state_bounds[feature["properties"]["GEOID"]] = [
            min(c[0] for c in coordinates), min(c[1] for c in coordinates),
            max(c[0] for c in coordinates), max(c[1] for c in coordinates),
        ]
    assert {p["STUSPS"] for p in states.values()} == set(EXPECTED_COUNTS)
    archive = args.cache_dir / "2025hwybronefiledel.zip"
    source = fetch(SOURCE_URL, archive)
    if source["sha256"] != SOURCE_SHA256:
        raise ValueError("The source ZIP differs from the audited 2025 release; review before publishing.")
    dc_path = args.cache_dir / "DC25.geojson"
    dc_source = fetch(DC_URL, dc_path)
    dc_reference = {
        feature["properties"]["BID01"]: feature["geometry"]["coordinates"]
        for feature in json.loads(dc_path.read_text())["features"]
    }

    records = {state: [] for state in sorted(EXPECTED_COUNTS)}
    input_counts = collections.Counter()
    exclusions = []
    outside_scope = collections.Counter()
    keys = set()
    duplicate_keys = collections.Counter()
    total = 0
    dc_checked = 0
    dc_max_difference = 0.0
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.namelist()
        assert members == ["2025HwyBridgesDelimitedAllStates.txt"]
        member = zipped.getinfo(members[0])
        with io.TextIOWrapper(zipped.open(member), encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream, quotechar="'"):
                total += 1
                if None in row or None in row.values():
                    raise ValueError(f"Malformed CSV record {total}")
                fips = row["STATE_CODE_001"].strip().zfill(2)
                if fips not in states:
                    outside_scope[fips] += 1
                    continue
                state = states[fips]["STUSPS"]
                input_counts[state] += 1
                identity = row["STRUCTURE_NUMBER_008"].strip()
                if not identity:
                    raise ValueError(f"Missing inventory key: {fips}")
                if (fips, identity) in keys:
                    duplicate_keys[(state, identity)] += 1
                keys.add((fips, identity))
                try:
                    latitude = dms(row["LAT_016"], 2)
                    longitude = -dms(row["LONG_017"], 3)
                    if not (-125 <= longitude <= -66 and 24 <= latitude <= 50):
                        raise ValueError("outside_conus_coordinate_envelope")
                    bounds = state_bounds[fips]
                    if not (bounds[0] - 0.25 <= longitude <= bounds[2] + 0.25
                            and bounds[1] - 0.25 <= latitude <= bounds[3] + 0.25):
                        raise ValueError("outside_state_coordinate_envelope")
                    assert math.isfinite(latitude) and math.isfinite(longitude)
                except ValueError as error:
                    exclusions.append({"state": state, "id": identity, "reason": str(error),
                                       "rawLatitude": row["LAT_016"], "rawLongitude": row["LONG_017"]})
                    continue
                if state == "DC":
                    reference = dc_reference[identity]
                    difference = max(abs(longitude - reference[0]), abs(latitude - reference[1]))
                    assert difference <= 0.00000051, (identity, difference)
                    dc_max_difference = max(dc_max_difference, difference)
                    dc_checked += 1
                records[state].append([
                    identity, round(longitude, 6), round(latitude, 6),
                    row["FACILITY_CARRIED_007"].strip(),
                    row["FEATURES_DESC_006A"].strip(),
                    row["LOCATION_009"].strip(),
                ])

    assert total == EXPECTED_TOTAL, total
    assert dict(input_counts) == EXPECTED_COUNTS, dict(input_counts)
    assert sum(input_counts.values()) == EXPECTED_CONUS
    point_count = sum(map(len, records.values()))
    assert point_count + len(exclusions) == EXPECTED_CONUS
    source_summary = {
        "name": "FHWA National Bridge Inventory — 2025 highway bridge locations",
        "url": SOURCE_PAGE, "downloadUrl": SOURCE_URL, "snapshotDate": SNAPSHOT_DATE,
    }
    outputs = []
    state_summaries = {}
    for state, rows in records.items():
        rows.sort(key=lambda row: row[0])
        state_properties = next(p for p in states.values() if p["STUSPS"] == state)
        state_summaries[state] = {
            "name": state_properties["name"], "stateFips": state_properties["GEOID"],
            "sourceRecords": input_counts[state], "mappedRecords": len(rows),
            "excludedCoordinates": input_counts[state] - len(rows),
            "bbox": [min(row[1] for row in rows), min(row[2] for row in rows),
                     max(row[1] for row in rows), max(row[2] for row in rows)],
        }
        outputs.append(compact_write(args.out_dir / f"bridge_{state}.json", {
            "version": 1, "state": state, "stateFips": state_properties["GEOID"],
            "sourceUrl": SOURCE_PAGE, "downloadUrl": SOURCE_URL, "snapshotDate": SNAPSHOT_DATE,
            "fields": FIELDS, "records": rows,
        }))
    outputs.append(compact_write(args.out_dir / "bridge_points.json", {
        "version": 1, "source": source_summary, "coordinateOrder": "longitude,latitude",
        "pointCount": point_count, "pointsByState": {
            state: [coordinate for row in rows for coordinate in row[1:3]]
            for state, rows in records.items()
        },
        "stateCounts": {state: len(rows) for state, rows in records.items()},
        "detailTemplate": "data/bridge_{STATE}.json",
    }))
    outputs.append(compact_write(args.out_dir / "bridge_exclusions.json", {
        "version": 1, "sourceUrl": SOURCE_PAGE, "snapshotDate": SNAPSHOT_DATE,
        "reason": "Records without valid DMS components or outside the broad CONUS/state coordinate envelopes are not mapped.",
        "records": exclusions,
    }))
    metadata = {
        "version": 1, "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "title": "2025 FHWA highway bridge locations, contiguous United States and DC",
        "source": {**source_summary, **source, "pageUrl": SOURCE_PAGE, "archiveMember": member.filename,
                   "uncompressedBytes": member.file_size, "formatDocumentation": FORMAT_URL,
                   "coordinateDocumentation": "https://www.fhwa.dot.gov/bridge/mtguide.pdf"},
        "snapshotNote": "2025 annual inventory, separate from the 2006–2025 November climatology; not current bridge status.",
        "coverage": {"sourceRecordsAllStatesAndTerritories": total, "sourceConusRecords": EXPECTED_CONUS,
                     "mappedRecords": point_count, "excludedCoordinates": len(exclusions),
                     "outsideScopeCountsByFips": dict(outside_scope), "statesAndDistrict": len(records)},
        "states": state_summaries,
        "recordSchema": {"fields": FIELDS, "identity": "Preserve source structure IDs as strings; use state plus detail row index as the display key because two source IDs are repeated.",
                         "carried": "FACILITY_CARRIED_007: facility carried by structure, as supplied.",
                         "below": "FEATURES_DESC_006A: feature(s) intersected, as supplied; display as 'Feature crossed (reported)'.",
                         "location": "LOCATION_009: source location description, as supplied.",
                         "pointIndex": "Each state coordinate pair at offset 2*i matches row i in its detail file."},
        "processing": [
            "Read the official comma-delimited highway-only file with its documented single-quote text qualifier.",
            "Filter to the 48 contiguous state FIPS codes plus Washington, DC; preserve exact source IDs and descriptions.",
            "Parse latitude DDMMSSss and longitude DDDMMSSss; reject missing/non-numeric inputs, minutes >=60 and seconds >=60.",
            "Use west-negative longitude and reject locations outside longitude [-125,-66], latitude [24,50].",
            "Exclude positions outside their named state's Census bounding box with a conservative 0.25-degree buffer; this only screens gross position errors, not exact boundary membership.",
            "Round valid geographic coordinates to six decimal places; this is output precision, not a positional accuracy claim.",
            "Do not snap to rivers or roads, infer crossing water, deduplicate colocated structures, or assess crossing suitability.",
            "Sort by source structure ID within each state for stable point/detail row correspondence.",
        ],
        "validation": {"publishedNationalCountMatched": total == EXPECTED_TOTAL,
                       "all49PublishedStateCountsMatched": dict(input_counts) == EXPECTED_COUNTS,
                       "stateCoordinateEnvelope": {"file": args.states.name, "sha256": sha256(args.states),
                                                   "bufferDegrees": 0.25, "exactPolygonMembershipChecked": False},
                       "uniqueConusStateAndStructureIds": len(keys),
                       "repeatedSourceIds": [{"state": key[0], "id": key[1], "additionalRecords": count}
                                             for key, count in duplicate_keys.items()],
                       "dcGeojson": {"source": dc_source, "validRecordsCompared": dc_checked,
                                     "maxAbsoluteCoordinateDifferenceDegrees": dc_max_difference},
                       "exclusionsByReason": dict(collections.Counter(row["reason"] for row in exclusions)),
                       "allOutputsHaveFiniteJsonNumbers": True},
        "limitations": [
            "Point inventory locations, not surveyed bridge footprints or approaches; source positions may be inaccurate even after syntax/range checks.",
            "Two source identifiers repeat at different locations; those rows are preserved and listed in validation rather than silently merged.",
            "The highway-bridge inventory is not a complete inventory of every private, railway or pedestrian structure.",
            "A bridge may span a road, railway, waterway or other feature. The supplied crossed-feature description is not a hydrological measurement.",
            "Presence in this annual inventory does not establish present condition, availability or access.",
            "FHWA states that NBI data should not be used for route-clearance purposes.",
            "This extracted layer contains no ratings, loads, clearance, vehicle suitability, crossing recommendation or routing analysis.",
        ],
        "files": outputs,
    }
    (args.out_dir / "bridge_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"mappedRecords": point_count, "excludedCoordinates": len(exclusions),
                      "reasons": metadata["validation"]["exclusionsByReason"],
                      "statesAndDistrict": len(records), "outputBytes": sum(x["bytes"] for x in outputs),
                      "dcCompared": dc_checked, "dcMaxDifferenceDegrees": dc_max_difference}))


if __name__ == "__main__":
    main()
