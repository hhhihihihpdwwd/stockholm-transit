"""Build a shared road/rail graph from one BBBike Stockholm PBF extract.

No remote Overpass/OSRM requests, no straight-line road/rail substitutes.
OpenStreetMap data © OpenStreetMap contributors (ODbL).
"""
import collections
import os
import pathlib
import shutil
import tempfile
import time
import urllib.request
from osm_routes import Graph, assemble, TYPES

BBBIKE_URL = 'https://download.bbbike.org/osm/bbbike/Stockholm/Stockholm.osm.pbf'


def download_pbf(url=BBBIKE_URL):
    """Stream the entire file to disk. Avoid reading a large ZIP/PBF into RAM."""
    if not url.startswith('https://download.bbbike.org/osm/bbbike/Stockholm/'):
        raise ValueError('Unexpected Stockholm PBF address')
    out=pathlib.Path(tempfile.gettempdir())/'stockholm-v8-osm.pbf'
    if out.exists() and out.stat().st_size>5_000_000:
        print('Using cached Stockholm PBF:',round(out.stat().st_size/1e6,1),'MB',flush=True)
        return out
    req=urllib.request.Request(url,headers={'User-Agent':'StockholmTransitV8/1.0 (hobby timetable simulator)','Accept-Encoding':'identity'})
    for attempt in range(3):
        try:
            print('Downloading Stockholm street and rail map from BBBike (one file)',flush=True)
            with urllib.request.urlopen(req,timeout=180) as response,open(str(out)+'.part','wb') as dst:
                shutil.copyfileobj(response,dst,1024*1024)
            pathlib.Path(str(out)+'.part').replace(out)
            if out.stat().st_size < 5_000_000:
                raise ValueError('Map download unexpectedly small')
            print('Stockholm PBF downloaded:',round(out.stat().st_size/1e6,1),'MB',flush=True)
            return out
        except Exception as exc:
            print('PBF attempt',attempt+1,'failed:',repr(exc)[:150],flush=True)
            if attempt==2:raise
            time.sleep(4*(attempt+1))


def graphs_from_way_elements(ways):
    """Pure testable route graph builder; ways have Overpass-like geometry."""
    modes=('bus','metro','commuter','tram','localrail','rail','ferry')
    graphs={m:Graph() for m in modes}
    for way in ways:
        tags=way.get('tags') or {}
        targets=[]
        if tags.get('highway') in TYPES['bus']:
            targets.append('bus')
        if tags.get('railway'):
            targets.extend(m for m in ('metro','commuter','tram','localrail','rail') if tags.get('railway') in TYPES[m])
        if tags.get('route')=='ferry':targets.append('ferry')
        for mode in targets:
            graphs[mode].add_elements([way],mode)
    return graphs


def load_graphs(path):
    try:
        import osmium
    except ImportError as exc:
        raise RuntimeError('pyosmium missing: install with pip install osmium') from exc

    modes=('bus','metro','commuter','tram','localrail','rail','ferry')
    graphs={m:Graph() for m in modes}
    totals=collections.Counter()

    class Reader(osmium.SimpleHandler):
        def way(self, w):
            tags={k:v for k,v in w.tags}
            targets=[]
            h=tags.get('highway')
            railway=tags.get('railway')
            if h in TYPES['bus']: targets.append('bus')
            if railway:
                targets.extend(m for m in ('metro','commuter','tram','localrail','rail') if railway in TYPES[m])
            if tags.get('route') == 'ferry':targets.append('ferry')
            if not targets:return
            nodes=[];geom=[]
            for n in w.nodes:
                try:
                    if not n.location.valid():return
                    lat,lon=n.location.lat,n.location.lon
                except (ValueError,AttributeError):return
                nodes.append(int(n.ref));geom.append({'lat':lat,'lon':lon})
            if len(nodes)<2:return
            element={'type':'way','tags':tags,'nodes':nodes,'geometry':geom}
            for m in targets:
                totals[m]+=graphs[m].add_elements([element],m)

    print('Parsing local PBF with osmium; no Overpass calls',flush=True)
    Reader().apply_file(str(path),locations=True,idx='flex_mem')
    print('PBF GRAPH EDGES:',dict(totals),flush=True)
    print('PBF GRAPH VERTICES:',{m:len(g.points) for m,g in graphs.items()},flush=True)
    return graphs


def enrich(global_routes,global_stops,global_shapes,per_day):
    mode_by_route={i:mode for (_,_,_,mode,_),i in global_routes.items()}
    points={i:(lat,lon) for (lat,lon,_),i in global_stops.items()}
    candidates=collections.defaultdict(lambda:collections.defaultdict(list))
    for trips in per_day.values():
        for item in trips:
            if item[2]>=0:continue
            mode=mode_by_route[item[0]]
            if mode not in TYPES:continue
            ids=tuple(st[0] for st in item[3])
            if len(ids)<2 or len(ids)>75:continue
            # Only local route variants. Intercity trips continue to exist in
            # the national timetable but require a different map extract.
            if not all(59.08<=points[sid][0]<=59.70 and 17.45<=points[sid][1]<=18.80 for sid in ids):continue
            candidates[mode][ids].append(item)
    print('PBF ROUTE PATTERNS:',{m:len(v) for m,v in candidates.items()},flush=True)
    if not candidates:return {}
    pbf=download_pbf(os.environ.get('STOCKHOLM_PBF_URL',BBBIKE_URL))
    graphs=load_graphs(pbf)
    tunnel_shapes={}
    total=collections.Counter();routed=collections.Counter()
    for mode,groups in candidates.items():
        graph=graphs[mode]
        if not graph.edges:continue
        # Cache identical point-pair routes across route variants. Especially
        # valuable for hundreds of bus routes sharing central street segments.
        leg_cache={}
        for ids,items in groups.items():
            total[mode]+=1
            legs=[];okay=True
            for a,b in zip(ids,ids[1:]):
                key=(a,b)
                if key not in leg_cache:
                    leg_cache[key]=graph.route(points[a],points[b],mode)
                result=leg_cache[key]
                if result is None:
                    okay=False;break
                legs.append(result)
            if not okay:continue
            coords=[];flags=[]
            for geom,under in legs:
                if coords:
                    coords.extend(geom[1:]);flags.extend(under[1:])
                else:
                    coords.extend(geom);flags.extend(under)
            if len(coords)<3:continue
            # Preserve station-to-station route orientation and tunnel tags;
            # simplify gently, and share the resulting geometry for all journeys.
            shape=[coords[0]];underground=[flags[0]]
            from osm_routes import hav
            for p,u in zip(coords[1:-1],flags[1:-1]):
                if hav(shape[-1],p)>30 or u!=underground[-1]:
                    shape.append(p);underground.append(u)
            shape.append(coords[-1]);underground.append(flags[-1])
            saved=tuple((round(a,5),round(b,5)) for a,b in shape)
            sid=global_shapes.setdefault(saved,len(global_shapes))
            if mode=='metro' and any(underground):
                tunnel_shapes[sid]=[j for j,f in enumerate(underground) if f]
            for item in items:item[2]=sid
            routed[mode]+=1
        print('PBF ROUTING',mode,routed[mode],'/',total[mode],
              'patterns, graph nodes',len(graph.points),flush=True)
    return tunnel_shapes
