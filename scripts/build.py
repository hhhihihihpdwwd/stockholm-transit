#!/usr/bin/env python3
"""Build static Stockholm timetable simulation. No secrets leave GitHub Actions."""
import csv, datetime as dt, io, json, os, re, sys, urllib.request, urllib.parse, urllib.error, zipfile, collections, math, pathlib, time, gzip, zlib
from zoneinfo import ZoneInfo

ROOT=pathlib.Path(__file__).resolve().parents[1]
PUBLIC=ROOT/'public'
OUT=PUBLIC/'data'; OUT.mkdir(exist_ok=True,parents=True)
# includes greater Stockholm; allow trains passing in and out of the county
BBOX=(58.65,60.45,16.25,19.35) # south,north,west,east
DAY0=dt.datetime.now(ZoneInfo('Europe/Stockholm')).date()
DAYS=[DAY0-dt.timedelta(days=1),DAY0,DAY0+dt.timedelta(days=1)]
AGENCIES=[]
FEEDS=[]


def fetch_feed(name,key,url):
    if not key: print(f'SKIP {name}: no key'); return None
    url=url+'?'+urllib.parse.urlencode({'key':key})
    req=urllib.request.Request(url,headers={
        'User-Agent':'StockholmTransitObservatory/1.1 (+timetable-simulator)',
        'Accept':'application/zip, application/octet-stream, */*',
        'Accept-Encoding':'gzip, deflate',
    })
    for attempt in range(3):
        try:
            print('Downloading',name,flush=True)
            with urllib.request.urlopen(req,timeout=180) as resp:
                data=resp.read()
                encoding=resp.headers.get('Content-Encoding','').lower().strip()
            if encoding == 'gzip':
                data=gzip.decompress(data)
            elif encoding == 'deflate':
                try: data=zlib.decompress(data)
                except zlib.error: data=zlib.decompress(data,-zlib.MAX_WBITS)
            elif encoding not in ('', 'identity'):
                raise ValueError('Unsupported response encoding: '+encoding)
            if not zipfile.is_zipfile(io.BytesIO(data)):
                raise ValueError('Feed response is not a ZIP file')
            print('Read',name,len(data)//1024//1024,'MiB',flush=True)
            return zipfile.ZipFile(io.BytesIO(data))
        except Exception as exc:
            print('Feed failure:',name,type(exc).__name__,str(exc).replace(key,'[REDACTED]')[:220],flush=True)
            time.sleep(attempt*2+1)
    return None

def records(z,filename):
    try:
        with z.open(filename) as f:
            for row in csv.DictReader(io.TextIOWrapper(f,encoding='utf-8-sig',errors='replace',newline='')):
                yield row
    except KeyError:
        return

def inside(lat,lon):
    return BBOX[0]<=lat<=BBOX[1] and BBOX[2]<=lon<=BBOX[3]

def pfloat(v):
    try:return float(v)
    except:return None

def service_on(z):
    selected={d:set() for d in DAYS}
    for row in records(z,'calendar.txt'):
        try:
            st=dt.datetime.strptime(row['start_date'],'%Y%m%d').date();en=dt.datetime.strptime(row['end_date'],'%Y%m%d').date()
            for d in DAYS:
                if st<=d<=en and row.get(['monday','tuesday','wednesday','thursday','friday','saturday','sunday'][d.weekday()])=='1':
                    selected[d].add(row['service_id'])
        except (KeyError,ValueError): pass
    for row in records(z,'calendar_dates.txt'):
        try:
            d=dt.datetime.strptime(row['date'],'%Y%m%d').date()
            if d in selected:
                if row['exception_type']=='1':selected[d].add(row['service_id'])
                elif row['exception_type']=='2':selected[d].discard(row['service_id'])
        except (KeyError,ValueError):pass
    return selected

def route_mode(r,agency):
    raw=r.get('route_type','3')
    try:t=int(raw)
    except:t=3
    info=' '.join((r.get('route_long_name',''),r.get('route_short_name',''),agency)).lower()
    if t in (0,900,901,902,903,904,905,906):return 'tram'
    if t in (1,400,401,402):return 'metro'
    if t in (4,1000,1001,1002):return 'ferry'
    if t==2 or 100<=t<400:
        if any(s in info for s in ('pendel','x60','commuter')):return 'commuter'
        if any(s in info for s in ('roslags','saltsjö')):return 'localrail'
        return 'rail'
    if t==3 or 700<=t<900:return 'bus'
    return 'other'

def time_sec(s):
    try:
        h,m,sec=map(int,s.split(':'));return h*3600+m*60+sec
    except:return None

def process_feed(z,label,global_routes,global_stops,global_shapes,per_day,seen_trips):
    print('Processing',label,flush=True)
    services=service_on(z)
    print('Active services',[(str(d),len(s)) for d,s in services.items()],flush=True)
    agencies={r.get('agency_id',''):r.get('agency_name','') for r in records(z,'agency.txt')}
    default_agency=next(iter(agencies.values()),label)
    routes={}
    for r in records(z,'routes.txt'):
        agency=agencies.get(r.get('agency_id',''),default_agency)
        mode=route_mode(r,agency)
        if mode=='other':continue
        short=r.get('route_short_name','').strip()
        long=r.get('route_long_name','').strip()
        color=(r.get('route_color') or '').strip().lstrip('#')
        if not re.fullmatch('[a-fA-F0-9]{6}',color):color={'metro':'1976D2','bus':'DA4B54','commuter':'E55397','tram':'28A6BA','localrail':'7964C7','rail':'818D9E','ferry':'2298B3'}.get(mode,'919191')
        key=(agency,short,long,mode,color.upper())
        if key not in global_routes:global_routes[key]=len(global_routes)
        routes[r.get('route_id')]=global_routes[key]
    local_stops={}
    for r in records(z,'stops.txt'):
        lat=pfloat(r.get('stop_lat')); lon=pfloat(r.get('stop_lon'))
        if lat is None or lon is None or not inside(lat,lon):continue
        sid=r.get('stop_id');name=r.get('stop_name','').strip()
        if not sid:continue
        key=(round(lat,5),round(lon,5),name)
        if key not in global_stops:global_stops[key]=len(global_stops)
        local_stops[sid]=global_stops[key]
    print('Local stops in area',len(local_stops),flush=True)
    trips={}
    active_ids=set().union(*services.values())
    for r in records(z,'trips.txt'):
        if r.get('service_id') not in active_ids or r.get('route_id') not in routes:continue
        ident=r.get('trip_id');
        if not ident:continue
        dates=[d for d in DAYS if r.get('service_id') in services[d]]
        if dates:trips[ident]=(routes[r['route_id']],r.get('trip_headsign',''),r.get('shape_id',''),dates)
    print('Trips with active service',len(trips),flush=True)
    stop_times=collections.defaultdict(list)
    for r in records(z,'stop_times.txt'):
        tid=r.get('trip_id');stop=r.get('stop_id')
        if tid not in trips or stop not in local_stops:continue
        arr=time_sec(r.get('arrival_time',''));dep=time_sec(r.get('departure_time',''))
        if arr is None and dep is None:continue
        if arr is None:arr=dep
        if dep is None:dep=arr
        try:seq=int(r.get('stop_sequence','0'))
        except:seq=0
        stop_times[tid].append((seq,local_stops[stop],arr,dep))
    relevant={tid:trips[tid] for tid,st in stop_times.items() if len(st)>=2}
    needed_shapes={r[2] for r in relevant.values() if r[2]}
    print('Trips with 2+ in-area stops',len(relevant),'shapes',len(needed_shapes),flush=True)
    raw_shapes=collections.defaultdict(list)
    for r in records(z,'shapes.txt'):
        sid=r.get('shape_id')
        if sid not in needed_shapes:continue
        lat=pfloat(r.get('shape_pt_lat'));lon=pfloat(r.get('shape_pt_lon'))
        if lat is None or lon is None:continue
        try:seq=int(r.get('shape_pt_sequence','0'))
        except:seq=0
        raw_shapes[sid].append((seq,lat,lon))
    shape_map={}
    for sid,pts in raw_shapes.items():
        pts.sort()
        # Trim to corridor around in-area points; include boundary neighbors. Limit complexity ~1000 per shape.
        kept=[(round(lat,5),round(lon,5)) for _,lat,lon in pts if BBOX[0]-.02<=lat<=BBOX[1]+.02 and BBOX[2]-.02<=lon<=BBOX[3]+.02]
        if len(kept)<2:continue
        # Reduce redundant near-identical points, retain bends. Preserve route fidelity.
        arr=[kept[0]]
        for p in kept[1:-1]:
            prev=arr[-1]
            if abs(p[0]-prev[0])+abs(p[1]-prev[1])>=.00013:arr.append(p)
        arr.append(kept[-1]);
        if len(arr)>1800:
            step=math.ceil(len(arr)/1800);arr=arr[::step]+[arr[-1]]
        coords=tuple(arr)
        if coords not in global_shapes:global_shapes[coords]=len(global_shapes)
        shape_map[sid]=global_shapes[coords]
    for tid,(route,head,shape,dates) in relevant.items():
        sts=sorted(stop_times[tid],key=lambda row:row[0]);clean=[]
        for _,stop,a,b in sts:
            if clean and a<clean[-1][2]-60:continue
            clean.append([stop,a,max(a,b)])
        if len(clean)<2 or clean[-1][1]-clean[0][1]>30*3600:continue
        # Exclude train duplicates between SL and Sweden 3 using trip time/route/stop identifiers.
        orig=(route,tuple((a[0],a[1]) for a in clean))
        if orig in seen_trips:continue
        seen_trips.add(orig)
        item=[route,head,shape_map.get(shape,-1),clean]
        for d in dates:per_day[d].append(item)
    print('Completed',label,'total trips',sum(len(v) for v in per_day.values()),flush=True)

def main():
    sl=os.environ.get('GTFS_SL_KEY','').strip()
    sw=os.environ.get('GTFS_SWEDEN_KEY','').strip()
    feeds=[('SL',sl,'https://opendata.samtrafiken.se/gtfs/sl/sl.zip')]
    if sw:feeds.append(('Sweden 3',sw,'https://opendata.samtrafiken.se/gtfs-sweden/sweden.zip'))
    global_routes={};global_stops={};global_shapes={};per_day={d:[] for d in DAYS};seen=set();used=[]
    for label,key,url in feeds:
        z=fetch_feed(label,key,url)
        if z:
            try:process_feed(z,label,global_routes,global_stops,global_shapes,per_day,seen);used.append(label)
            except Exception as e:print('Processing failed:',label,str(e),file=sys.stderr);raise
            finally:z.close()
    if not used:
        print('No datasets downloaded. Need GTFS_SL_KEY at minimum.',file=sys.stderr)
        return 2
    routes=[None]*len(global_routes)
    for (agency,short,long,mode,color),i in global_routes.items():routes[i]=[short or long[:20],long,mode,color,agency]
    stops=[None]*len(global_stops)
    for (lat,lon,name),i in global_stops.items():stops[i]=[lat,lon,name]
    shapes=[None]*len(global_shapes)
    for coords,i in global_shapes.items():shapes[i]=coords
    meta={'source':used,'generated':dt.datetime.now(dt.timezone.utc).isoformat(),'simulation':True,'bounds':BBOX}
    net={'meta':meta,'routes':routes,'stops':stops,'shapes':shapes}
    (OUT/'network.json').write_text(json.dumps(net,ensure_ascii=False,separators=(',',':')))
    for d,items in per_day.items():
        (OUT/(d.isoformat()+'.json')).write_text(json.dumps({'date':d.isoformat(),'trips':items},ensure_ascii=False,separators=(',',':')))
    (OUT/'manifest.json').write_text(json.dumps({'dates':[d.isoformat() for d in DAYS],'generated':meta['generated'],'sources':used,'counts':{str(d):len(per_day[d]) for d in DAYS}},ensure_ascii=False,separators=(',',':')))
    for f in OUT.iterdir():print(f.name,round(f.stat().st_size/1024/1024,2),'MB')
    return 0

if __name__=='__main__':sys.exit(main())
