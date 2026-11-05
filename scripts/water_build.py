#!/usr/bin/env python3
"""Build a point-only November streamflow snapshot from approved USGS records.

Standard library only. Raw responses are cached outside the Site repository.
Run with --inventory-only first to inspect inventory; reruns reuse the cache.
No interpolation, channel-depth, ice, water-quality, or mobility inference.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import datetime as dt
import hashlib
import io
import json
import math
import pathlib
import statistics
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1]
YEARS = list(range(2006, 2026))
CFS_TO_M3S = 0.028316846592
STATS_URL = "https://waterservices.usgs.gov/nwis/stat/"
SITE_URL = "https://waterservices.usgs.gov/nwis/site/"
DOC_URL = "https://waterservices.usgs.gov/docs/statistics/statistics-details/"
FAQ_URL = "https://waterservices.usgs.gov/docs/statistics/faqs/"


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def json_write(path, data, pretty=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False,
                               indent=2 if pretty else None,
                               separators=None if pretty else (",", ":")) + "\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fetch(url, cache_dir, label, cache_only=False):
    """Cached GET with conservative retry; preserve timestamp and content digest."""
    key = digest(url.encode())[:20]
    path = cache_dir / (label + "_" + key + ".rdb")
    meta_path = path.with_suffix(".meta.json")
    if path.exists() and meta_path.exists():
        raw = path.read_bytes()
        metadata = json.loads(meta_path.read_text())
        if digest(raw) != metadata["sha256"]:
            raise ValueError("Cached response checksum mismatch: " + str(path))
        return raw, metadata
    if cache_only:
        raise RuntimeError("Required cached response is unavailable: " + str(path))
    last_error = None
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "CONUS-November-Environmental-Atlas/1.0",
                "Accept": "text/plain",
            })
            with urllib.request.urlopen(request, timeout=75) as response:
                raw = response.read()
                metadata = {"url": url, "retrievedAt": utc_now(),
                            "bytes": len(raw), "sha256": digest(raw),
                            "httpStatus": response.status}
            # A server-side HTML error is never treated as valid tabular data.
            if b"<html" in raw[:500].lower() or b"<!doctype" in raw[:500].lower():
                raise ValueError("Unexpected HTML response")
            path.write_bytes(raw)
            json_write(meta_path, metadata, True)
            return raw, metadata
        except Exception as error:
            last_error = error
            if isinstance(error, urllib.error.HTTPError) and error.code in (400, 401, 403):
                break
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise RuntimeError(f"{label}: {last_error}")


def rdb_rows(raw):
    lines = [line for line in raw.decode("utf-8-sig").splitlines()
             if line and not line.startswith("#")]
    if not lines:
        return []
    if len(lines) < 2:
        raise ValueError("Incomplete RDB response")
    # RDB has a column header followed by a type/width row, then data.
    return list(csv.DictReader(io.StringIO("\n".join([lines[0]] + lines[2:])), delimiter="\t"))


def make_url(base, parameters):
    return base + "?" + urllib.parse.urlencode(parameters, safe=",")


def significant(value, digits=7):
    return float(format(value, f".{digits}g"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=pathlib.Path,
                        default=pathlib.Path(tempfile.gettempdir()) / "conus_november_water_cache")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cache-only", action="store_true",
                        help="Require verified cached responses; never make network requests")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--maximum-stations", type=int, default=0,
                        help="Optional deterministic state-balanced subset; 0 selects all candidates")
    args = parser.parse_args()
    if not 1 <= args.workers <= 8:
        parser.error("Use between 1 and 8 workers")
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    states_geojson = json.loads((ROOT / "docs/data/states.geojson").read_text())
    states = {f["properties"]["GEOID"]: {
        "abbreviation": f["properties"]["STUSPS"],
        "name": f["properties"]["name"]} for f in states_geojson["features"]}
    if len(states) != 49 or "02" in states or "15" in states:
        raise ValueError("Expected 48 contiguous states and District of Columbia")

    requests = []
    failures = []
    excluded = Counter()
    inventory = {}

    def inventory_state(state):
        url = make_url(SITE_URL, {
            "format": "rdb", "stateCd": states[state]["abbreviation"],
            "parameterCd": "00060", "hasDataTypeCd": "dv",
            "siteOutput": "expanded", "siteStatus": "all", "siteType": "ST",
            "startDt": "2006-11-01", "endDt": "2025-11-30"})
        raw, metadata = fetch(url, args.cache_dir, "inventory_" + state, args.cache_only)
        return state, rdb_rows(raw), metadata

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, args.workers)) as pool:
        futures = {pool.submit(inventory_state, state): state for state in sorted(states)}
        for number, future in enumerate(concurrent.futures.as_completed(futures), 1):
            state = futures.pop(future)
            try:
                _, rows, metadata = future.result()
                requests.append(metadata)
                for row in rows:
                    if row.get("agency_cd") != "USGS" or row.get("site_tp_cd") != "ST":
                        excluded["inventoryNotUSGSStreamST"] += 1
                        continue
                    if row.get("state_cd") not in states:
                        excluded["outsideCONUSState"] += 1
                        continue
                    try:
                        lon, lat = float(row["dec_long_va"]), float(row["dec_lat_va"])
                    except (ValueError, KeyError):
                        excluded["missingCoordinates"] += 1
                        continue
                    if not (-125 <= lon <= -66 and 24 <= lat <= 50):
                        excluded["coordinatesOutsideCONUSBounds"] += 1
                        continue
                    if row.get("dec_coord_datum_cd") not in ("NAD83", "WGS84"):
                        excluded["unhandledCoordinateDatum"] += 1
                        continue
                    key = row["site_no"]
                    if key in inventory and inventory[key] != row:
                        raise ValueError("Conflicting station metadata: " + key)
                    inventory[key] = row
            except Exception as error:
                failures.append({"phase": "inventory", "state": state, "error": str(error)})
            if number % 10 == 0 or number == len(states):
                print(json.dumps({"phase": "inventory", "completed": number, "states": len(states),
                                  "candidateStations": len(inventory), "failures": len(failures)}), flush=True)

    # USGS state-filter responses can include Canadian province codes with the
    # same numeric values as US state FIPS codes. Keep the request inventory
    # stable for cache reuse, but never publish those records as US stations.
    non_us_candidates = sorted(site for site, row in inventory.items()
                               if row.get("country_cd") != "US")
    eligible_us_count = len(inventory) - len(non_us_candidates)
    excluded["outsideUSCountry"] = len(non_us_candidates)
    inventory_report = {
        "generatedAt": utc_now(), "candidateStations": len(inventory),
        "eligibleUSStations": eligible_us_count,
        "nonUSCountryCandidates": len(non_us_candidates),
        "statesRequested": 49,
        "countsByState": dict(sorted(Counter(states[r["state_cd"]]["abbreviation"]
                                                for r in inventory.values()
                                                if r.get("country_cd") == "US").items())),
        "exclusions": dict(excluded), "failures": failures,
        "selectionRule": "Inventory USGS stream sites (exact ST) with daily discharge records overlapping 2006-11-01 to 2025-11-30 through queries for the 48 contiguous states and DC; require valid NAD83/WGS84 decimal coordinates. Publish only records explicitly marked country US. Canadian records with colliding province codes are excluded rather than assigned US state names."}
    json_write(args.cache_dir / "inventory_report.json", inventory_report, True)
    print(json.dumps({"phase": "inventory_done", **inventory_report}), flush=True)
    if args.inventory_only:
        return
    if failures:
        raise RuntimeError("Inventory is incomplete; repair failed requests before building national snapshot")

    selected = sorted(inventory)
    subset_rule = "All state-filter inventory candidates were requested; no sampling. Non-US candidates are excluded from the published station layer."
    if args.maximum_stations and len(selected) > args.maximum_stations:
        # Explicit, reproducible state-balanced inventory sample; no data-value selection.
        by_state = defaultdict(list)
        for site in selected:
            if inventory[site].get("country_cd") == "US":
                by_state[inventory[site]["state_cd"]].append(site)
        selected = []
        depth = 0
        subset_limit = min(args.maximum_stations, eligible_us_count)
        while len(selected) < subset_limit:
            for state in sorted(by_state):
                sequence = by_state[state]
                # Hash ordering avoids systematically preferring a stream basin's upstream IDs.
                if depth == 0:
                    sequence.sort(key=lambda value: digest(value.encode()))
                if depth < len(sequence):
                    selected.append(sequence[depth])
                    if len(selected) == subset_limit:
                        break
            depth += 1
        selected.sort()
        subset_rule = (f"Deterministic state-balanced subset of {len(selected)} inventory stations: "
                       "round-robin through state FIPS codes, station order within each state by SHA256 of station ID. "
                       "This is an illustrative geographic subset, not a statistically representative sample of rivers.")
    batches = [selected[i:i + 10] for i in range(0, len(selected), 10)]
    series = defaultdict(lambda: defaultdict(dict))
    locations = {}
    duplicates = 0
    empty_batches = 0

    def statistics_batch(index, sites):
        url = make_url(STATS_URL, {
            "format": "rdb", "sites": ",".join(sites), "parameterCd": "00060",
            "statReportType": "monthly", "statType": "mean",
            "startDt": "2006-11", "endDt": "2025-11", "missingData": "off"})
        raw, metadata = fetch(url, args.cache_dir, f"monthly_{index:04d}", args.cache_only)
        return rdb_rows(raw), metadata

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(statistics_batch, i, sites): (i, sites)
                   for i, sites in enumerate(batches)}
        for number, future in enumerate(concurrent.futures.as_completed(futures), 1):
            index, sites = futures.pop(future)
            try:
                rows, metadata = future.result()
                requests.append(metadata)
                if not rows:
                    empty_batches += 1
                for row in rows:
                    if row.get("parameter_cd") != "00060" or row.get("agency_cd") != "USGS":
                        raise ValueError("Unexpected parameter or agency in response")
                    year, month = int(row["year_nu"]), int(row["month_nu"])
                    if month != 11 or year not in YEARS:
                        continue
                    site = row["site_no"]
                    if site not in sites:
                        raise ValueError("Unrequested site in response: " + site)
                    try:
                        value = float(row["mean_va"])
                    except ValueError:
                        excluded["blankOrNonnumericNovemberMeans"] += 1
                        continue
                    if not math.isfinite(value):
                        raise ValueError("Nonfinite discharge")
                    series_id = row["ts_id"]
                    previous = series[site][series_id].get(year)
                    if previous is not None:
                        if previous != value:
                            raise ValueError("Conflicting duplicate monthly means")
                        duplicates += 1
                    series[site][series_id][year] = value
                    locations[(site, series_id)] = row.get("loc_web_ds", "").strip()
            except Exception as error:
                failures.append({"phase": "monthly", "batch": index, "sites": sites,
                                 "error": str(error)})
            if number % 20 == 0 or number == len(batches):
                print(json.dumps({"phase": "monthly", "completed": number, "batches": len(batches),
                                  "stationsWithNovemberValues": len(series), "failures": len(failures)}), flush=True)

    stations = []
    ambiguous = []
    for site in selected:
        if inventory[site].get("country_cd") != "US":
            continue
        available = series.get(site, {})
        if not available:
            excluded["noApprovedCompleteNovember"] += 1
            continue
        # Never merge independent time series at one monitoring location.
        # Exact duplicate annual sequences are harmless; other multi-series cases stay unknown.
        sequences = {tuple(values.get(year) for year in YEARS) for values in available.values()}
        if len(sequences) > 1:
            ambiguous.append({"site": site, "seriesIds": sorted(available)})
            excluded["ambiguousMultipleDischargeSeries"] += 1
            continue
        series_id = sorted(available)[0]
        record = available[series_id]
        values = [record[y] for y in YEARS if y in record]
        converted = [v * CFS_TO_M3S for v in values]
        row = inventory[site]
        station = {
            "id": "USGS-" + site,
            "name": row["station_nm"],
            "lon": float(row["dec_long_va"]), "lat": float(row["dec_lat_va"]),
            "state": states[row["state_cd"]]["abbreviation"],
            "stateName": states[row["state_cd"]]["name"],
            "country": "US",
            "coordinateDatum": row["dec_coord_datum_cd"],
            "seriesId": series_id, "equivalentSeriesIds": sorted(available),
            "subLocation": locations.get((site, series_id), ""),
            "meanDischargeM3s": significant(statistics.mean(converted)),
            "medianDischargeM3s": significant(statistics.median(converted)),
            "sdDischargeM3s": significant(statistics.pstdev(converted)) if len(values) > 1 else None,
            "minAnnualMeanM3s": significant(min(converted)),
            "maxAnnualMeanM3s": significant(max(converted)),
            "validYears": len(values), "expectedYears": 20,
            "completeBaseline": len(values) == 20,
            "years": YEARS,
            "annualMeansM3s": [significant(record[y] * CFS_TO_M3S) if y in record else None for y in YEARS],
            "annualMeansCfs": [record.get(y) for y in YEARS],
            "sourceUrl": "https://waterdata.usgs.gov/monitoring-location/" + "USGS-" + site + "/",
        }
        stations.append(station)

    coverage = {
        "candidateStations": len(inventory), "eligibleUSStations": eligible_us_count,
        "nonUSCountryCandidates": len(non_us_candidates), "requestedStations": len(selected),
        "publishedStations": len(stations),
        "completeBaselineStations": sum(s["completeBaseline"] for s in stations),
        "partialBaselineStations": sum(not s["completeBaseline"] for s in stations),
        "statesWithPublishedStations": len({s["state"] for s in stations}),
        "countsByState": {state: {"published": sum(s["state"] == state for s in stations),
                                   "complete": sum(s["state"] == state and s["completeBaseline"] for s in stations)}
                          for state in sorted(v["abbreviation"] for v in states.values())},
        "countsByAvailableYears": dict(sorted(Counter(str(s["validYears"]) for s in stations).items(), key=lambda item: int(item[0]))),
        "annualStationCounts": {str(y): sum(s["annualMeansCfs"][i] is not None for s in stations) for i, y in enumerate(YEARS)},
        "failedRequestCount": len(failures), "emptyBatchCount": empty_batches,
        "exclusions": dict(excluded), "exactDuplicateMonthlyRows": duplicates,
    }
    metadata = {
        "title": "Observed November streamflow at USGS streamgages",
        "description": "Point summaries of approved monthly mean discharge; an environmental water-condition indicator.",
        "generatedAt": utc_now(), "buildStartedAt": started,
        "retrievedAtRange": [min(r["retrievedAt"] for r in requests), max(r["retrievedAt"] for r in requests)],
        "source": {"organization": "U.S. Geological Survey", "parameterCode": "00060",
                   "parameterName": "Discharge", "sourceUnits": "ft^3/s",
                   "displayUnits": "m^3/s", "cfsToM3s": CFS_TO_M3S,
                   "statisticsUrl": STATS_URL, "siteMetadataUrl": SITE_URL,
                   "documentationUrl": DOC_URL, "completenessDocumentationUrl": FAQ_URL},
        "baseline": {"month": 11, "startYear": 2006, "endYear": 2025, "expectedYears": 20},
        "selectionRule": inventory_report["selectionRule"] + " " + subset_rule,
        "method": [
            "Retrieve USGS monthly mean discharge, parameter 00060, from 2006-11 through 2025-11 with missingData=off; retain November only.",
            "The USGS service uses approved daily values only and, with missingData=off, suppresses a monthly mean when any daily value is missing.",
            "Compute the arithmetic mean and median of available annual November means, giving each available year equal weight. Standard deviation is the population standard deviation of those annual means.",
            "A station represents the full 2006–2025 baseline only when all 20 November monthly means are available. Partial records keep absent years as null; missing years are never imputed.",
            "Independent discharge series at one station are not combined. Stations with conflicting annual sequences across multiple series are excluded and reported in the manifest.",
            "Convert cubic feet per second to cubic metres per second using the exact factor 0.028316846592; retain original annual values for reproducibility. Stored summaries are rounded to seven significant digits, which is numerical storage precision rather than observational accuracy; source monthly means are already rounded by USGS.",
        ],
        "coverage": coverage,
        "limitations": [
            "Values describe monitored points only. No interpolation to ungauged channels, lakes, wetlands, or groundwater is performed.",
            "Discharge is volume per unit time; it does not establish channel depth, local water velocity, flood extent, ice thickness, or crossing suitability.",
            "These historical November summaries are not live conditions, forecasts, or probabilities of a particular event.",
            "A high or low discharge at one river is not a normalized hazard rating and is not directly comparable as a risk score between rivers.",
            "Zero mean discharge does not prove an absence of water; standing water or zero net flow can occur. Negative values can describe reversing flow and are preserved.",
            "No drinking-water quality, potability, accessibility, treatment requirement, or reliable resupply is inferred from discharge.",
            "Stations are unevenly distributed and are not a random sample of all streams. Some November 2025 values may still be unavailable or unapproved when retrieved.",
            "Regulated streamgages are included. Recorded discharge can reflect reservoir releases, diversions, pumping, and other upstream operations; it is not a natural-runoff-only climatology.",
            "Monthly means suppress day-to-day extremes; annual November variability describes variation among monthly means rather than within-month floods or drought events.",
            "USGS decimal coordinate datums NAD83 or WGS84 are retained as reported; the national overview does not resolve their metre-scale differences. Coordinate accuracy varies by station; decimal digits do not establish metre accuracy.",
            "Legacy WaterServices is scheduled for retirement on 2027-02-22. This snapshot remains usable, but the downloader will need migration to the modern API for subsequent updates.",
        ],
    }
    dataset = {"schemaVersion": 1, "metadata": metadata, "stations": stations}
    output_path = ROOT / "docs/data/water_streamflow.json"
    json_write(output_path, dataset)

    checks = {
        "uniqueStationIds": len({s["id"] for s in stations}) == len(stations),
        "explicitUSCountryForEveryPublishedStation": all(inventory[s["id"].removeprefix("USGS-")].get("country_cd") == "US" for s in stations),
        "atLeastOneObservationPerStation": all(s["validYears"] > 0 for s in stations),
        "yearArraysMatchBaseline": all(s["years"] == YEARS and len(s["annualMeansM3s"]) == 20 and len(s["annualMeansCfs"]) == 20 for s in stations),
        "yearCountsMatchNonNullValues": all(s["validYears"] == sum(v is not None for v in s["annualMeansCfs"]) for s in stations),
        "completeBaselineFlagsCorrect": all(s["completeBaseline"] == (s["validYears"] == 20) for s in stations),
        "conversionMatchesSource": all(abs(a - b * CFS_TO_M3S) <= max(1e-9, abs(a) * 1e-6) for s in stations for a, b in zip(s["annualMeansM3s"], s["annualMeansCfs"]) if a is not None),
        "meansReproduceFromSource": all(math.isclose(s["meanDischargeM3s"], statistics.mean(v * CFS_TO_M3S for v in s["annualMeansCfs"] if v is not None), rel_tol=1e-6, abs_tol=1e-9) for s in stations),
        "mediansWithinObservedMonthlyMeanRange": all(s["minAnnualMeanM3s"] <= s["medianDischargeM3s"] <= s["maxAnnualMeanM3s"] for s in stations),
        "noRequestFailures": not failures,
        "all49JurisdictionsInventoried": len([r for r in requests if "/site/" in r["url"]]) == 49,
        "allRequestedStationBatchesCompleted": len([r for r in requests if "/stat/" in r["url"]]) == len(batches),
    }
    validation = {"generatedAt": utc_now(), "passed": all(checks.values()), "checks": checks,
                  "inputResponseCount": len(requests), "cacheOnlyBuild": args.cache_only,
                  "coverage": coverage, "negativeMeanStations": sum(s["meanDischargeM3s"] < 0 for s in stations),
                  "zeroMeanStations": sum(s["meanDischargeM3s"] == 0 for s in stations),
                  "note": "Signed discharge can occur in reversing flows; negative or zero observations are preserved, not assigned a suitability class."}
    json_write(ROOT / "docs/data/water_validation.json", validation, True)
    manifest = {"schemaVersion": 1, "metadata": metadata,
                "dataset": {"file": "water_streamflow.json", "bytes": output_path.stat().st_size,
                            "sha256": digest(output_path.read_bytes())},
                "requests": sorted(requests, key=lambda r: r["url"]),
                "failures": failures, "ambiguousSeriesExcluded": ambiguous,
                "nonUSStationsExcluded": [{"site": site, "name": inventory[site]["station_nm"],
                                            "country": inventory[site].get("country_cd")}
                                           for site in non_us_candidates],
                "validation": validation, "script": "scripts/water_build.py"}
    json_write(ROOT / "docs/data/water_manifest.json", manifest, True)
    print(json.dumps({"phase": "done", "output": str(output_path), "bytes": output_path.stat().st_size,
                      "coverage": coverage, "validationPassed": validation["passed"]}), flush=True)
    if not validation["passed"]:
        raise RuntimeError("Water build validation failed; inspect water_validation.json")


if __name__ == "__main__":
    main()
