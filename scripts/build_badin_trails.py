"""Rebuild the Badin Lake recreational full-size trail layer. Stdlib only.

Input manifest: only the orange motorized entries with the full-size vehicle icon in the
US Forest Service Badin Lake recreation map (p. 1, right-hand column). GIS names below
were explicitly compared to those entries. A map rating is never a current access claim.
"""
from collections import defaultdict
from datetime import datetime, timezone
import argparse
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_TrailNFSPublishWithDataStatus_01/MapServer/0"
MAP = "https://www.fs.usda.gov/media/241208"
WHERE = "admin_org = '081110' AND trail_no LIKE 'TRBL%'"
FIELDS = "objectid,globalid,trail_no,trail_name,terra_motorized,fourwd_managed,fourwd_restricted,gis_miles,bmp,emp,trail_cn,admin_org"
QUERY = BASE + "/query?" + urlencode(dict(f="geojson", where=WHERE, outFields=FIELDS, returnGeometry="true", outSR=4326))
# trail badge, map label, published mileage, published rating, cross-checked GIS name
ROWS = [
    ("69", "Lakeview", 1.6, "Easy", "LAKEVIEW OHV"),
    ("79", "Slab Pile", 1.1, "Moderate", "SLAB PILE OHV"),
    ("89", "Wolf Den", 1, "Easy", "WOLF DEN OHV"),
    ("90", "Dutch John", 2.1, "Difficult", "DUTCH JOHN OHV"),
    ("91", "Dickey Bell", 3.5, "Difficult", "DICKEY BELL OHV"),
    ("91A", "Dickey Bell Alt", 0.4, "Moderate", "DICKEY BELL OHV BYPASS"),
    ("91B", "Dickey Bell Con", 0.1, "Moderate", None),
    ("92", "Rocky Mtn. Loop", 2, "Moderate", "ROCKY MOUNTAIN OHV"),
    ("93", "Sawmill", 1, "Moderate", "SAWMILL OHV"),
    ("96", "Falls Dam", 2, "Moderate", "FALLS DAM OHV"),
    ("390", "Daniel", 2, "Extremely Difficult", "DANIEL OHV"),
]
GRADES = {"Easy": 1, "Moderate": 2, "Difficult": 3, "Extremely Difficult": 4}


def build(source, stamp):
    if source.get("type") != "FeatureCollection" or source.get("exceededTransferLimit"):
        raise ValueError("Incomplete Forest Service source response")
    features = defaultdict(list)
    for f in source["features"]:
        p = f["properties"]
        if p["admin_org"] != "081110":
            raise ValueError("Unexpected district")
        features[p["trail_no"]].append(f)
    trails = []
    for number, name, miles, label, alias in ROWS:
        key = "TRBL" + number
        fs = sorted(features[key], key=lambda f: (f["properties"]["bmp"], f["properties"]["objectid"]))
        ps = [f["properties"] for f in fs]
        if fs and (alias is None or any(p["trail_name"] != alias for p in ps)):
            raise ValueError(f"Review source changes at {key} before rebuilding")
        geometry = None
        if not fs:
            status = "unmatched"
            note = "No matching numbered centerline in the Forest Service district extract. Catalog only."
        elif any(p["terra_motorized"] != "Y" or not p["fourwd_managed"] or p["fourwd_restricted"] for p in ps):
            status = "source-conflict"
            if not all(p["fourwd_restricted"] == "01/01-12/31" for p in ps):
                raise ValueError(f"Review changed access fields at {key}")
            note = "The recreation map shows a full-size vehicle symbol, but the GIS record lists four-wheel-drive use as restricted all year. Line withheld."
        else:
            status = "matched"
            lines = []
            for f in fs:
                g = f["geometry"]
                if g["type"] not in ("LineString", "MultiLineString"):
                    raise ValueError(f"Invalid line: {key}")
                parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
                for part in parts:
                    if len(part) < 2 or any(not (-81 < xy[0] < -79 and 35 < xy[1] < 36) for xy in part):
                        raise ValueError(f"Invalid coordinates: {key}")
                    lines.append([[round(x, 6), round(y, 6)] for x, y in part])
            geometry = dict(type="LineString", coordinates=lines[0]) if len(lines) == 1 else dict(type="MultiLineString", coordinates=lines)
            note = "Official centerline matched by district, trail number, name and four-wheel-drive management designation."
        attrs = ["objectid", "globalid", "trail_no", "trail_name", "fourwd_managed", "fourwd_restricted", "terra_motorized", "trail_cn"]
        trails.append(dict(id=number, name=name, grade=GRADES[label], officialRating=label, miles=miles,
                           geometry=geometry, geometryStatus=status, geometryNote=note,
                           gisRecords=[{k: p[k] for k in attrs} for p in ps]))
    return dict(title="Badin Lake full-size recreational trails", area="Uwharrie National Forest, North Carolina",
                publisher="USDA Forest Service", sourceTitle="Uwharrie National Forest Badin Lake Recreation Area map",
                sourceUrl=MAP, geometrySourceUrl=BASE, geometryQueryUrl=QUERY, sourceMapImage="data/badin_map.webp",
                mapPdfSha256="3ddf53aaf092fcff668292035cab8325ddbcb4c9b9ea537c3570f73552e4fec6",
                mapPdfCreationDate="2024-06-17", retrievedOn=stamp,
                description="All 11 named motorized trails carrying the full-size vehicle icon on the Forest Service recreation map. Labels and miles come from that map; the numbers 1–4 encode its four ordered labels. The map does not define a graded slope or vehicle-performance threshold.",
                joinMethod="National Forest System Trails, layer 0: match district admin_org 081110, prefix TRBL plus the printed trail badge, and independently cross-check the trail name. Retain original parts, with coordinates rounded to six decimal places in WGS84. The three Lakeview challenge sections and two Falls Dam connectors lack independent rating entries and are not included.",
                geometryPolicy="Only draw a matched line when the source identifies motorized use and four-wheel-drive management, without a conflicting restriction. 91A has conflicting use attributes; 91B has no matching district GIS record. Both remain in the catalog with null geometry. No lines were inferred or traced.",
                accessNote="Ratings describe published recreational difficulty, not current access, road conditions or vehicle capability. Check current land-manager maps, orders and notices.",
                seasonOrderUrl="https://www.fs.usda.gov/media/237560", ratingCodes=GRADES, trails=trails)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-cache", type=Path, help="optional unmodified response from geometryQueryUrl")
    ap.add_argument("--date", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--output", type=Path, default=Path(__file__).resolve().parents[1]/"docs/data/badin_trails.json")
    ns = ap.parse_args()
    if ns.source_cache:
        src = json.loads(ns.source_cache.read_text())
    else:
        with urlopen(QUERY, timeout=45) as r:
            src = json.load(r)
    out = build(src, ns.date)
    ns.output.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":"))+"\n")
