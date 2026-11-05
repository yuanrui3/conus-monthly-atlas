#!/usr/bin/env python3
"""Regional mean slope (degrees) from USGS 3DEP bare-earth elevations in a metre-based grid.
Usage: python3 scripts/build_regional_slope.py --cache /absolute/scratch/path
"""
import argparse,concurrent.futures,datetime,gzip,hashlib,json,math,time,urllib.request,urllib.parse
from pathlib import Path
import numpy as np,rasterio
from rasterio.features import geometry_mask,bounds
from rasterio.transform import from_origin
from rasterio.warp import transform_geom,reproject,Resampling
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/data';API='https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer';RES=500;SIDE=500000;N=SIDE//RES;GEO=.05

def grads(a,cell):
 return np.degrees(np.arctan(np.hypot(((a[:-2,2:]-a[:-2,:-2])+2*(a[1:-1,2:]-a[1:-1,:-2])+(a[2:,2:]-a[2:,:-2]))/(8*cell),((a[:-2,:-2]-a[2:,:-2])+2*(a[:-2,1:-1]-a[2:,1:-1])+(a[:-2,2:]-a[2:,2:]))/(8*cell))))

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--cache',required=True,type=Path);ap.add_argument('--workers',type=int,default=4);args=ap.parse_args();cache=args.cache;cache.mkdir(parents=True,exist_ok=True)
 states=[f['geometry'] for f in json.loads((OUT/'states.geojson').read_text())['features']];projected=[transform_geom('EPSG:4326','EPSG:5070',g) for g in states];bb=[bounds(g) for g in projected];x0=math.floor(min(a[0] for a in bb)/SIDE)*SIDE;y1=math.ceil(max(a[3] for a in bb)/SIDE)*SIDE;cols=math.ceil((max(a[2] for a in bb)-x0)/SIDE);rows=math.ceil((y1-min(a[1] for a in bb))/SIDE);mask=geometry_mask(projected,(rows,cols),from_origin(x0,y1,SIDE,SIDE),invert=True,all_touched=True)
 jobs=[(r,c) for r in range(rows) for c in range(cols) if mask[r,c]];print('Requesting',len(jobs),'500-km terrain tiles at 500 m sampling',flush=True)
 def fetch(t):
  r,c=t;x=x0+c*SIDE;y=y1-r*SIDE;b=(x-RES,y-SIDE-RES,x+SIDE+RES,y+RES);p=cache/f'dem5070_{x}_{y}_{RES}.tif';params=dict(bbox=','.join(map(str,b)),bboxSR=5070,imageSR=5070,size=f'{N+2},{N+2}',format='tiff',pixelType='F32',renderingRule=json.dumps({'rasterFunction':'None'},separators=(',',':')),interpolation='RSP_BilinearInterpolation',adjustAspectRatio='false',f='image');url=API+'/exportImage?'+urllib.parse.urlencode(params)
  def split_request():
   a=N+2;half=a//2;all_z=np.full((a,a),np.nan,'float32');records=[]
   for row,hh in [(0,half),(half,a-half)]:
    for col,ww in [(0,half),(half,a-half)]:
     xmin=b[0]+col*RES;ymax=b[3]-row*RES;bb=(xmin,ymax-hh*RES,xmin+ww*RES,ymax)
     pp={**params,'size':f'{ww},{hh}','bbox':','.join(map(str,bb))};u=API+'/exportImage?'+urllib.parse.urlencode(pp);part=cache/(p.stem+f'_part{row}_{col}.tif')
     if not part.exists():
      content=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'CONUS-Monthly-Atlas/0.8'}),timeout=100).read();assert content[:2] in (b'II',b'MM');part.write_bytes(content)
     with rasterio.open(part) as image:
      assert image.shape==(hh,ww) and image.crs.to_epsg()==5070 and np.allclose(image.bounds,bb,rtol=0,atol=.02);all_z[row:row+hh,col:col+ww]=image.read(1,masked=True).filled(np.nan)
     records.append({'bounds5070':bb,'url':u,'sha256':hashlib.sha256(part.read_bytes()).hexdigest(),'bytes':part.stat().st_size})
   with rasterio.open(p,'w',driver='GTiff',width=a,height=a,count=1,dtype='float32',crs='EPSG:5070',transform=from_origin(b[0],b[3],RES,RES),nodata=np.nan) as target:target.write(all_z,1)
   p.with_suffix('.parts.json').write_text(json.dumps(records))
  for attempt in range(3):
   try:
    if not p.exists():
     req=urllib.request.Request(url,headers={'User-Agent':'CONUS-Monthly-Atlas/0.8'});data=urllib.request.urlopen(req,timeout=105).read();assert data[:2] in (b'II',b'MM'),data[:100];temp=p.with_suffix('.part');temp.write_bytes(data);temp.replace(p)
    with rasterio.open(p) as ds:
     assert ds.crs.to_epsg()==5070 and ds.count==1 and ds.shape==(N+2,N+2) and ds.dtypes[0]=='float32';assert max(abs(u-v) for u,v in zip(ds.bounds,b))<.02
    rec={'bounds5070':b,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    if p.with_suffix('.parts.json').exists():rec['subrequests']=json.loads(p.with_suffix('.parts.json').read_text())
    else:rec['url']=url
    return t,p,rec
   except Exception:
    if attempt==1:
     print('Retrying as four aligned subtiles:',b,flush=True);split_request();continue
    if attempt==2:raise
    if p.exists():p.unlink()
    time.sleep(1+attempt)
 src=np.full((N*rows,N*cols),np.nan,dtype='float32');manifest=[]
 with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
  fs=[pool.submit(fetch,j) for j in jobs]
  for n,f in enumerate(concurrent.futures.as_completed(fs),1):
   (r,c),p,rec=f.result()
   with rasterio.open(p) as ds:a=ds.read(1,masked=True).filled(np.nan)
   a[(a<-500)|(a>5000)]=np.nan;s=grads(a,RES);s[~np.isfinite(a[1:-1,1:-1])]=np.nan;src[r*N:(r+1)*N,c*N:(c+1)*N]=s;manifest.append(rec)
   if n%5==0 or n==len(jobs):print('Validated and differentiated',n,'/',len(jobs),flush=True)
 w,h=1180,520;tr=from_origin(-125,50,GEO,GEO);dst=np.full((h,w),np.nan,'float32');reproject(src,dst,src_transform=from_origin(x0,y1,RES,RES),src_crs='EPSG:5070',src_nodata=np.nan,dst_transform=tr,dst_crs='EPSG:4326',dst_nodata=np.nan,resampling=Resampling.average,num_threads=3);land=geometry_mask(states,(h,w),tr,invert=True);lakegeoms=[f['geometry'] for f in json.loads((OUT/'hydro_overview.geojson').read_text())['features'] if f['properties'].get('kind')=='lake'];lakes=geometry_mask(lakegeoms,(h,w),tr,invert=True);dst[~land|lakes]=np.nan
 valid=dst[np.isfinite(dst)];assert len(valid)>250000 and valid.min()>=0 and valid.max()<90
 rr,cc=np.indices((5,5));plane=500*(.1*cc+.2*rr);assert np.allclose(grads(plane,500),np.degrees(np.arctan(np.hypot(.1,.2))));assert np.all(grads(plane*0,500)==0)
 def probe(lon,lat):
  v=dst[int((50-lat)/GEO),int((lon+125)/GEO)];return round(float(v),2) if np.isfinite(v) else None
 samples=[{'lon':x,'lat':y,'value':probe(x,y)} for x,y in [(-105.73,40.31),(-80.48,26.27),(-86.28,39.89),(-87,43.5)]];assert samples[0]['value']>samples[1]['value'] and samples[-1]['value'] is None,samples
 dx=[round(-125+(i+.5)*GEO,5) for i in range(w)];dy=[round(50-(i+.5)*GEO,5) for i in range(h)];vals=[round(float(q),2) if np.isfinite(q) else None for q in dst.ravel()]
 when=datetime.datetime.now(datetime.timezone.utc).isoformat();d={'schemaVersion':1,'source':{'title':'USGS 3DEP Elevation ImageServer','url':API,'sourceElevationSamplingM':RES,'time':'Static terrain; DEM vintage varies across source coverage.','retrievedAt':when},'grid':{'crs':'EPSG:4326','width':w,'height':h,'lon':dx,'lat':dy},'variables':{'slope':{'unit':'degrees','min':round(float(valid.min()),2),'max':round(float(valid.max()),2),'values':vals,'description':'Regional mean slope angle. Horn 3×3 gradients of a 500 m USGS elevation grid in CONUS Albers are averaged into 0.05° cells (about 5.6 km north–south). Local peaks and slopes can differ substantially from the average.'}}}
 out=OUT/'regional_slope.json.gz';out.write_bytes(gzip.compress(json.dumps(d,separators=(',',':'),allow_nan=False).encode(),compresslevel=6,mtime=0));meta={'product':'Regional mean terrain slope (degrees)','source':d['source'],'units':'degrees above horizontal (not percent grade)','calculation':'Request 500 m elevation samples in NAD83 / CONUS Albers, EPSG:5070 with bilinear interpolation and a one-sample halo around each tile. Calculate Horn 3×3 horizontal gradient from metre-based vertical and horizontal units; require all nine samples valid. Angle is atan(hypot(dz/dx,dz/dy)) in degrees. GDAL average resampling across valid contributing slope values gives each 0.05° overview cell. Clip centers to bundled contiguous-state boundaries and exclude generalized mapped lake centers. This is not slope computed from the 11 km ETOPO elevation overlay.','support':'500 m input samples (nominally 1.5 km 3×3 footprint); 0.05° display cells, roughly 5.6 km north–south, narrower east–west. Albers grid distances have small projection scale variation. No local grade or current condition inferred.','tileCount':len(manifest),'tiles':sorted(manifest,key=lambda v:v['bounds5070']),'floatDataRange':[round(float(valid.min()),3),round(float(valid.max()),3)],'validOverviewCells':len(valid),'publishedRoundingDegrees':.01,'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'validation':{'crsDimensionsTransformAndFormatChecked':True,'flatPlaneAndAnalyticalTiltTestsPassed':True,'checkPoints':samples,'allFiniteAnglesPhysical':True}};(OUT/'regional_slope_metadata.json').write_text(json.dumps(meta,indent=2)+'\n');print('PASS',len(valid),samples,flush=True)
if __name__=='__main__':main()
