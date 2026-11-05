#!/usr/bin/env python3
"""Derive monthly NOAA nClimGrid 2006–2025 climatologies for the atlas.

Uses the established November grid and schema; cross-checks each calendar month
against the 2025 NOAA text distribution and directly sampled 20-year raster
windows. Retains the previously published November file rather than rewriting it.
The dependency versions are in climate_requirements.txt. Run with --cache DIR.
"""
from __future__ import annotations

import argparse, calendar, copy, gzip, hashlib, json, math, statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import time, urllib.request
import numpy as np
import rasterio
from rasterio.windows import Window
from climate_build import YEARS, BUCKET, aggregate

ROOT = Path(__file__).resolve().parents[1]
URL = BUCKET + '/cog/{year}/nclimgrid-monthly-{year}{month:02d}.tif'
BANDS = {'mean_temp_c':'tavg','min_temp_c':'tmin','max_temp_c':'tmax','precip_mm':'precip'}
PNT = {'tavg':'tave','tmin':'tmin','tmax':'tmax','precip':'prcp'}

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(buf):
    return hashlib.sha256(buf).hexdigest()

def read_input(cache, year, month):
    stem=f'{year}{month:02d}'
    image, sidecar=cache/(stem+'.tif'), cache/(stem+'.json')
    url=URL.format(year=year,month=month)
    if image.exists() and sidecar.exists():
        rec=json.loads(sidecar.read_text())
        if (rec['url']==url and rec['year']==year and rec['month']==month and
            rec['sha256']==sha(image.read_bytes())):
            return image,rec
    for try_no in range(3):
        try:
            with urllib.request.urlopen(url,timeout=90) as r:
                buf=r.read()
                assert len(buf)>1000000 and buf[:2] in (b'II',b'MM')
                rec={'year':year,'month':month,'url':url,'retrievedAt':now(),
                     'lastModified':r.headers.get('Last-Modified'),'etag':r.headers.get('ETag'),
                     'bytes':len(buf),'sha256':sha(buf)}
            tmp=image.with_suffix('.part');tmp.write_bytes(buf);tmp.replace(image)
            sidecar.write_text(json.dumps(rec,indent=2)+'\n')
            return image,rec
        except Exception:
            if try_no==2:raise
            time.sleep(try_no+1)

def sample_2025_text(cache, month, srcfile):
    """Compare all bands to separately distributed original tabular values."""
    ref=json.loads((ROOT/'scripts/climate_unit_reference.json').read_text())
    n=0;largest=0;hashes={}
    with rasterio.open(srcfile) as ds:
        for rec in ref['records']:
            name=rec['band'];part=cache/f"check_2025_{PNT[name]}.txt"
            if not part.exists():
                req=urllib.request.Request(rec['sourceUrl'],headers={'Range':f"bytes=0-{rec['bytesSampled']-1}"})
                with urllib.request.urlopen(req,timeout=60) as r:part.write_bytes(r.read(rec['bytesSampled']))
            buf=part.read_bytes();assert sha(buf)==rec['sampleSha256']
            lines=buf.decode().splitlines()
            vals=[]
            for line in lines[:len(rec['points'])]:
                vals.append([float(x) for x in line.split()])
            assert all(len(row)==14 for row in vals)
            xy=[(r[1],r[0]) for r in vals];band=ds.descriptions.index(name)+1
            actual=[float(v[0])*ds.scales[band-1]+ds.offsets[band-1] for v in ds.sample(xy,indexes=band)]
            errs=[abs(v-r[month+1]) for v,r in zip(actual,vals,strict=True)]
            assert max(errs)<.0001,(month,name,max(errs))
            n+=len(errs);largest=max(largest,max(errs));hashes[name]=sha(buf)
    return {'comparisons':n,'maxAbsoluteDifference':largest,'tolerance':.0001,
            'unitsDocumentationUrl':ref['documentationUrl'],'sourceSampleHashes':hashes}

def export_numbers(a):
    valid=np.isfinite(a);out=np.round(a,2).astype(object)
    out[~valid]=None
    return out.ravel().tolist()

def names_in(obj,month):
    """Adapt human-readable documentation, never observations or grid values."""
    if isinstance(obj,str):return obj.replace('November',calendar.month_name[month])
    if isinstance(obj,list):return [names_in(x,month) for x in obj]
    if isinstance(obj,dict):return {k:names_in(v,month) for k,v in obj.items()}
    return obj

def direct_samples(records,grid,layers):
    """Independent 2x2 window reads, scalar per-cell weights and sample SD."""
    use=[('Indiana',-86.90,40.42),('Badin Lake, North Carolina',-80.04,35.42),
         ('Pacific Northwest',-122.50,45.49),('Arizona',-111.80,33.33)]
    width=grid['width']; h=grid['height']
    dx=grid['lon'][1]-grid['lon'][0];dy=grid['lat'][0]-grid['lat'][1]
    ids={name:round((grid['lat'][0]-lat)/dy)*width+round((lon-grid['lon'][0])/dx) for name,lon,lat in use}
    partial=[i for i,c in enumerate(grid['sourceCellCount']) if 0<c<4]
    if partial:ids['partial_block']=partial[len(partial)//2]
    series={name:[] for name in ids}
    weights={}
    for path,_ in records:
        with rasterio.open(path) as ds:
            indices=[ds.descriptions.index(BANDS[k])+1 for k in layers]
            for name,idx in ids.items():
                row,col=divmod(idx,width);assert row<h
                window=ds.read(indices,window=Window(2*col,2*row,2,2),masked=True).astype('float64').filled(np.nan)
                for j,b in enumerate(indices):window[j]=window[j]*ds.scales[b-1]+ds.offsets[b-1]
                series[name].append(window)
                weights[name]=[math.sin(math.radians(ds.transform.f+(2*row+y)*ds.transform.e))-
                               math.sin(math.radians(ds.transform.f+(2*row+y+1)*ds.transform.e)) for y in range(window.shape[1])]
    report=[]
    for name,idx in ids.items():
        record={'name':name,'gridIndex':idx,'latitude':grid['lat'][idx//width],
                'longitude':grid['lon'][idx%width],'values':{}}
        cube=np.array(series[name])
        for j,key in enumerate(layers):
            years=cube[:,j,:,:];ys,xs=np.where(np.all(np.isfinite(years),axis=0))
            expected_cells=len(ys);assert expected_cells==grid['sourceCellCount'][idx]
            if not expected_cells:
                assert grid['values'][key][idx] is None
                continue
            denominator=sum(weights[name][y] for y in ys)
            one_year=[sum(frame[y,x]*weights[name][y] for y,x in zip(ys,xs))/denominator for frame in years]
            v=statistics.mean(one_year);actual=grid['values'][key][idx]
            assert abs(v-actual)<=.00501,(name,key,v,actual)
            if key in grid['interannualStdDev']:
                assert abs(statistics.stdev(one_year)-grid['interannualStdDev'][key][idx])<=.00501
            record['values'][key]={'fromRawWindows':round(v,5),'published':actual}
        report.append(record)
    return report

def build_month(cache, out, month, template, workers):
    label=calendar.month_name[month]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        records=list(ex.map(lambda y:read_input(cache,y,month),YEARS))
    units=sample_2025_text(cache,month,records[-1][0])
    var_order=list(BANDS)
    stack=None;signature=None;transform=None;file_checks=[]
    for iy,(path,rec) in enumerate(records):
        with rasterio.open(path) as ds:
            sig=(ds.width,ds.height,tuple(ds.transform),ds.crs.to_epsg(),ds.descriptions)
            if signature is None:
                signature=sig;transform=ds.transform
                assert ds.crs.to_epsg()==4326 and set(ds.descriptions)==set(BANDS.values())
                md=template['metadata']['resolution']
                assert ds.width==md['nativeWidth'] and ds.height==md['nativeHeight']
                assert np.allclose(list(ds.bounds),md['nativeBounds'],rtol=0,atol=1e-8)
                assert np.isclose(transform.a,md['nativeDegrees']['x']) and np.isclose(-transform.e,md['nativeDegrees']['y'])
                assert transform.b==transform.d==0
                stack=np.empty((len(YEARS),len(var_order),ds.height,ds.width),dtype='float32')
            assert sig==signature,(month,rec['year'],'grid alignment')
            for j,key in enumerate(var_order):
                bi=ds.descriptions.index(BANDS[key])+1
                band=ds.read(bi,masked=True).astype('float32').filled(np.nan)
                # Source values are float32 with identity scale and offset in this product.
                assert ds.scales[bi-1]==1 and ds.offsets[bi-1]==0
                stack[iy,j]=band
            avg,lo,hi,pr=stack[iy];mask=np.isfinite(avg)
            assert all(np.array_equal(mask,np.isfinite(a)) for a in (lo,hi,pr))
            assert (lo[mask]<=avg[mask]+.02).all() and (avg[mask]<=hi[mask]+.02).all() and (pr[mask]>=0).all()
            file_checks.append({'year':rec['year'],'validNativeCells':int(mask.sum())})
    meta=names_in(template['metadata'],month)
    period=meta['period'];period['month']=month;period['monthName']=label
    meta['title']=f'CONUS seasonal atlas — {label} climate'
    meta['version']='0.7';meta['builtAt']=now()
    meta['source']['urlTemplate']=URL
    meta['source']['accessedAt']=max(rec['retrievedAt'] for _,rec in records)
    meta['source']['datasetCitation']=f'Vose et al. (2014), NOAA Monthly U.S. Climate Gridded Dataset (NClimGrid), Version 1. Subset: {label} 2006–2025. NOAA NCEI. doi:10.7289/V5SX6B56.'
    meta['source']['unitsVerification']=f"All four bands cross-checked against 2025 {label} NOAA tabular point values ({units['comparisons']} comparisons)."
    meta['limitations'][0]='Outdoor climatology does not measure an occupied vehicle cabin or the performance of its climate control.'
    grid=copy.deepcopy(template['grid']);values={};counts={};sds={};layers=[];coverage={}
    north=transform.f+np.arange(stack.shape[2])*transform.e
    weights=np.sin(np.deg2rad(north))-np.sin(np.deg2rad(north+transform.e))
    national={year:{'year':year} for year in YEARS}
    cells0=None
    for j,key in enumerate(var_order):
        slab=stack[:,j];complete=np.all(np.isfinite(slab),axis=0)
        coverage[key]=int((~complete & np.any(np.isfinite(slab),axis=0)).sum())
        native=slab.mean(axis=0,dtype=np.float64);native[~complete]=np.nan
        ov,cells=aggregate(native,weights,2)
        if cells0 is None:cells0=cells
        else:assert np.array_equal(cells0,cells)
        valid=np.isfinite(ov);fin=ov[valid]
        values[key]=export_numbers(ov);counts[key]=np.where(valid,len(YEARS),0).ravel().tolist()
        layer=names_in(next(l for l in template['layers'] if l['id']==key),month)
        layer.update({'validCells':len(fin),'min':round(float(fin.min()),2),'max':round(float(fin.max()),2),
                      'p02':round(float(np.percentile(fin,2)),2),'p98':round(float(np.percentile(fin,98)),2)})
        layers.append(layer)
        area=np.broadcast_to(weights[:,None],native.shape)[complete];area_total=area.sum()
        acc=np.zeros(ov.shape)
        for iy,year in enumerate(YEARS):
            yr=slab[iy]
            national[year][key]=round(float((yr[complete]*area).sum()/area_total),3)
            if key in ('mean_temp_c','precip_mm'):
                a,_=aggregate(np.where(complete,yr,np.nan),weights,2);acc+=np.where(valid,(a-ov)**2,0)
        if key in ('mean_temp_c','precip_mm'):
            sd=np.sqrt(acc/(len(YEARS)-1));sd[~valid]=np.nan;sds[key]=export_numbers(sd)
    del stack
    assert cells0.shape==(grid['height'],grid['width'])
    grid.update(values=values,validYears=counts,interannualStdDev=sds,sourceCellCount=cells0.ravel().tolist())
    meta['coverage'].update(validGridCells=int((cells0>0).sum()),nativeCompleteCells=int(cells0.sum()),nativeIncompleteCells=coverage)
    report=direct_samples(records,grid,var_order)
    data={'schemaVersion':1,'grid':grid,'layers':layers,'metadata':meta,
          'annualNationalSummary':{'method':template['annualNationalMethod'],'values':[national[y] for y in YEARS]}}
    raw=(json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n').encode()
    packed=gzip.compress(raw,compresslevel=6,mtime=0)
    target=out/f'{month:02d}.json.gz';tmp=target.with_suffix('.part');tmp.write_bytes(packed);tmp.replace(target)
    record={'month':month,'name':label,'path':'data/climate_months/'+target.name,'sha256':sha(packed),'decodedSha256':sha(raw),
            'bytes':len(packed),'decodedBytes':len(raw),'inputs':[r for _,r in records],
            'validGridCells':meta['coverage']['validGridCells'],'nativeCompleteCells':meta['coverage']['nativeCompleteCells'],
            'validation':{'sourceChecks':file_checks,'unitCrossCheck':units,'rawWindowChecks':report,'passed':True}}
    print(f'{label}: {len(packed):,} compressed bytes; {record["validGridCells"]:,} complete cells; {len(report)} raw-window checks.',flush=True)
    return record

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cache',type=Path,required=True)
    p.add_argument('--data',type=Path,default=ROOT/'docs/data')
    p.add_argument('--workers',type=int,default=4)
    args=p.parse_args();args.cache.mkdir(exist_ok=True,parents=True)
    out=args.data/'climate_months';out.mkdir(exist_ok=True,parents=True)
    nov_path=args.data/'climate.json';nov=json.loads(nov_path.read_text());nov_hash=sha(nov_path.read_bytes())
    existing=json.loads((args.data/'climate_manifest.json').read_text());assert nov_hash==existing['output']['sha256']
    template={'metadata':nov['metadata'],'layers':nov['layers'],'annualNationalMethod':nov['annualNationalSummary']['method'],
              'grid':{k:v for k,v in nov['grid'].items() if k not in ('values','validYears','interannualStdDev','sourceCellCount')}}
    november={'month':11,'name':'November','path':'data/climate.json','sha256':nov_hash,'bytes':nov_path.stat().st_size,
              'inputs':existing['inputs'],'validGridCells':nov['metadata']['coverage']['validGridCells'],
              'nativeCompleteCells':nov['metadata']['coverage']['nativeCompleteCells'],
              'validation':{'passed':True,'previouslyVerified':True,'report':'data/validation.json','originalManifest':'data/climate_manifest.json'}}
    del nov
    entries=[november];monthly_samples={}
    for m in range(1,13):
        if m!=11:entries.append(build_month(args.cache,out,m,template,args.workers))
    entries.sort(key=lambda r:r['month'])
    for e in entries:
        if e['month']==11:
            c=json.loads(nov_path.read_text());idx=round((c['grid']['lat'][0]-40.42)/(c['grid']['lat'][0]-c['grid']['lat'][1]))*c['grid']['width']+round((-86.90-c['grid']['lon'][0])/(c['grid']['lon'][1]-c['grid']['lon'][0]))
            fields={k:a[idx] for k,a in c['grid']['values'].items()};del c
        else:
            fields={k:r['published'] for k,r in e['validation']['rawWindowChecks'][0]['values'].items()}
        monthly_samples[e['name']]=fields
    assert len({tuple(sorted(f.items())) for f in monthly_samples.values()})==12
    h=[r['sha256'] for e in entries for r in e['inputs']];assert len(set(h))==len(h)==240
    manifest={'schemaVersion':1,'builtAt':now(),'sourceUrl':template['metadata']['source']['url'],'years':[YEARS[0],YEARS[-1]],
              'months':entries,'inputCount':len(h),'uniqueSourceHashes':len(set(h)),'support':'2006–2025; 20 instances of each calendar month.',
              'method':'Same four source variables, 2×2 spherical-area-weighted overview grid and strict full-baseline contributor rule as the November release. November file preserved byte-for-byte.',
              'validation':{'passed':True,'distinctCalendarMonthValueSetsAtIndianaPoint':12,'monthSamplePoint':[-86.90,40.42],
                            'monthSampleValues':monthly_samples,'note':'Checks verify acquisition and numerical processing, not independent scientific accuracy.'}}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print('Validated all 12 months from 240 unique source files.',flush=True)

if __name__=='__main__':main()
