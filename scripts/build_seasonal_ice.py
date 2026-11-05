#!/usr/bin/env python3
"""NOAA GLERL gridded Great Lakes ice-concentration climatology, 2006–2025.

Run: python scripts/build_seasonal_ice.py --cache /absolute/external/cache
Requires Python 3 and NumPy. No GIS resampling software required: the official
coordinate grids are rectilinear after conversion to geographic coordinates.
"""
import argparse,calendar,collections,datetime,gzip,hashlib,io,json,math,re,time,urllib.request,zipfile
from pathlib import Path
import numpy as np

ROOT=Path(__file__).resolve().parents[1]; DEFAULT=ROOT/'docs/data'
HOME_URL='https://www.glerl.noaa.gov/data/ice/'
BASE=HOME_URL+'glicd/'
SOURCES={n:BASE+'grids/'+n for n in ['coords.zip','grid2000_2009.zip','grid2010_2019.zip','grid2020_2025.zip','grid2026.zip']}
SOURCES.update({n:BASE+'daily/'+n for n in ['README.txt','sup.txt','mic.txt','hur.txt','eri.txt','ont.txt']})
NAMES=['Lake Superior','Lake Michigan','Lake Huron','Lake Erie','Lake Ontario','Lake Saint Clair']
YEARS=list(range(2006,2026)); MONTHS=range(1,13)
def sha(b):return hashlib.sha256(b).hexdigest()
def acquire(cache):
    import concurrent.futures
    cache.mkdir(parents=True,exist_ok=True)
    def get(kv):
        n,url=kv;p=cache/n
        if not p.is_file():
            err=None
            for i in range(3):
                try:
                    req=urllib.request.Request(url,headers={'User-Agent':'PublicEnvironmentalAtlasData/0.8'})
                    with urllib.request.urlopen(req,timeout=75) as r:b=r.read()
                    if (n.endswith('.zip') and not b.startswith(b'PK')) or (n.endswith('.txt') and b.lstrip().startswith(b'<')):raise ValueError('Unexpected source file')
                    tmp=p.with_suffix(p.suffix+'.part');tmp.write_bytes(b);tmp.replace(p);break
                except Exception as e:err=e;time.sleep(i+1)
            if not p.is_file():raise RuntimeError(f'Failed {url}: {err}')
        b=p.read_bytes();return {'filename':n,'url':url,'bytes':len(b),'sha256':sha(b)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return list(pool.map(get,SOURCES.items()))
def nearest(axis,centers):
    assert np.all(np.diff(axis)>0)
    i=np.searchsorted(axis,centers);a=np.maximum(0,i-1);b=np.minimum(i,len(axis)-1);return np.where(abs(centers-axis[a])<=abs(centers-axis[b]),a,b)
def dated(record):
    m=re.fullmatch(r'g(\d{4})(\d\d)(\d\d)\.ct',Path(record).name,re.I)
    if not m:return None
    return datetime.date(*map(int,m.groups()))
def json_bytes(x):return json.dumps(x,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def summary_reference(file):
    line=[r.split() for r in file.read_text().splitlines() if r.strip()];cols=list(map(int,line[0]));out={}
    for r in line[1:]:
        month,day=r[0].split('-');m=list(calendar.month_abbr).index(month);assert len(r)-1==len(cols)
        for iy,s in zip(cols,r[1:]):
            y=iy-int(m in (11,12)) # source ICE years differ from calendar years
            if y not in YEARS or s.upper()=='NA':continue
            d=datetime.date(y,m,int(day));val=float(s);assert 0<=val<=100 and d not in out
            out[d]=val
    return out
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--cache',type=Path,required=True);ap.add_argument('--out',type=Path,default=DEFAULT);args=ap.parse_args();cache=args.cache;out=args.out
    out.mkdir(parents=True,exist_ok=True);sources=acquire(cache)
    with zipfile.ZipFile(cache/'coords.zip') as z:
        lat2=np.loadtxt(z.open('1024_latgrid.txt'));lon2=np.loadtxt(z.open('1024_longrid.txt'));lids=np.loadtxt(z.open('1024_lake_ids.txt'),dtype='i1');assert lat2.shape==lon2.shape==lids.shape==(1024,1024)
        assert np.all(lat2==lat2[:,0:1]) and np.all(lon2==lon2[0:1,:]) and np.all(np.diff(lat2[:,0])<0)
    byname={}
    for f in json.loads((DEFAULT/'hydro_overview.geojson').read_text())['features']:
        n=f['properties']['name']
        if n in NAMES and f['properties']['kind']=='lake':assert n not in byname;byname[n]=f['id']
    assert set(NAMES)==set(byname)
    # 0.05-degree geographic cells. Each is the nearest provider grid node,
    # after source water masking, not interpolation across an ice edge/shore.
    x=np.round(np.arange(-92.375,-75.975,0.05),3);y=np.round(np.arange(49.125,41.325,-0.05),3)
    assert min(x)>=np.min(lon2) and max(x)<=np.max(lon2) and min(y)>=np.min(lat2) and max(y)<=np.max(lat2)
    ix=nearest(lon2[0,:],x); iy=1023-nearest(lat2[::-1,0],y)
    assert np.all(np.diff(ix)>0) and np.all(np.diff(iy)>0)
    ids=lids[iy[:,None],ix[None,:]];water=ids>0;idx=(iy[:,None]*1024+ix[None,:])[water]
    lake=ids[water];ny,nx=ids.shape;length=len(idx);assert set(np.unique(lake))==set(range(1,7))
    for i,n in enumerate(NAMES,1):
        # The overview window must not clip an entire portion of a lake.
        rr,cc=np.where(lids==i);assert lon2[0,cc.min()]>=min(x)-.025 and lon2[0,cc.max()]<=max(x)+.025 and lat2[rr.min(),0]<=max(y)+.025 and lat2[rr.max(),0]>=min(y)-.025,(i,n,lon2[0,cc.min()],lon2[0,cc.max()],lat2[rr.min(),0],lat2[rr.max(),0])
    sums=np.zeros((20,12,length),dtype='f8');counts=np.zeros((20,12,length),dtype='u1');dates=set();headers=collections.Counter();counts_chart=np.zeros((20,12),dtype=int)
    def read_year(z,yeararchive):
        for n in z.namelist():
            d=dated(n)
            if not d or d.year not in YEARS:continue
            assert d not in dates,(d,n);dates.add(d);iyr=d.year-2006;im=d.month-1;counts_chart[iyr,im]+=1
            raw=z.read(n)
            mat_start=re.search(rb'(?:US National Ice Center|Canadian Ice Service)[^\n]*\n',raw[:2048],re.I)
            if not mat_start:
                mat_start=re.search(rb'^source[^\n]*\n',raw[:2048],re.I|re.M)
            if not mat_start:raise ValueError((n,raw[:512]))
            header=raw[:mat_start.end()].decode('ascii').splitlines();keys={r.strip().split()[0].lower():r.strip().split()[-1] for r in header if r.strip()}
            assert int(keys['ncols'])==int(keys['nrows'])==1024 and abs(float(keys['cellsize'])-1800)<.01
            assert abs(float(keys['xllcorner'])+10288021.9553)<2 and abs(float(keys['yllcorner'])-4675974.1583)<2
            mat=np.fromstring(raw[mat_start.end():].decode('ascii'),sep=' ',dtype='i2');assert mat.size==1024*1024,(d,mat.size)
            data=mat[idx];keep=(data>=0)&(data<=100);assert np.all((data<=100)|(data==float(keys['nodata_value']))),(d,np.max(data))
            sums[iyr,im,keep]+=data[keep];counts[iyr,im]+=keep
            headers[keys['nodata_value']]+=1
        print('Processed ice year',yeararchive,flush=True)
    for a in ['grid2000_2009.zip','grid2010_2019.zip','grid2020_2025.zip']:
        with zipfile.ZipFile(cache/a) as decade:
            for member in sorted(decade.namelist()):
                yr=re.fullmatch(r'grid(\d{4})\.zip',Path(member).name)
                if yr and int(yr.group(1))>=2006:
                    with zipfile.ZipFile(io.BytesIO(decade.read(member))) as z:read_year(z,yr.group(1))
    with zipfile.ZipFile(cache/'grid2026.zip') as z:read_year(z,'2026 (calendar 2025 only)')
    assert sum(counts_chart.flat)==len(dates) and datetime.date(2025,12,31) in dates
    # Consistency checks against independently published whole-lake series.
    # Overview area weighting cos(latitude); source daily chart product and
    # whole-lake summary may vary slightly in lake masks and chart revisions.
    refs={i:summary_reference(cache/(n+'.txt')) for i,n in enumerate(['sup','mic','hur','eri','ont'],1)}
    months=[];checks=[];lake_references=[]
    for m in MONTHS:
        minima=np.array([math.ceil(.8*calendar.monthrange(y0,m)[1]) for y0 in YEARS]);cnt=counts[:,m-1,:];qualified=cnt>=minima[:,None]
        nyears=qualified.sum(axis=0);aval=np.divide(sums[:,m-1,:],cnt,out=np.full(cnt.shape,np.nan),where=qualified)
        av=np.divide(np.nansum(aval,axis=0),nyears,out=np.full(length,np.nan),where=nyears>=10)
        valgrid=[None]*(ny*nx);yrgrid=np.zeros((ny,nx),dtype='u1');yrgrid[water]=nyears;flat=np.flatnonzero(water)
        for k in np.flatnonzero(np.isfinite(av)):valgrid[int(flat[k])]=round(float(av[k]),2)
        mdata={'month':m,'values':valgrid,'validYears':yrgrid.ravel().tolist(),'chartDays':int(counts_chart[:,m-1].sum()),'chartYears':int((counts_chart[:,m-1]>0).sum()),'qualifiedYears':int((counts_chart[:,m-1]>=minima).sum()),'valueCells':int(np.isfinite(av).sum()),'chartDaysByYear':counts_chart[:,m-1].tolist()}
        months.append(mdata);weights=np.broadcast_to(np.cos(np.deg2rad(y))[:,None],ids.shape)[water]
        # Lakewide comparison is an audit, never a fill source.
        ref_row={}
        for i,rd in refs.items():
            years_l=[]
            for j,yy in enumerate(YEARS):
                v=[dd for date,dd in rd.items() if date.year==yy and date.month==m]
                if len(v)>=minima[j]:years_l.append(float(np.mean(v)))
            refval=float(np.mean(years_l)) if len(years_l)>=10 else None
            ref_row[NAMES[i-1]]={'referenceMeanPercent':round(refval,3) if refval is not None else None,'qualifyingYears':len(years_l)}
            mask=(lake==i)&np.isfinite(av)
            if refval is not None and np.any(mask):
                coarse=float(np.average(av[mask],weights=weights[mask]));checks.append({'month':m,'lake':NAMES[i-1],'sourceLakewide':round(refval,3),'areaWeightedOverview':round(coarse,3),'differencePoints':round(coarse-refval,3)})
        lake_references.append({'month':m,'lakewide':ref_row})
    assert months[0]['valueCells']>0 and months[1]['valueCells']>0 and months[2]['valueCells']>0
    assert len(checks)>=15 and max(abs(c['differencePoints']) for c in checks)<5,(len(checks),max(abs(c['differencePoints']) for c in checks))
    assert all(m['valueCells']==0 and m['chartDays']==0 for m in months if 7<=m['month']<=10)
    base={'schemaVersion':1,'title':'Seasonal Great Lakes surface ice concentration','unit':'%','startYear':2006,'endYear':2025,'source':'NOAA GLERL historical Great Lakes Ice Cover Database (USNIC/CIS charts)','sourceUrl':HOME_URL,'nativeSupport':'1024 × 1024 Mercator source grid; projection cell size 1,800 m. The source coordinate package supplies latitudes, longitudes, and lake IDs.','displaySupport':'0.05° geographic overview; nearest source grid cell to each displayed cell center, masked by the NOAA lake IDs.','method':'Average valid concentration (0–100%) across available chart dates within each calendar month and year. Include a cell-year only with valid values on at least 80% of all calendar days. Equally average qualifying yearly means if at least 10 of 20 years qualify. Retain actual qualifying year counts.','minimumCalendarDayFraction':0.8,'minimumYears':10,'limitations':['Ice charts are seasonal. No chart or sub-threshold coverage is unknown, never 0%.','A measured 0% surface concentration is distinct from a missing estimate.','These are charted surface concentrations, not ice thickness, load capacity, snow depth, or a present-day forecast.','The five Great Lakes and Lake Saint Clair are the only supported water bodies.'],'lakes':[{'id':i,'name':n,'geometryId':byname[n]} for i,n in enumerate(NAMES,1)]}
    payload={**base,'grid':{'width':nx,'height':ny,'lon':x.tolist(),'lat':y.tolist(),'rowOrder':'north-to-south','columnOrder':'west-to-east','crs':'EPSG:4326','lakeIds':ids.ravel().tolist()},'months':months};dest=out/'seasonal_ice.json.gz';dest.write_bytes(gzip.compress(json_bytes(payload),compresslevel=9,mtime=0))
    small=[{k:v for k,v in m.items() if k not in ('values','validYears')} for m in months]
    val={'passed':True,'uniqueChartDates':len(dates),'firstChartDate':min(dates).isoformat(),'lastChartDate':max(dates).isoformat(),'sourceHeaderNoDataCounts':dict(headers),'coverageByMonth':small,'lakewideCheck':'Same 80%-days/minimum-10-year rule. Compare area-weighted displayed grid with NOAA separately published daily lakewide averages; five lakes only. Both come from the same underlying chart system, so this is a processing cross-check, not an independent accuracy estimate.','lakewideChecks':checks,'lakewideReferenceCoverage':lake_references,'maximumAbsoluteDifferencePercentagePoints':max(abs(c['differencePoints']) for c in checks),'JulyThroughOctoberNoChartDatesConfirmed':True,'juneNote':'A few June chart dates exist in the gridded archive. They are insufficient to form a supported monthly climatology.','missingNeverZero':True}
    (out/'seasonal_ice_validation.json').write_text(json.dumps(val,indent=2)+'\n')
    man={**base,'sources':sources,'retrievalNote':'Downloaded through the NOAA GLERL historical ice cover page, including the ice-year 2026 archive for calendar November–December 2025.','sourceReference':'Yang et al. (2020), https://doi.org/10.1038/s41597-020-00603-1','builtAt':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sourceGeometryIds':byname,'outputSha256':sha(dest.read_bytes()),'outputBytes':dest.stat().st_size,'uniqueChartDates':len(dates),'coverageByMonth':small,'validationFile':'seasonal_ice_validation.json'}
    (out/'seasonal_ice_manifest.json').write_text(json.dumps(man,indent=2)+'\n')
    print('PASS',len(dates),ny,nx,dest.stat().st_size,[(m['month'],m['chartDays'],m['qualifiedYears'],m['valueCells']) for m in months], 'max lake comparison discrepancy',val['maximumAbsoluteDifferencePercentagePoints'],flush=True)
if __name__=='__main__':main()
