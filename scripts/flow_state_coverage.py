#!/usr/bin/env python3
"""Summarize published monthly gauge files by state; each station counts once within a month."""
import calendar,csv,gzip,json
from collections import Counter
from pathlib import Path
DATA=Path(__file__).resolve().parents[1]/'docs/data'
names={f['properties']['STUSPS']:f['properties'].get('name') or f['properties'].get('NAME') for f in json.loads((DATA/'states.geojson').read_text())['features']}
with (DATA/'river_flow_coverage_by_state.csv').open('w',newline='') as out:
 w=csv.writer(out);w.writerow(['calendar_month','month_name','state_code','state_name','gauges_with_record','gauges_with_all_20_years','gauges_with_partial_records'])
 for m in range(1,13):
  d=json.loads(gzip.decompress((DATA/'water_months'/f'{m:02}.json.gz').read_bytes()));rows=d['stations'];total=Counter(s['state'] for s in rows);full=Counter(s['state'] for s in rows if all(v is not None for v in s['annualMeansCfs']));assert len(rows)==len({s['id'] for s in rows})==sum(total.values()) and set(total)==set(names)
  for code in sorted(names):w.writerow([m,calendar.month_name[m],code,names[code],total[code],full[code],total[code]-full[code]])
