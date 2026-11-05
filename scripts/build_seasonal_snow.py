#!/usr/bin/env python3
"""2006–2025 calendar-month observed snow frequency. USNIC IMS 24 km ASCII snapshots.

Usage: python scripts/build_seasonal_snow.py --cache /path/outside/repo/ims-cache --fetch
Requires numpy, shapely and pyproj (netCDF4 for the optional Rutgers cross-check). To reproduce the independent archive check, save G10035-rutgers-nh-24km-weekly-sce-v01r00-19800826-20241104.nc from https://noaadata.apps.nsidc.org/NOAA/G10035/ as <cache>/rutgers24km.nc. The delivered grid is nearest-neighbor sampled,
not interpolated, at 0.25-degree atlas cell centers. Nothing estimates seasonal ice thickness.
"""
import argparse, calendar, concurrent.futures, datetime as dt, gzip, hashlib, io, json, math, re, time, urllib.request
from pathlib import Path
import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely import union_all, intersects_xy

ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'docs/data'; BASE='https://noaadata.apps.nsidc.org/NOAA/G02156/'
DOC='https://nsidc.org/data/g02156/versions/1'; GUIDE='https://nsidc.org/sites/default/files/g02156-v001-userguide_1_1.pdf'
GEO='https://nsidc.org/data/user-resources/help-center/how-import-ims-ascii-data-arcgis'
META=['Ims24km.gpd','imslat_24km.bin.gz','imslon_24km.bin.gz','G02156_missing_files.txt']
SOURCE_DIMS=(1024,1024); PX=23684.997; XLL=-12126597.; YLL=-12126597. # rounded lower-left projected edges derived from the official geolocator arrays (checked below)
PROJ='+proj=stere +lat_0=90 +lat_ts=60 +lon_0=-80 +R=6371200 +units=m'
sha=lambda b:hashlib.sha256(b).hexdigest()

def download(url,path):
    if path.exists():return
    path.parent.mkdir(parents=True,exist_ok=True)
    for attempt in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'CONUS-monthly-environmental-atlas/0.8'})
            with urllib.request.urlopen(req,timeout=50) as r:b=r.read()
            if path.suffix=='.gz':gzip.decompress(b) # CRC and length verification
            tmp=path.with_suffix(path.suffix+'.part');tmp.write_bytes(b);tmp.replace(path);return
        except Exception:
            if attempt==2:raise
            time.sleep(1+attempt)

def inventory(cache,fetch,workers):
    if fetch:
        for fn in META:download(BASE+'metadata/'+fn,cache/'metadata'/fn)
    items=[]
    for y in range(2006,2027):
        p=cache/str(y)/'list.html'
        if fetch:download(BASE+f'24km/{y}/',p)
        pairs=re.findall(r'href="(ims(\d{4})(\d{3})_00UTC_24km_v[\d.]+\.asc\.gz)"',p.read_text(),re.I)
        assert (350<=len(pairs)<=366 if y<2026 else len(pairs)>=1),(y,len(pairs))
        for filename,ys,doy in pairs:
            assert int(ys)==y
            date=dt.date(y,1,1)+dt.timedelta(days=int(doy)-1);assert date.year==y
            analysis_date=date-dt.timedelta(days=1)
            if 2006<=analysis_date.year<=2025:items.append((analysis_date,filename,cache/str(y)/filename))
    items=sorted(items);dates={x[0] for x in items};assert len(dates)==len(items)
    if fetch:
        with concurrent.futures.ThreadPoolExecutor(workers) as ex:
            list(ex.map(lambda a:download(BASE+f'24km/{a[1][3:7]}/{a[1]}',a[2]),items))
    return items

def make_grid(cache):
    lons=np.arange(-124.875,-66,.25);lats=np.arange(49.875,24,-.25);xx,yy=np.meshgrid(lons,lats)
    states=json.loads((DATA/'states.geojson').read_text());mask=intersects_xy(union_all([shape(f['geometry']) for f in states['features']]),xx,yy)
    tr=Transformer.from_crs('EPSG:4326',CRS.from_proj4(PROJ),always_xy=True);x,y=tr.transform(xx,yy)
    col=np.floor((x-XLL)/PX).astype(int);row=np.floor((y-YLL)/PX).astype(int)
    assert ((col>=0)&(col<1024)&(row>=0)&(row<1024)).all()
    # Independent geolocation check against the 24 km geolocator support arrays.
    # USNIC documents the arrays as lower-left corners, stored top-to-bottom;
    # source ASCII charts store rows bottom-to-top, requiring the row flip.
    def geo(k):return np.frombuffer(gzip.decompress((cache/'metadata'/('ims'+k+'_24km.bin.gz')).read_bytes()),'<f4').reshape(SOURCE_DIMS)
    fx,fy=tr.transform(geo('lon')[1023-row,col],geo('lat')[1023-row,col]);err=max(float(np.max(np.abs(fx-(XLL+col*PX)))),float(np.max(np.abs(fy-(YLL+row*PX)))));assert err<25,err
    return lons,lats,mask,row[mask],col[mask],err

def parse_chart(buf):
    raw=gzip.decompress(buf);lines=raw.splitlines();rows=lines[-1024:]
    if len(rows)==1024 and all(len(r)==1024 for r in rows):
        chart=np.frombuffer(b''.join(rows),np.uint8).reshape(SOURCE_DIMS)-48;assert chart.max()<=4
    else:
        # Expanded legacy layout: the first wholly numeric data line marks end
        # of header; 164 is ice and 165 is snow, per the IMS user guide.
        start=next(i for i,r in enumerate(lines) if re.fullmatch(rb'\s*\d+\s+\d+[\d\s]*',r))
        chart=np.fromstring(b' '.join(lines[start:]).decode('ascii'),sep=' ',dtype=np.int16).reshape(SOURCE_DIMS)
        assert np.isin(chart,[0,1,2,3,4,164,165]).all();chart[chart==164]=3;chart[chart==165]=4
    return chart


def validate_weekly(cache,items):
    # Independent distribution cross-check: after Feb 2004 Rutgers takes the Monday
    # analysis (Tuesday 00 UTC valid IMS chart), already used by the operational CDR.
    ref=cache/'rutgers24km.nc'
    if not ref.is_file(): return None
    from netCDF4 import Dataset
    _,_,mask,rows,cols,_=make_grid(cache)
    chosen=set();summaries=[]
    with Dataset(ref) as nc:
        nc.set_auto_mask(False)
        epoch={dt.datetime.fromtimestamp(int(n),dt.timezone.utc).date():i for i,n in enumerate(nc['time'][:])}
        land=nc['land'][:][1023-rows,cols]==1
        for date,filename,path in items:
            key=(date.year,date.month)
            if date not in epoch or key in chosen or date.month not in (1,4,7,10):continue
            chosen.add(key);im=parse_chart(path.read_bytes())[rows,cols];rm=nc['snow_cover_extent'][epoch[date],:,:][1023-rows,cols]
            dland=(im==2)|(im==4);nland=int((land!=dland).sum());nbinary=int(((im[land&dland]==4)!=rm[land&dland].astype(bool)).sum())
            summaries.append({'analysisDate':date.isoformat(),'sourceFile':filename,'landMaskDisagreements':nland,'snowFlagDisagreements':nbinary,'commonLandCells':int((land&dland).sum())})
    assert all(q['landMaskDisagreements']==q['snowFlagDisagreements']==0 for q in summaries),summaries
    assert len(summaries)==76,len(summaries)
    return {'product':'Rutgers 24 km weekly snow-cover extent G10035','productUrl':'https://nsidc.org/data/g10035/versions/1','fileUrl':'https://noaadata.apps.nsidc.org/NOAA/G10035/G10035-rutgers-nh-24km-weekly-sce-v01r00-19800826-20241104.nc','sha256':sha(ref.read_bytes()),'note':'For the common period 2006–2024 compare one Monday analysis each January, April, July and October; independent archive and georegistration check, not independent sensor or scientific accuracy validation.','totalChartCellComparisons':sum(q['commonLandCells'] for q in summaries),'dates':summaries}

def run(cache,files,out):
    lons,lats,mask,row,col,err=make_grid(cache);w,h=len(lons),len(lats)
    dates=set(a[0] for a in files);date0=dt.date(2006,1,1);expected=[date0+dt.timedelta(days=i) for i in range((dt.date(2026,1,1)-date0).days)];missing=[d.isoformat() for d in expected if d not in dates]
    # Match data inventory gaps to published 24-km ASCII errata, using valid dates.
    errata=re.split(r'^Missing [^\n]*GeoTIFF Files[ \t]*$',(cache/'metadata'/'G02156_missing_files.txt').read_text(),maxsplit=1,flags=re.M)[0]
    published=set()
    for ys,entries in re.findall(r'^(\d{4}) - (.+)$',errata,re.M):
        for ent in entries.split(','):
            if '[' in ent and '24km only' not in ent:continue
            match=re.search(r'\b(\d{3})\b',ent)
            if match:
                valid=dt.date(int(ys),1,1)+dt.timedelta(days=int(match.group(1))-1);analysis=valid-dt.timedelta(days=1)
                if 2006<=analysis.year<=2025:published.add(analysis.isoformat())
    assert set(missing)==published,(missing,sorted(published))
    digests=[];metadata_hashes={f:sha((cache/'metadata'/f).read_bytes()) for f in META}
    sums=np.zeros((12,len(row)),np.float64);ny=np.zeros_like(sums,dtype=np.uint8);days=np.zeros_like(sums,dtype=np.uint16)
    geo_points={'Lake Michigan center':(-87,43.5),'Pacific offshore':(-124.8,40),'Central Iowa':(-93.5,42),'Central Florida':(-81.6,28.2),'Upper Minnesota':(-94.6,48.1),'Cascade highlands':(-121.75,46.875)}
    tr=Transformer.from_crs('EPSG:4326',CRS.from_proj4(PROJ),always_xy=True)
    pts={k:tr.transform(*p) for k,p in geo_points.items()};counts={k:np.zeros(5,dtype=int) for k in pts};index={k:(int((y-YLL)//PX),int((x-XLL)//PX)) for k,(x,y) in pts.items()};coverage=[]
    for y in range(2006,2026):
        success=np.zeros((12,len(row)),np.uint8);n=np.zeros_like(success);filecounts=[0]*12
        for date,filename,path in (a for a in files if a[0].year==y):
            buf=path.read_bytes();header=gzip.GzipFile(fileobj=io.BytesIO(buf)).readline().decode('ascii');hd=re.search(r'\b(\d{7})\b',header);assert hd and hd.group(1)==date.strftime('%Y%j'),(filename,header,date);a=parse_chart(buf);m=date.month-1;sub=a[row,col];success[m]+=sub==4;n[m]+=(sub==2)|(sub==4);filecounts[m]+=1
            for k in pts:counts[k][a[index[k]]]+=1
            digests.append([date.isoformat(),(date+dt.timedelta(days=1)).isoformat(),filename,len(buf),sha(buf)])
        for j in range(12):
            required=math.ceil(calendar.monthrange(y,j+1)[1]*.8);good=n[j]>=required
            sums[j]+=np.divide(success[j],n[j],out=np.zeros(len(row)),where=good)*100;ny[j]+=good;days[j]+=n[j];coverage.append({'year':y,'month':j+1,'availableDailyCharts':filecounts[j],'calendarDays':calendar.monthrange(y,j+1)[1],'minValidLandDaysRequired':required,'eligibleDisplayCells':int(good.sum())})
        print('Processed snow',y,flush=True)
    months=[];matrix=[]
    for i in range(12):
        ok=ny[i]==20;v=np.round(sums[i]/20,1);assert np.all((v>=0)&(v<=100));arr=np.full((h,w),np.nan);arr[mask]=np.where(ok,v,np.nan);matrix.append(arr);vals=[None if not np.isfinite(t) else float(t) for t in arr.ravel()];total_obs=np.zeros((h,w),np.uint16);total_obs[mask]=np.where(ok,days[i],0);months.append({'month':i+1,'values':vals,'observationDays':[int(v) if v else None for v in total_obs.flat],'scheduledCalendarDays':int(sum(calendar.monthrange(y,i+1)[1] for y in range(2006,2026))),'availableDailyAnalyses':sum(c['availableDailyCharts'] for c in coverage if c['month']==i+1),'validCells':int(ok.sum()),'observedLandDaysRange':[int(days[i][ok].min()),int(days[i][ok].max())]});assert ok.sum()>10000
    def sample(lon,lat):
        r=int(np.argmin(abs(lats-lat)));c=int(np.argmin(abs(lons-lon)));return [None if not np.isfinite(a[r,c]) else float(a[r,c]) for a in matrix]
    samples={k:{'sampleCoordinate':[lon,lat],'sampledDisplayCenter':[lons[np.argmin(abs(lons-lon))],lats[np.argmin(abs(lats-lat))]],'monthlyFrequencyPercent':sample(lon,lat),'rawFlagCountsAtOriginalCoordinate_0_1_2_3_4':counts[k].tolist()} for k,(lon,lat) in geo_points.items()};assert sum(counts['Lake Michigan center'][[1,3]])>len(files)*.95 and sum(counts['Pacific offshore'][[1,3]])>len(files)*.95
    assert samples['Upper Minnesota']['monthlyFrequencyPercent'][0]>samples['Central Florida']['monthlyFrequencyPercent'][0] and samples['Upper Minnesota']['monthlyFrequencyPercent'][0]>samples['Upper Minnesota']['monthlyFrequencyPercent'][6]+40
    out.mkdir(exist_ok=True,parents=True);rel='seasonal_snow_sources.json.gz';manifest={'schemaVersion':1,'publisher':'US National Ice Center, distributed by NSIDC','metadataFiles':metadata_hashes,'sourcePathPattern':BASE+'24km/{validDateYear}/{filename}','recordFields':['analysisDate','validDate00UTC','filename','gzipBytes','sha256'],'records':digests,'missingAnalysisDates':missing,'missingValidDates':[(dt.date.fromisoformat(x)+dt.timedelta(days=1)).isoformat() for x in missing],'yearMonthCoverage':coverage,'checks':{'allCatalogFilesRead':True,'allInventoryGapsMatchPublished24kmAsciiErrata':True,'atlasConusMaskFileSha256':sha((DATA/'states.geojson').read_bytes()),'gzipCRCChecked':True,'everyAsciiHeaderAgreesWithAnalysisDate':True,'geolocatorVsProjectionMaxCornerDisagreementM':round(err,3),'latLonToSourceValidation':samples,'rutgersGeolocationAndFlagComparison':validate_weekly(cache,files)}};mb=json.dumps(manifest,separators=(',',':'),allow_nan=False).encode();(out/rel).write_bytes(gzip.compress(mb,mtime=0))
    d={'schemaVersion':1,'title':'Seasonal land snow cover','quantity':'Mean frequency of snow-classified days','unit':'%','minimumYears':20,'legendDescription':'Mean share of observed land days classified as snow. Each month-year requires at least 80% of calendar days observed and all 20 years must qualify. Source: about 24 km; measures frequency, not snow depth.','source':'USNIC Interactive Multisensor Snow and Ice Mapping System (IMS), NOAA/NSIDC G02156','sourceUrl':DOC,'archiveUrl':BASE+'24km/','guideUrl':GUIDE,'geolocationUrl':GEO,'errataUrl':BASE+'metadata/G02156_missing_files.txt','sourceSupport':'Nominal 24 km polar stereographic grid; nearest source cell at each 0.25° display-cell center.','period':{'startYear':2006,'endYear':2025,'dailyCharts':len(files),'expectedCalendarDays':len(expected),'missingCalendarDays':len(missing)},'method':'For each calendar month in each year, divide snow (IMS 4/165) days by observed snow-covered or snow-free land days (4/165 and 2). Require at least 80% of calendar days with a land observation and all 20 qualifying year-months. Average the 20 annual percentages equally and round to 0.1 percentage point. Group by the analysis calendar date: the day preceding the filename’s 00:00 UTC validity date. Include the 2026-01-01 valid chart for the 2025-12-31 analysis; exclude the 2006-01-01 valid chart for the 2005-12-31 analysis. Water, ice and out-of-domain flags never count as snow-free land.','limitations':'Measures frequency of mapped snow cover, not snow depth, water equivalent, snowfall amount, lake or river ice, bare-ice exposure, or a current condition. Named permanent ice/snow land-cover cells remain a separate land category; chart classification does not give snow persistence within a subpixel.','sourceManifest':rel,'grid':{'width':w,'height':h,'lon':lons.tolist(),'lat':lats.tolist(),'crs':'EPSG:4326','registration':'cell centers','rowOrder':'north to south','columnOrder':'west to east','cellSizeDegrees':.25,'mask':'Centers intersecting the atlas 48-state/DC outlines; source surface coverage additionally required.'},'months':months,'sampleChecks':samples};b=json.dumps(d,separators=(',',':'),allow_nan=False).encode();o=out/'seasonal_snow.json.gz';o.write_bytes(gzip.compress(b,mtime=0));print('Snow output',o.stat().st_size,'source files',len(files),'missing',missing,'samples',samples)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--cache',type=Path,required=True);a.add_argument('--out',type=Path,default=DATA);a.add_argument('--workers',type=int,default=12);a.add_argument('--fetch',action='store_true');args=a.parse_args();run(args.cache,inventory(args.cache,args.fetch,args.workers),args.out)
