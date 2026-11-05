#!/usr/bin/env python3
"""Build 12 calendar-month streamgage datasets from approved USGS observations.

Run water_build.py with an external cache first, then this script:
python scripts/water_months_build.py --legacy-cache PATH --cache PATH
Sources: the original 2006-11..2025-11 approved monthly means and fresh
state-by-state daily means for boundary months, plus full-period inventory.
"""
from __future__ import annotations
import argparse, calendar, concurrent.futures, csv, gzip, hashlib, io, json, math, re, statistics
from collections import Counter,defaultdict
from pathlib import Path
import water_build as wb
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/data'
YEAR0,YEAR1=2006,2025
DV_URL='https://waterservices.usgs.gov/nwis/dv/'

def load_edge(cache,states,workers):
 jobs=[]
 for code,st in states.items():
  para={'format':'rdb','stateCd':st,'parameterCd':'00060','hasDataTypeCd':'dv','siteOutput':'expanded','siteStatus':'all','siteType':'ST','startDt':'2006-01-01','endDt':'2025-12-31'}
  jobs.append(('inventory',st,wb.make_url(wb.SITE_URL,para)))
  for year,start,end in [(2006,'2006-01-01','2006-11-30'),(2025,'2025-11-01','2025-12-31')]:
   q={'format':'rdb','stateCd':st,'statCd':'00003','parameterCd':'00060','startDT':start,'endDT':end,'siteStatus':'all'}
   jobs.append((f'daily{year}',st,wb.make_url(DV_URL,q)))
 def run(job):
  kind,st,url=job;raw,meta=wb.fetch(url,cache,kind+'_'+st)
  if raw and not(raw.startswith(b'#') or raw.startswith(b'agency_cd')):raise ValueError('Unexpected format: '+url)
  if kind.startswith('daily') and raw and b'Discharge' not in raw and b'No sites' not in raw and len(raw)>2000: raise ValueError('Unexpected daily response: '+url)
  return kind,st,meta
 res=[]
 with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
  for n,x in enumerate(pool.map(run,jobs),1):
   res.append(x)
   if n%15==0: print(f'Source requests {n}/{len(jobs)}',flush=True)
 return res

def main():
 a=argparse.ArgumentParser();a.add_argument('--cache',type=Path,required=True);a.add_argument('--legacy-cache',type=Path,required=True);a.add_argument('--workers',type=int,default=7);a.add_argument('--acquire-only',action='store_true');args=a.parse_args();args.cache.mkdir(parents=True,exist_ok=True)
 states={f['properties']['GEOID']:f['properties']['STUSPS'] for f in json.loads((OUT/'states.geojson').read_text())['features']};assert len(states)==49
 res=load_edge(args.cache,states,args.workers);print(f'{len(res)} acquisitions verified.',flush=True)
 if not args.acquire_only:
  build(args.cache,args.legacy_cache,res,states)
  print('Leap-February:',verify_leap_february(args.cache),flush=True)

def checked(path):
 raw=path.read_bytes();m=json.loads(path.with_suffix('.meta.json').read_text());assert m['sha256']==wb.digest(raw) and m['bytes']==len(raw),path
 return raw,m

def build(cache,legacy,res,states):
 out=OUT/'water_months';out.mkdir(exist_ok=True)
 inventory={}; inv_count=Counter(); names={f['properties']['STUSPS']:f['properties']['name'] for f in json.loads((OUT/'states.geojson').read_text())['features']}
 for st in states.values():
  f,=cache.glob('inventory_'+st+'_*.rdb');raw,_=checked(f)
  for row in wb.rdb_rows(raw):
   if row['agency_cd']!='USGS' or row['site_tp_cd']!='ST' or row['country_cd']!='US' or row['state_cd'] not in states or row['dec_coord_datum_cd'] not in ('NAD83','WGS84'):continue
   try:xy=float(row['dec_long_va']),float(row['dec_lat_va'])
   except (TypeError,ValueError):continue
   if not(-125<=xy[0]<=-66 and 24<=xy[1]<=50):continue
   site=row['site_no'];r={'id':'USGS-'+site,'name':row['station_nm'],'lon':xy[0],'lat':xy[1],'state':states[row['state_cd']],'country':'US','coordinateDatum':row['dec_coord_datum_cd']}
   if site in inventory:assert inventory[site]==r
   inventory[site]=r
 series=defaultdict(lambda:defaultdict(dict)); overlap=[]; raw_monthly=0;edge_counts=Counter();missing_edge=Counter(); requests=[];subloc={}
 def put(site,m,ts,y,v):
  dst=series[(site,m)][ts];old=dst.get(y);assert old is None or old==v,(site,m,ts,y,old,v);dst[y]=v
 files=sorted(legacy.glob('monthly_*.rdb'));assert len(files)==1085
 for f in files:
  raw,meta=checked(f);requests.append(meta)
  for row in wb.rdb_rows(raw):
   assert row['agency_cd']=='USGS' and row['parameter_cd']=='00060';s=row['site_no']
   if s not in inventory:continue
   y,m,ts=int(row['year_nu']),int(row['month_nu']),row['ts_id'];assert (2006,11)<=(y,m)<=(2025,11)
   try:v=float(row['mean_va'])
   except ValueError:continue
   assert math.isfinite(v);put(s,m,ts,y,v);raw_monthly+=1;subloc[(s,ts)]=row.get('loc_web_ds','').strip()
 print('Approved monthly rows loaded:',raw_monthly,flush=True)
 for edge_i,(kind,st,meta) in enumerate(res):
  if edge_i and edge_i%15==0:print('Edge inventory/daily requests parsed:',edge_i,'/',len(res),flush=True)
  if not kind.startswith('daily'):continue
  f,=cache.glob(kind+'_'+st+'_*.rdb');raw,_=checked(f)
  bins=defaultdict(dict);cols=[]
  for line in raw.decode('utf-8-sig').splitlines():
   if line.startswith('agency_cd\t'):
    header=line.split('\t');cols=[]
    for i,col in enumerate(header):
     match=re.fullmatch(r'(\d+)_00060_00003',col)
     if match:cols.append((i,header.index(col+'_cd'),match[1]))
   elif line.startswith('USGS\t'):
    r=line.split('\t');site=r[1];
    if site not in inventory or not cols:continue
    y,m,day=map(int,r[2].split('-'));assert y==int(kind[-4:])
    for i,j,ts in cols:
     if not r[i] or not r[j]:continue
     if r[j]!='A':
      flags=set(re.split(r'[,;\s:]+',r[j].strip()))
      if 'A' not in flags or 'P' in flags:continue
     try:v=float(r[i]);
     except ValueError:continue
     if not math.isfinite(v) or v==-999999:continue
     z=bins[(site,m,ts,y)];assert day not in z or z[day]==v;z[day]=v
  for (s,m,ts,y),values in bins.items():
   if set(values)!=set(range(1,calendar.monthrange(y,m)[1]+1)):missing_edge[(y,m)]+=1;continue
   v=statistics.fmean(values.values())
   if m==11:
    baseline=series.get((s,m),{}).get(ts,{}).get(y)
    if baseline is not None:overlap.append((s,y,ts,v,baseline))
   else:assert (y==2006 and 1<=m<=10) or (y==2025 and m==12);put(s,m,ts,y,v);edge_counts[(y,m)]+=1
 print('Complete boundary station/series-months:',sum(edge_counts.values()),flush=True)
 docs=json.loads((OUT/'water_streamflow.json').read_text());previous={r['id']:r for r in docs['stations']};oldMeta=docs['metadata'];report=[];checks=[];novs={}
 selection='USGS stream sites (ST, discharge parameter 00060) with daily records overlapping January 2006–December 2025 in the 48 contiguous states and DC. Require US country code and valid NAD83 or WGS84 source coordinates. Each month is evaluated independently; conflicting discharge series are omitted for that month.'
 method=['Source monthly means for November 2006–November 2025 use approved daily data and require a complete calendar month (missingData=off). January–October 2006 and December 2025 use the arithmetic mean of approved USGS daily means only when every calendar day in the month is present for the same station and discharge series. Daily-derived boundary means may retain different source rounding.', 'Summaries give each available year equal weight. Full coverage requires all 20 years for the same calendar month. Gaps remain null. An incomplete record is explicitly partial.','The download stores source annual monthly means in ft³/s. The app converts to m³/s with 0.028316846592, and calculates the mean, median, and population standard deviation over the available values. A single observation has no displayed SD.']
 for m in range(1,13):
  stations=[];ambiguous=[];full=0;counts=Counter();perYear=Counter()
  for site,loc in sorted(inventory.items()):
   src=series.get((site,m));
   if not src:continue
   seq={tuple(vals.get(y) for y in wb.YEARS) for vals in src.values()}
   if len(seq)>1:ambiguous.append('USGS-'+site);continue
   values=next(iter(seq));assert len(values)==20 and any(v is not None for v in values)
   n=sum(v is not None for v in values);full+=n==20;counts[n]+=1
   for j,y in enumerate(wb.YEARS):perYear[y]+=values[j] is not None
   ts=sorted(src)[0];r={**loc,'seriesId':ts,'annualMeansCfs':values}
   if len(src)>1:r['equivalentSeriesIds']=sorted(src)
   if subloc.get((site,ts)):r['subLocation']=subloc[(site,ts)]
   stations.append(r)
   if m==11:novs[r['id']]=(ts,list(values))
  coverage={'publishedStations':len(stations),'completeBaselineStations':full,'partialBaselineStations':len(stations)-full,'nByValidYears':dict(sorted(counts.items())),'annualStationCounts':dict(perYear),'unresolvedSeriesCount':len(ambiguous),'statesWithPublishedStations':len(set(s['state'] for s in stations))}
  assert len(stations)==len(set(s['id'] for s in stations)) and full==counts[20] and sum(counts.values())==len(stations) and coverage['statesWithPublishedStations']==49
  meta={'title':f'Historical {calendar.month_name[m]} streamflow at USGS streamgages','description':f'Approved {calendar.month_name[m]} mean discharge, calculated separately for each year and summarized at individual streamgages.','month':m,'baseline':{'month':m,'startYear':2006,'endYear':2025,'expectedYears':20},'years':wb.YEARS,'source':oldMeta['source'],'selectionRule':selection,'method':method,'coverage':coverage,'limitations':['Point observations only; no interpolation to ungauged locations.','These are historical means, not current flow, water depth, speed, ice, flood extent or water quality.','Reservoirs, diversions and other human activities may influence discharge. Zero and negative flows are retained.']}
  def write_gz(path,d):
   b=json.dumps(d,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8');path.write_bytes(gzip.compress(b,compresslevel=6,mtime=0));return path.stat().st_size,wb.digest(path.read_bytes())
  path=out/f'{m:02}.json.gz';size,checksum=write_gz(path,{'schemaVersion':2,'metadata':meta,'stations':stations});report.append({'month':m,'monthName':calendar.month_name[m],'file':'water_months/'+path.name,'bytes':size,'sha256':checksum,'coverage':coverage,'ambiguousStations':ambiguous});print(m,coverage['publishedStations'],full,size,flush=True)
 nov_matches=all(novs[site]==(s['seriesId'],s['annualMeansCfs']) for site,s in previous.items() if site in novs);nov_diff=sorted(set(previous)^set(novs));assert nov_matches and not nov_diff,('November changed',nov_diff[:20]);assert len(overlap)>3000
 # Compare independently retrieved November daily-derived means to published November monthly reports.
 within=[(s,y,ts,a,b) for s,y,ts,a,b in overlap if abs(a-b)<=max(0.01,0.005*abs(b))];assert len(within)/len(overlap)>.97,(len(within),len(overlap));novstats={'matchedStationSeriesYears':len(overlap),'withinMaxOf0_01CfsOr0_5Percent':len(within),'outsideTolerance':len(overlap)-len(within),'tolerancePurpose':'Daily source rounding can differ from published monthly values. This cross-check is descriptive and does not replace source values.','examples':[{'station':'USGS-'+s,'year':y,'dailyMeanCfs':a,'reportedMonthlyCfs':b} for s,y,ts,a,b in (overlap[0],overlap[-1])]}
 check={'sourceChecksumVerification':True,'calendarMonthFiltering':True,'all12MonthsPublished':len(report)==12,'all20YearPositionsExplicit':True,'novemberMatchesExistingStationsSeriesAndAnnualValues':nov_matches and not nov_diff,'all49JurisdictionsEachMonth':True,'novemberCrossCheckOfDailyAndStatisticsSources':novstats,'countNote':'One station may be present in several months. Counts across months are not distinct station totals.'}
 wb.json_write(OUT/'water_months_validation.json',{'passed':True,'checks':check,'months':[{'month':r['month'],**r['coverage']} for r in report]},True)
 wb.json_write(OUT/'water_months_manifest.json',{'schemaVersion':1,'generatedAt':wb.utc_now(),'baseline':{'years':wb.YEARS,'calendarMonths':list(range(1,13))},'source':oldMeta['source'],'dailySource':DV_URL,'selectionRule':selection,'method':method,'eligibleUSInventory':len(inventory),'olderMonthlyProvenance':{'file':'water_manifest.json','sha256':wb.digest((OUT/'water_manifest.json').read_bytes()),'monthlyFilesVerified':len(files),'dateRange':['2006-11','2025-11'],'rowsRetainedEligibleStations':raw_monthly},'additionalRequests':[m for k,st,m in sorted(res,key=lambda row:row[2]['url'])],'completeDailySeriesMonthsUsed':{f'{y}-{m:02}':n for (y,m),n in sorted(edge_counts.items())},'validationFile':'water_months_validation.json','months':report},True)
 print('PASS:',novstats,flush=True)

def verify_leap_february(cache):
 site='03335500';year=2020;month=2
 q={'format':'rdb','sites':site,'statCd':'00003','parameterCd':'00060','startDT':'2020-02-01','endDT':'2020-02-29','siteStatus':'all'}
 raw,source=wb.fetch(wb.make_url(DV_URL,q),cache,'leap_feb_2020')
 d=json.loads(gzip.decompress((OUT/'water_months/02.json.gz').read_bytes()))
 s=next(x for x in d['stations'] if x['id']=='USGS-'+site);col=s['seriesId']+'_00060_00003'
 rows=wb.rdb_rows(raw); days=calendar.monthrange(year,month)[1];dates=[r['datetime'] for r in rows]
 assert days==29 and sorted(dates)==[f'2020-02-{day:02}' for day in range(1,days+1)]
 for r in rows:
  flags=set(re.split(r'[,;\s:]+',r[col+'_cd']));assert 'A' in flags and 'P' not in flags and r['site_no']==site and r['agency_cd']=='USGS'
 avg=statistics.fmean(float(r[col]) for r in rows);published=s['annualMeansCfs'][year-YEAR0];tol=max(0.01,0.005*abs(published));assert abs(avg-published)<=tol
 case={'station':s['id'],'sameSeriesId':s['seriesId'],'month':month,'year':year,'approvedDailyMeans':days,'independentDailyMeanCfs':avg,'sourceMonthlyMeanCfs':published,'absoluteDifferenceCfs':abs(avg-published),'toleranceCfs':tol,'dailySource':source,'passed':True}
 report_path=OUT/'water_months_validation.json';report=json.loads(report_path.read_text());report['checks']['independentLeapFebruary']=case;wb.json_write(report_path,report,True)
 return case

if __name__=='__main__':main()

