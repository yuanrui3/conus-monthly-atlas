#!/usr/bin/env python3
"""Check two published station-months against an independent USGS daily endpoint.

The daily observations verify calendar-month selection and monthly-mean semantics;
they do not independently validate the original USGS measurements. Standard library
only. Run after water_build.py, with an optional --cache-dir outside the repository.
"""

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CASES = [("03335500", 2006), ("01646500", 2025)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = ROOT / "docs/data/water_streamflow.json"
    raw_dataset = dataset_path.read_bytes()
    dataset = json.loads(raw_dataset)
    stations = {s["id"]: s for s in dataset["stations"]}
    checks = []
    for site, year in CASES:
        parameters = {"format": "json", "sites": site, "parameterCd": "00060",
                      "statCd": "00003", "startDT": f"{year}-11-01",
                      "endDT": f"{year}-11-30", "siteStatus": "all"}
        url = "https://waterservices.usgs.gov/nwis/dv/?" + urllib.parse.urlencode(parameters)
        path = args.cache_dir / f"{site}_{year}11.json"
        if not path.exists():
            request = urllib.request.Request(url, headers={
                "User-Agent": "CONUS-November-Atlas-validation/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                path.write_bytes(response.read())
        source = path.read_bytes()
        series = json.loads(source)["value"]["timeSeries"]
        matching = [s for s in series if s["name"] == f"USGS:{site}:00060:00003"]
        if len(matching) != 1:
            raise ValueError("Expected one unambiguous daily discharge series: " + site)
        record = matching[0]
        rows = [v for group in record["values"] for v in group["value"]]
        dates = [v["dateTime"][:10] for v in rows]
        expected_dates = [f"{year}-11-{d:02d}" for d in range(1, 31)]
        values = [float(v["value"]) for v in rows]
        complete = (sorted(dates) == expected_dates and
                    all("A" in v["qualifiers"] for v in rows) and
                    all(v != record["variable"]["noDataValue"] for v in values))
        if not complete or record["variable"]["unit"]["unitCode"] != "ft3/s":
            raise ValueError("Expected 30 approved November daily values in ft3/s")
        daily_mean = statistics.mean(values)
        station = stations["USGS-" + site]
        published = station["annualMeansCfs"][station["years"].index(year)]
        # These two source monthly values are reported to whole cubic feet/second.
        # Check agreement at that reported precision, not false decimal equality.
        agrees = published is not None and abs(daily_mean - published) <= 0.5
        checks.append({"station": station["id"], "name": station["name"], "year": year,
                       "month": 11, "approvedDailyCount": len(values),
                       "dailyMeanCfs": daily_mean, "publishedMonthlyMeanCfs": published,
                       "absoluteDifferenceCfs": abs(daily_mean - published) if published is not None else None,
                       "toleranceCfs": 0.5, "passed": agrees, "sourceUrl": url,
                       "sourceSha256": hashlib.sha256(source).hexdigest()})
    report = {"generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
              "passed": all(c["passed"] for c in checks),
              "datasetSha256": hashlib.sha256(raw_dataset).hexdigest(),
              "scope": "Two independent endpoint checks of calendar dates, approved daily completeness and monthly aggregation; not a ground-truth validation of measurements or ungauged areas.",
              "cases": checks}
    output = ROOT / "docs/data/hydrology_validation.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("Independent hydrology checks failed")


if __name__ == "__main__":
    main()
