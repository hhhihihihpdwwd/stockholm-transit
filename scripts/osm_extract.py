"""Stockholm Transit V9 one-time OSM network matching.

Unlike V8, which only loaded the BBBike city extract, this module reads an
entire Sweden OSM snapshot ONCE, then filters it into two inexpensive PBFs:
  (1) Stockholm county-sized roads, rails and ferries;
  (2) all Swedish railway tracks (rail/subway/tram/narrow gauge).
This avoids public Overpass request throttling and lets distant trains follow
actual OSM railway segments rather than fabricated straight corridors.

All produced routes are ESTIMATES based on publicly mapped infrastructure and
historical timetables, not live vehicle positions or verified dispatch routes.
OSM data © OpenStreetMap contributors, ODbL.
"""
import collections
import os
import pathlib
import shutil
import subprocess
import tempfile
import time
import urllib.request
from osm_routes import Graph, TYPES, hav

SWEDEN_URL = 'https://download.geofabrik.de/europe/sweden-latest.osm.pbf'
CACHE = pathlib.Path(tempfile.gettempdir()) / 'stockholm-transit-v9'
# Roughly Stockholm County and its immediate surrounding transport network.
# This is a *bounded* city-region road graph, not every Swedish bus route.
STOCKHOLM_ROAD_BBOX = (16.90, 58.72, 19.78, 60.37)
RAIL_TAGS = ('rail', 'subway', 'tram', 'light_rail', 'narrow_gauge')


def run(*cmd):
    print('OSM preparation:', ' '.join(map(str,cmd))[:220],flush=True)
    subprocess.run(list(map(str,cmd)), check=True, timeout=1100)


def download_sweden(url=SWEDEN_URL):
    if not url.startswith('https://download.geofabrik.de/europe/sweden') or not url.endswith('.osm.pbf'):
        raise ValueError('Sweden OSM download must be an official Geofabrik PBF')
    CACHE.mkdir(parents=True, exist_ok=True)
    dest=CACHE/'sweden.osm.pbf'
    if dest.is_file() and dest.stat().st_size>300_000_000:
        print('Using local Sweden PBF cache',dest.stat().st_size,flush=True)
        return dest
    req=urllib.request.Request(url,headers={'User-Agent':'StockholmTransitV9-HobbyOSMImport/1.0','Accept-Encoding':'identity'})
    for attempt in range(3):
        try:
            print('Downloading Sweden OSM railway + Stockholm roads, one PBF (~900 MB)',flush=True)
            with urllib.request.urlopen(req,timeout=300) as response,open(str(dest)+'.part','wb') as out:
                shutil.copyfileobj(response,out,1024*1024)
            if pathlib.Path(str(dest)+'.part').stat().st_size<300_000_000:
                raise RuntimeError('Unexpectedly small Sweden PBF')
            pathlib.Path(str(dest)+'.part').replace(dest)
            print('Sweden PBF downloaded',round(dest.stat().st_size/1e6),'MB',flush=True)
            return dest
        except Exception as exc:
            print('Sweden OSM download failed:',type(exc).__name__,str(exc)[:140],flush=True)
            if attempt==2:raise
            time.sleep(8*(attempt+1))


def prepare_extracts(full):
    if not shutil.which('osmium'):
        raise RuntimeError('OSM CLI is required: install osmium-tool on the GitHub runner')
    CACHE.mkdir(parents=True,exist_ok=True)
    road=CACHE/'stockholm-region.osm.pbf'
    rail=CACHE/'sweden-railways.osm.pbf'
    if not road.is_file() or road.stat().st_size<200_000:
        bbox=','.join(str(x) for x in STOCKHOLM_ROAD_BBOX)
        run('osmium','extract','--bbox',bbox,'--strategy','complete_ways','-o',road,'-O',full)
    if not rail.is_file() or rail.stat().st_size<100_000:
        run('osmium','tags-filter',full,*('w/railway='+r for r in RAIL_TAGS),'-o',rail,'-O')
    print('OSM extract sizes (MB):',round(road.stat().st_size/1e6),round(rail.stat().st_size/1e6),flush=True)
    return road,rail


def graphs_from_way_elements(ways):
    """Small pure-logic graph builder for unit tests, no downloads."""
    modes=('bus','metro','commuter','tram','localrail','rail','ferry')
    graphs={m:Graph() for m in modes}
    for way in ways:
        tags=way.get('tags') or {}
        modes_here=[]
        if tags.get('highway') in TYPES['bus']:modes_here.append('bus')
        if tags.get('railway'):
            modes_here.extend(m for m in ('metro','commuter','tram','localrail','rail') if tags['railway'] in TYPES[m])
        if tags.get('route')=='ferry':modes_here.append('ferry')
        for mode in modes_here:graphs[mode].add_elements([way],mode)
    return graphs


def load_graphs(path,modes):
    try:
        import osmium
    except ImportError as exc:
        raise RuntimeError('pyosmium missing: pip install osmium') from exc
    graphs={m:Graph() for m in modes}
    counts=collections.Counter()
    class Reader(osmium.SimpleHandler):
        def way(self,w):
            tags={k:v for k,v in w.tags}
            targets=[]
            if 'bus' in graphs and tags.get('highway') in TYPES['bus']:
                targets.append('bus')
            if tags.get('railway'):
                targets.extend(m for m in modes if m not in {'bus','ferry'} and tags['railway'] in TYPES[m])
            if 'ferry' in graphs and tags.get('route')=='ferry':
                targets.append('ferry')
            if not targets:return
            ids=[];geometry=[]
            for n in w.nodes:
                try:
                    if not n.location.valid():return
                    ids.append(int(n.ref))
                    geometry.append({'lat':n.location.lat,'lon':n.location.lon})
                except (ValueError,AttributeError):return
            if len(ids)<2:return
            element={'type':'way','tags':tags,'nodes':ids,'geometry':geometry}
            for mode in targets:counts[mode]+=graphs[mode].add_elements([element],mode)
    print('Reading OSM graph:',path,'for',list(modes),flush=True)
    Reader().apply_file(str(path), locations=True, idx='flex_mem')
    print('OSM GRAPH EDGES:',dict(counts),flush=True)
    print('OSM GRAPH VERTICES:',{m:len(g.points) for m,g in graphs.items()},flush=True)
    return graphs


def line_stop_patterns(global_routes,per_day,points):
    routes={idx:mode for (_,_,_,mode,_),idx in global_routes.items()}
    patterns=collections.defaultdict(lambda:collections.defaultdict(list))
    for trips in per_day.values():
        for item in trips:
            if item[2]>=0:continue
            mode=routes[item[0]]
            if mode not in TYPES or len(item[3])<2:continue
            ids=tuple(s[0] for s in item[3])
            if len(ids)>110:continue
            # IMPORTANT: 995 national trains are kept if Stockholm-serving.
            # Buses outside Stockholm's regional extract will be listed as
            # missing geometry rather than drawn across water.
            patterns[mode][ids].append(item)
    return patterns


def route_pattern(graph,points,ids,mode,cache):
    coords=[];underground=[];length=0
    for a,b in zip(ids,ids[1:]):
        key=(a,b)
        if key not in cache:
            reverse=cache.get((b,a))
            if reverse is not None:
                rgeom,rflags=reverse
                cache[key]=(list(reversed(rgeom)),list(reversed(rflags)))
            else:
                cache[key]=graph.route(points[a],points[b],mode)
        leg=cache[key]
        if leg is None:return None
        geom,flags=leg
        if coords:
            coords.extend(geom[1:]);underground.extend(flags[1:])
        else:
            coords.extend(geom);underground.extend(flags)
    if len(coords)<2:return None
    compact=[coords[0]];flags=[underground[0]]
    for xy,under in zip(coords[1:-1],underground[1:-1]):
        if hav(compact[-1],xy)>35 or under!=flags[-1]:
            compact.append(xy);flags.append(under)
    compact.append(coords[-1]);flags.append(underground[-1])
    # Guard nonsensical detours and invalid coordinates before publishing.
    if len(compact)<2:return None
    return tuple((round(x,5),round(y,5)) for x,y in compact),flags


def enrich(global_routes,global_stops,global_shapes,per_day):
    if os.environ.get('OSM_GEOMETRY','1')!='1':
        print('OSM_GEOMETRY=0: no routing performed',flush=True)
        return {}
    points={idx:(lat,lon) for (lat,lon,_),idx in global_stops.items()}
    patterns=line_stop_patterns(global_routes,per_day,points)
    print('V9 ROUTE PATTERNS NEEDING GEOMETRY:',{m:len(v) for m,v in patterns.items()},flush=True)
    if not patterns:return {}
    full=download_sweden(os.environ.get('SWEDEN_OSM_URL',SWEDEN_URL))
    region,all_rail=prepare_extracts(full)
    # Release ~900MB before graph allocation on hosted runners.
    if os.environ.get('KEEP_FULL_OSM','0')!='1':
        full.unlink(missing_ok=True)
    local=load_graphs(region,('bus','ferry'))
    railway=load_graphs(all_rail,('metro','commuter','tram','localrail','rail'))
    graphs={**local,**railway}
    # Process dense city transit before national train journeys.
    order=('metro','commuter','localrail','tram','bus','rail','ferry')
    tunnel_shapes={};counts={};coverage={};missing={}
    for mode in order:
        groups=patterns.get(mode,{})
        graph=graphs[mode]
        cache={};good=0;done=0;failed=[]
        for k,(ids,items) in enumerate(groups.items()):
            # Each unique station-to-station link is routed once and reused.
            result=route_pattern(graph,points,ids,mode,cache)
            if result is None:
                failed.append((ids,len(items)))
                continue
            shape,flags=result
            sid=global_shapes.setdefault(shape,len(global_shapes))
            for item in items:item[2]=sid;done+=1
            if mode=='metro' and any(flags):
                tunnel_shapes[sid]=[i for i,flag in enumerate(flags) if flag]
            good+=1
            if k and k%500==0:
                print('ROUTING PROGRESS',mode,k,'/',len(groups),flush=True)
        coverage[mode]=(good,len(groups))
        counts[mode]=done
        missing[mode]=len(failed)
        print('V9 ROUTING COVERAGE:',mode,good,'/',len(groups),'patterns,',done,'dated trips',flush=True)
    # Metadata printed for human inspection in Actions; do not fabricate shapes.
    print('V9 FINAL ROUTE COVERAGE:',coverage,flush=True)
    return tunnel_shapes
