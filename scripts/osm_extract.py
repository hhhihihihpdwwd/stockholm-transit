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
STOCKHOLM_ROAD_BBOX = (16.40, 58.60, 19.85, 60.72)
RAIL_TAGS = ('rail', 'subway', 'tram', 'light_rail', 'narrow_gauge')


def run(*cmd):
    print('OSM preparation:', ' '.join(map(str,cmd))[:220],flush=True)
    subprocess.run(list(map(str,cmd)), check=True, timeout=1100)


def download_sweden(url=SWEDEN_URL):
    """Resumable official PBF download with visible progress every 50 MiB."""
    if not url.startswith('https://download.geofabrik.de/europe/sweden') or not url.endswith('.osm.pbf'):
        raise ValueError('Sweden OSM download must be an official Geofabrik PBF')
    CACHE.mkdir(parents=True, exist_ok=True)
    dest=CACHE/'sweden.osm.pbf'
    if dest.is_file() and dest.stat().st_size>300_000_000:
        print('Using cached Sweden PBF',dest.stat().st_size,flush=True)
        return dest
    part=pathlib.Path(str(dest)+'.part')
    for attempt in range(3):
        have=part.stat().st_size if part.exists() else 0
        headers={'User-Agent':'StockholmTransitV11/1.0 (OSM archive hobby simulator)',
                 'Accept-Encoding':'identity'}
        if have>0:headers['Range']=f'bytes={have}-'
        try:
            print('SWEDEN OSM: downloading official PBF; resume from',round(have/1048576),'MiB',flush=True)
            req=urllib.request.Request(url,headers=headers)
            with urllib.request.urlopen(req,timeout=120) as response:
                # Some mirrors ignore HTTP Range; then restart instead of appending.
                resume=bool(have and response.status==206)
                if response.status not in (200,206):raise RuntimeError(f'Unexpected HTTP {response.status}')
                if not resume:have=0
                next_log=have+50*1024*1024
                with part.open('ab' if resume else 'wb') as out:
                    total=have
                    while True:
                        block=response.read(1024*1024)
                        if not block:break
                        out.write(block);total+=len(block)
                        if total>=next_log:
                            print('SWEDEN OSM PROGRESS:',round(total/1048576),'MiB',flush=True)
                            next_log=total+50*1024*1024
            if part.stat().st_size<300_000_000:
                raise RuntimeError('Unexpectedly small Sweden OSM PBF')
            part.replace(dest)
            print('SWEDEN OSM COMPLETE:',round(dest.stat().st_size/1048576),'MiB',flush=True)
            return dest
        except Exception as exc:
            print('Sweden OSM download attempt',attempt+1,'failed:',type(exc).__name__,str(exc)[:140],flush=True)
            if attempt==2:raise
            time.sleep(5*(attempt+1))


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


def route_pattern_detailed(graph,points,ids,mode,cache):
    """Produce OSM-only polyline + a route distance for EVERY stop.

    Earlier versions threw out a whole trip if neighbouring stop coordinates
    were nearly coincident. Here such stops share a zero-length anchor. We also
    preserve snapped end nodes and bridge adjacent legs using only OSM edges,
    never by drawing an arbitrary geographic chord.
    """
    from route_quality import cumulative, valid_anchors
    if len(ids)<2:return None
    coords=[];flags=[];stop_indices=[0]
    for a,b in zip(ids,ids[1:]):
        if hav(points[a],points[b])<15:
            stop_indices.append(max(0,len(coords)-1))
            continue
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
        geom,under=leg
        if coords and hav(coords[-1],geom[0])>12:
            # Two independently snapped stops may connect to different nodes;
            # join them only if the OSM graph actually connects the nodes.
            bridge_key=('bridge',tuple(coords[-1]),tuple(geom[0]),mode)
            if bridge_key not in cache:
                cache[bridge_key]=graph.route(coords[-1],geom[0],mode)
            bridge=cache[bridge_key]
            if bridge is None:return None
            for xy,flag in zip(*bridge):
                if not coords or hav(coords[-1],xy)>0.5:
                    coords.append(xy);flags.append(flag)
        for xy,flag in zip(geom,under):
            if not coords or hav(coords[-1],xy)>0.5:
                coords.append(xy);flags.append(flag)
        stop_indices.append(len(coords)-1)
    if len(coords)<2:return None
    # Stop anchors are protected during simplification, so they remain exact.
    protected=set(stop_indices)
    keep=[]
    for i,xy in enumerate(coords):
        if (not keep or i in protected or i==len(coords)-1 or
                hav(coords[keep[-1]],xy)>35 or flags[i]!=flags[keep[-1]]):
            keep.append(i)
    # The last point is always kept, and original stop points are never dropped.
    shape=tuple((round(coords[i][0],5),round(coords[i][1],5)) for i in keep)
    underground=[bool(flags[i]) for i in keep]
    sums=cumulative(shape)
    back={original:j for j,original in enumerate(keep)}
    anchors=[round(sums[back[i]],2) for i in stop_indices]
    if not valid_anchors(shape,anchors,len(ids)):return None
    return shape,underground,anchors


def route_pattern(graph,points,ids,mode,cache):
    """Backward-compatible public helper used by the existing regression tests."""
    result=route_pattern_detailed(graph,points,ids,mode,cache)
    return result[:2] if result else None


def partial_route_segments(graph, points, ids, mode, cache, cap=14):
    """Recover verified OSM pieces of a trip without ever drawing across gaps.

    A single missing road between two stops must not hide every other mapped
    part of that bus line. The browser receives separate shapes and will render
    mapped portions only. A missing span remains visibly unmapped.
    """
    good=[]
    for j,(a,b) in enumerate(zip(ids,ids[1:])):
        if hav(points[a],points[b])<15:
            good.append(True)
            continue
        key=(a,b)
        if key not in cache:
            cache[key]=graph.route(points[a],points[b],mode)
        good.append(cache[key] is not None)
    blocks=[];first=None
    for j,ok in enumerate(good):
        if ok and first is None:first=j
        if first is not None and (not ok or j==len(good)-1):
            end=j if not ok else j+1
            if end>first:blocks.append((first,end))
            first=None
    if not blocks:return []
    out=[]
    def add_piece(a,b):
        if len(out)>=cap or b<=a:return
        result=route_pattern_detailed(graph,points,ids[a:b+1],mode,cache)
        if result:
            shape,flags,anchors=result
            out.append((a,b,shape,flags,anchors))
        elif b-a>1:
            # An independently snapped intermediate platform may make the full
            # path discontinuous; retain verifiable sublegs instead.
            mid=(a+b)//2
            add_piece(a,mid);add_piece(mid,b)
    for a,b in blocks:
        add_piece(a,b)
        if len(out)>=cap:break
    return out


def enrich(global_routes,global_stops,global_shapes,per_day):
    if os.environ.get('OSM_GEOMETRY','1')!='1':
        print('OSM_GEOMETRY=0: no routing performed',flush=True)
        return {}
    points={idx:(lat,lon) for (lat,lon,_),idx in global_stops.items()}
    patterns=line_stop_patterns(global_routes,per_day,points)
    print('V9 ROUTE PATTERNS NEEDING GEOMETRY:',{m:len(v) for m,v in patterns.items()},flush=True)
    if not patterns:return {}
    # GitHub Actions restores these expensive extracts from a retained cache.
    # Subsequent V11 rebuilds therefore skip downloading the ~900MB Swedish PBF.
    region=CACHE/'stockholm-region.osm.pbf'
    all_rail=CACHE/'sweden-railways.osm.pbf'
    if region.is_file() and all_rail.is_file() and region.stat().st_size>200000 and all_rail.stat().st_size>100000:
        print('V11: using persistent cached Stockholm roads + national railways',flush=True)
    else:
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
        partly=0
        for k,(ids,items) in enumerate(groups.items()):
            # Compute each unique stop sequence once and reuse it for all days.
            result=route_pattern_detailed(graph,points,ids,mode,cache)
            if result is None:
                pieces=partial_route_segments(graph,points,ids,mode,cache)
                if pieces:
                    published=[]
                    for start,end,shape,flags,anchors in pieces:
                        sid=global_shapes.setdefault(shape,len(global_shapes))
                        published.append([sid,start,end,anchors])
                        if mode=='metro' and any(flags):
                            tunnel_shapes[sid]=[i for i,flag in enumerate(flags) if flag]
                    for item in items:
                        while len(item)<8:item.append('')
                        if len(item)==8:item.append(published)
                        else:item[8]=published
                    partly+=len(items)
                failed.append((ids,len(items)))
                continue
            shape,flags,anchors=result
            sid=global_shapes.setdefault(shape,len(global_shapes))
            for item in items:
                item[2]=sid
                while len(item)<7:item.append('')
                if len(item)==7:item.append(anchors)
                else:item[7]=anchors
                done+=1
            if mode=='metro' and any(flags):
                tunnel_shapes[sid]=[i for i,flag in enumerate(flags) if flag]
            good+=1
            if k and k%500==0:
                print('ROUTING PROGRESS',mode,k,'/',len(groups),flush=True)
        coverage[mode]=(good,len(groups))
        counts[mode]=done
        missing[mode]=len(failed)
        print('V11 ROUTING COVERAGE:',mode,good,'/',len(groups),'complete patterns,',done,'full dated trips,',partly,'partial dated trips',flush=True)
    # Metadata printed for human inspection in Actions; do not fabricate shapes.
    print('V9 FINAL ROUTE COVERAGE:',coverage,flush=True)
    return tunnel_shapes
