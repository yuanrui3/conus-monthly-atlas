#!/usr/bin/env python3
"""Verify official USGS local land-cover imagery and write its client config.

Uses a dated public WMS, a raw GetFeatureInfo class response, and a small number
of cached probe requests. No RGB-to-class decoding or mobility model is used.
Only Python's standard library is required. Existing landcover.json supplies
the already verified official class labels and palette.
"""
from __future__ import annotations

import argparse
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import struct
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


BASE = "https://dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data"
WMS = BASE + "/wms"
LAYER = "Land-Cover-Native_conus_year_data"
TIME = "2025-01-01T00:00:00.000Z"
ORIGIN = os.environ.get("ATLAS_PROBE_ORIGIN", "http://localhost:8000")
RADIUS = 6378137.0
WORLD_HALF = math.pi * RADIUS
SOURCE_PAGE = "https://www.usgs.gov/data/annual-national-land-cover-database-nlcd-collection-1-products-ver-12-june-2026"
SERVICES_PAGE = "https://www.mrlc.gov/data-services-page"
METHOD_PAGE = "https://www.usgs.gov/centers/eros/science/annual-nlcd-land-cover-classification"
VALID_CODES = {11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95}


def url(params: dict, endpoint: str = WMS) -> str:
    return endpoint + "?" + urllib.parse.urlencode(params)


def request(cache: Path, name: str, address: str, offline: bool) -> tuple[bytes, dict]:
    body = cache / name
    record = cache / (name + ".response.json")
    if not body.exists() or not record.exists():
        if offline:
            raise RuntimeError(f"Missing cached probe: {name}")
        req = urllib.request.Request(address, headers={"Origin": ORIGIN, "User-Agent": "CONUS-November-Atlas public-data verification"})
        with urllib.request.urlopen(req, timeout=65) as response:
            raw = response.read()
            headers = {k.lower(): v for k, v in response.headers.items()}
            info = {
                "url": address, "httpStatus": response.status,
                "retrievedAt": datetime.now(timezone.utc).isoformat(),
                "contentType": headers.get("content-type"),
                "accessControlAllowOrigin": headers.get("access-control-allow-origin"),
                "originHeaderTested": ORIGIN,
                "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            }
        body.write_bytes(raw)
        record.write_text(json.dumps(info, indent=2) + "\n")
    raw = body.read_bytes()
    info = json.loads(record.read_text())
    assert info["url"] == address, "Cached request differs from the current probe recipe."
    assert info["sha256"] == hashlib.sha256(raw).hexdigest()
    assert info["httpStatus"] == 200
    return raw, info


def map_params(bbox: list[float], width: int = 256, height: int = 256) -> dict:
    return {"service": "WMS", "version": "1.3.0", "request": "GetMap",
            "layers": LAYER, "styles": "raster", "crs": "EPSG:3857",
            "bbox": ",".join(str(v) for v in bbox), "width": width, "height": height,
            "format": "image/png", "transparent": "true", "time": TIME}


def tile(lon: float, lat: float, zoom: int) -> tuple[list[float], int, int]:
    count = 2 ** zoom
    x = int((lon + 180) / 360 * count)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * count)
    span = 2 * WORLD_HALF / count
    return [x * span - WORLD_HALF, WORLD_HALF - (y + 1) * span,
            (x + 1) * span - WORLD_HALF, WORLD_HALF - y * span], x, y


def local_query(lon: float, lat: float) -> dict:
    x = RADIUS * math.radians(lon)
    y = RADIUS * math.asinh(math.tan(math.radians(lat)))
    # Web Mercator map scale grows with latitude. A 3-by-3 request with these
    # bounds has approximately 30 m ground support per query pixel everywhere.
    half = 45 / math.cos(math.radians(lat))
    params = map_params([x - half, y - half, x + half, y + half], 3, 3)
    params.update({"request": "GetFeatureInfo", "query_layers": LAYER,
                   "info_format": "application/json", "feature_count": 1, "i": 1, "j": 1})
    return params


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=Path("/tmp/conus-landcover-detail"))
    parser.add_argument("--outdir", type=Path, default=Path(__file__).resolve().parents[1] / "docs/data")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    capabilities_url = url({"service": "WMS", "version": "1.3.0", "request": "GetCapabilities"})
    describe_url = url({"service": "WCS", "version": "2.0.1", "request": "DescribeCoverage",
                        "coverageId": "mrlc_Land-Cover-Native_conus_year_data__" + LAYER}, BASE + "/wcs")
    requests = [("capabilities.xml", capabilities_url), ("describe.xml", describe_url)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        metadata_responses = list(pool.map(lambda pair: request(args.cache, pair[0], pair[1], args.offline), requests))
    ns = {"w": "http://www.opengis.net/wms"}
    root = ET.fromstring(metadata_responses[0][0])
    layer = next(n for n in root.findall(".//w:Layer", ns) if n.findtext("w:Name", namespaces=ns) == LAYER)
    assert layer.attrib.get("queryable") == "1"
    styles = [n.findtext("w:Name", namespaces=ns) for n in layer.findall("w:Style", ns)]
    assert "raster" in styles
    time_dimension = next(n for n in layer.findall("w:Dimension", ns) if n.attrib.get("name") == "time")
    assert TIME in time_dimension.text.split(",")
    assert any(n.text == "EPSG:3857" for n in root.iter() if n.tag.endswith("CRS"))
    map_formats = [n.text for n in root.findall(".//w:Request/w:GetMap/w:Format", ns)]
    info_formats = [n.text for n in root.findall(".//w:Request/w:GetFeatureInfo/w:Format", ns)]
    assert "image/png" in map_formats and "application/json" in info_formats
    coverage = ET.fromstring(metadata_responses[1][0])
    offsets = [[float(v) for v in n.text.split()] for n in coverage.iter() if n.tag.endswith("offsetVector")]
    assert len(offsets) == 2
    assert abs(offsets[0][0] - 30) < .001 and abs(offsets[1][1] + 30) < .001

    probes = []
    for name, lon, lat in [("crops_z13.png", -93.5, 42.3), ("outside_z13.png", -130.0, 40.0)]:
        bbox, x, y = tile(lon, lat, 13)
        probes.append({"name": name, "kind": "png", "url": url(map_params(bbox)), "zoom": 13, "tileX": x, "tileY": y})
    for name, lon, lat, expected in [("crops_query.json", -93.5, 42.3, 82),
                                      ("water_query.json", -87.0, 44.0, 11),
                                      ("outside_query.json", -130.0, 40.0, None)]:
        probes.append({"name": name, "kind": "class", "url": url(local_query(lon, lat)),
                       "lon": lon, "lat": lat, "expectedClass": expected})

    def probe(item: dict) -> dict:
        raw, info = request(args.cache, item["name"], item["url"], args.offline)
        assert info["accessControlAllowOrigin"] in {"*", ORIGIN}
        if item["kind"] == "png":
            assert raw[:8] == b"\x89PNG\r\n\x1a\n"
            width, height = struct.unpack(">II", raw[16:24])
            assert (width, height) == (256, 256)
            info.update({"width": width, "height": height, "zoom": item["zoom"], "tileX": item["tileX"], "tileY": item["tileY"]})
        else:
            value = json.loads(raw)
            assert value.get("type") == "FeatureCollection"
            features = value.get("features", [])
            code = features[0].get("properties", {}).get("PALETTE_INDEX") if features else None
            if code == 250:
                code = None
            assert code is None or code in VALID_CODES
            assert code == item["expectedClass"]
            info.update({"lon": item["lon"], "lat": item["lat"], "rawClass": code,
                         "valueProperty": "PALETTE_INDEX", "featureCount": len(features),
                         "queryImageSize": [3, 3], "nominalQueryGroundPixelMeters": 30})
        return info

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(probe, probes))
    overview = json.loads((args.outdir / "landcover.json").read_text())
    classes = [{k: row[k] for k in ["value", "label", "color", "group", "description"]}
               for row in overview["classes"]]
    assert {row["value"] for row in classes} == VALID_CODES
    resolution_range = [2 * WORLD_HALF * math.cos(math.radians(lat)) / (256 * 2 ** 13) for lat in [50, 24]]
    config = {
        "schemaVersion": 1, "id": "usgs-annual-nlcd-2025-local", "title": "Land cover · 30 m source",
        "source": "USGS Annual NLCD Collection 1.2, served by MRLC",
        "sourceUrl": SOURCE_PAGE, "sourceYear": 2025,
        "snapshot": "2025 calendar-year land cover; Collection 1.2, June 2026",
        "nativeResolutionMeters": 30, "nativeResolutionLabel": "30 m source cells",
        "sourceNativeCRS": "EPSG:5070", "license": "USGS data release: CC0 1.0 Universal",
        "attribution": "USGS Annual NLCD 2025 · MRLC · 30 m source",
        "classDocumentationUrl": "https://www.mrlc.gov/data/type/land-cover",
        "methodDocumentationUrl": METHOD_PAGE, "serviceDocumentationUrl": SERVICES_PAGE,
        "displaySupport": "Provider WMS imagery resampled from 30 m source cells. Zooming or smaller rendered pixels do not add information below the source support.",
        "wms": {
            "url": WMS, "version": "1.3.0", "layer": LAYER, "style": "raster", "time": TIME,
            "crs": "EPSG:3857", "format": "image/png", "transparent": True,
            "tileSize": 256, "maxNativeZoom": 13, "minDetailZoom": 8,
            "clientResampling": "nearest", "imageCrossOrigin": "anonymous",
            "maxConcurrentRequests": 3, "requestTimeoutMs": 25000,
            "groundPixelMetersAtMaximumTileZoomRange": resolution_range,
            "maximumTileZoomMeaning": "At z13, EPSG:3857 PNG pixels span approximately 12–18 m on the ground across CONUS. They resample the 30 m source and add no independent information below that support. Higher display zoom enlarges these tiles with nearest-neighbor rendering.",
            "capabilitiesUrl": capabilities_url, "webpAdvertised": "image/webp" in map_formats,
        },
        "featureInfo": {
            "enabled": True, "url": WMS, "request": "GetFeatureInfo", "infoFormat": "application/json",
            "valueProperty": "PALETTE_INDEX", "featureCount": 1,
            "queryWidth": 3, "queryHeight": 3, "queryI": 1, "queryJ": 1,
            "queryGroundResolutionMeters": 30, "queryCRS": "EPSG:3857",
            "noDataValues": [250], "fetchCredentials": "omit",
            "queryMethod": "Build a separate 3 × 3 query centered on the clicked longitude/latitude. In EPSG:3857, x=6378137*longitudeRadians, y=6378137*asinh(tan(latitudeRadians)), halfSpan=45/cos(latitudeRadians). BBOX=[x-halfSpan,y-halfSpan,x+halfSpan,y+halfSpan], WIDTH=HEIGHT=3, I=J=1. Pin the same 2025 TIME, layer, style and CRS. This is independent of viewport scale.",
            "responseMethod": "Read features[0].properties.PALETTE_INDEX as the provider class code. Empty features, source NoData 250, non-finite values or unrecognized codes are unknown. Never decode display colors or substitute a coarse overview class for a failed local lookup.",
            "label": "2025 provider class · nominal 30 m source support",
        },
        "classes": classes,
        "limitations": [
            "This is 2025 annual land cover, separate from November 2006–2025 climate. It is not a November foliage, crop-harvest or flood observation.",
            "The classification has 30 m native cells. Narrow features, mixed pixels and source classification errors remain; display enlargement does not establish finer ground truth.",
            "Forests, shrubland, crops and wetlands are distinct mapped categories. Tree spacing, understory, seasonal crop height, soil strength, current wetness and water depth are not provided.",
            "Provider map imagery uses scale-dependent rendering and reprojection. A local class query uses an independent nominal 30 m support request and may differ from generalized imagery when zoomed out.",
            "Open-water and wetland categories do not establish water quality, depth, current, safe crossings or present inundation.",
            "Class codes are obtained from the raw provider GetFeatureInfo response. The visual imagery is used for display only.",
            "External imagery and class queries require a working connection to the public USGS service. Failed requests must remain visibly unavailable.",
        ],
        "verification": {
            "verifiedAt": datetime.now(timezone.utc).isoformat(),
            "wmsVersion": "1.3.0", "layerQueryable": True, "styleVerified": "raster",
            "timePinnedAndAdvertised": TIME, "epsg3857AdvertisedAndTested": True,
            "pngTileVerified": True, "sourceNative30mVerifiedFromWcs": True,
            "corsResponseHeadersVerified": True, "corsOriginTested": ORIGIN,
            "browserExecutionVerified": False,
            "corsMeaning": "PNG and JSON responses were requested with the published site Origin and returned Access-Control-Allow-Origin:*. Final browser execution is verified by the UI integration workflow.",
            "rawClassAndNoDataQueriesVerified": True, "colorDecodingUsed": False,
            "capabilities": metadata_responses[0][1], "describeCoverage": metadata_responses[1][1],
            "probes": results,
        },
    }
    out = args.outdir / "landcover_detail_source.json"
    out.write_text(json.dumps(config, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(out), "bytes": out.stat().st_size, "maxNativeZoom": 13,
                      "classes": len(classes), "probes": len(results), "groundPixelRangeMeters": resolution_range}))


if __name__ == "__main__":
    main()
