"""Optional, one-time OSM street/rail geometries for an OFFLINE transit simulation.

Only connected OpenStreetMap ways are used. No straight-line interpolation is
presented as a road or a rail route. Failed OSM access is diagnosed; the build
can keep an existing trustworthy shape but must never invent a centerline.

OpenStreetMap data © OpenStreetMap contributors, ODbL.
"""
import collections, heapq, json, math, os, time, urllib.error, urllib.parse, urllib.request

OVERPASS = os.environ.get('OSM_OVERPASS_ENDPOINT', 'https://overpass.kumi.systems/api/interpreter')
# Kept deliberately separate: bus roads cannot be used for trains and vice versa.
TYPES = {
    'metro': {'subway'},
    'commuter': {'rail'},
    'tram': {'tram', 'light_rail'},
    'localrail': {'narrow_gauge', 'light_rail', 'rail'},
    'rail': {'rail'},
    'ferry': {'ferry'},
    'bus': {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified',
            'residential', 'living_street', 'service', 'busway', 'motorway_link',
            'trunk_link', 'primary_link', 'secondary_link', 'tertiary_link'},
}


def hav(a, b):
    la, lo = map(math.radians, a)
    lb, lob = map(math.radians, b)
    q = math.sin((la-lb)/2)**2 + math.cos(la)*math.cos(lb)*math.sin((lo-lob)/2)**2
    return 12742000*math.asin(min(1,math.sqrt(q)))


def tiles(s, w, n, e, dy, dx):
    la = s
    while la < n-1e-7:
        lo = w
        while lo < e-1e-7:
            yield (la, lo, min(n, la+dy), min(e, lo+dx))
            lo += dx
        la += dy


def fetch_elements(bbox, kind):
    s, w, n, e = bbox
    if kind == 'bus':
        expr = 'way["highway"]'
    elif kind == 'ferry':
        expr = 'way["route"="ferry"]'
    else:
        expr = 'way["railway"~"^(subway|rail|tram|light_rail|narrow_gauge)$"]'
    query = f'[out:json][timeout:110];{expr}({s:.5f},{w:.5f},{n:.5f},{e:.5f});out geom;'
    req = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({'data':query}).encode(),
            headers={'User-Agent':'StockholmTransitV7/1.0 (one-time historical route map)',
                     'Content-Type':'application/x-www-form-urlencoded', 'Accept-Encoding':'identity'})
    with urllib.request.urlopen(req,timeout=145) as response:
        result=json.load(response)
    return result['elements']


class Graph:
    def __init__(self):
        self.points={};self.edges=collections.defaultdict(list);self.grid=collections.defaultdict(list)
    def add_elements(self, elements, mode):
        count=0
        for way in elements:
            if way.get('type')!='way':continue
            tags=way.get('tags') or {}
            key='highway' if mode=='bus' else ('route' if mode=='ferry' else 'railway')
            if tags.get(key) not in TYPES[mode]:continue
            if mode=='bus' and (tags.get('access') in {'private','no'} or tags.get('motor_vehicle')=='no'):
                continue
            nodes=way.get('nodes') or [];geom=way.get('geometry') or []
            if len(nodes)!=len(geom):continue
            for nid,coord in zip(nodes,geom):
                if 'lat' not in coord or 'lon' not in coord:continue
                if nid not in self.points:
                    p=(float(coord['lat']),float(coord['lon']))
                    self.points[nid]=p
                    self.grid[(int(p[0]*250),int(p[1]*250))].append(nid)
            underground = tags.get('tunnel') in {'yes','true','1','building_passage'} or tags.get('layer') in {'-1','-2','-3','-4'}
            for a,b in zip(nodes,nodes[1:]):
                if a not in self.points or b not in self.points:continue
                length=hav(self.points[a],self.points[b])
                if 0.25<length<1700:
                    self.edges[a].append((b,length,underground))
                    self.edges[b].append((a,length,underground))
                    count+=1
        return count
    def nearby(self, point, limit):
        cy=int(point[0]*250);cx=int(point[1]*250)
        found=[]
        for i in range(cy-3,cy+4):
            for j in range(cx-3,cx+4):
                for nid in self.grid.get((i,j),()):
                    d=hav(self.points[nid],point)
                    if d<limit:found.append((d,nid))
        found.sort()
        # Several railway tracks at a station; keep alternatives in case nearest disconnected.
        if not found:return []
        baseline=found[0][0]
        return [(d,n) for d,n in found[:10] if d<baseline+35]
    def route(self, p, q, mode):
        direct=hav(p,q)
        if direct<65:return None
        max_snap=500 if mode=='bus' else (1100 if mode=='ferry' else 650)
        starts=self.nearby(p,max_snap)
        ends=self.nearby(q,max_snap)
        if not starts or not ends:return None
        targets={nid:d for d,nid in ends}
        # A* with a geographic lower bound, instead of Dijkstra's broad
        # exploration of the entire Stockholm road network for every stop pair.
        heap=[];costs={};prev={};tunnel={}
        target_coord=q
        for dist,nid in starts:
            costs[nid]=dist
            heapq.heappush(heap,(dist+hav(self.points[nid],target_coord),dist,nid))
        maxlen=max(1500,direct*(3.5 if mode=='bus' else 2.4)+900)
        destination=None
        while heap:
            _,cost,node=heapq.heappop(heap)
            if cost!=costs.get(node):continue
            if cost>maxlen:continue
            if node in targets:
                destination=node;break
            for nxt,edge,under in self.edges.get(node,()):
                alt=cost+edge
                if alt<costs.get(nxt,math.inf) and alt<=maxlen:
                    costs[nxt]=alt;prev[nxt]=node;tunnel[nxt]=under
                    heapq.heappush(heap,(alt+hav(self.points[nxt],target_coord),alt,nxt))
        if destination is None:return None
        ids=[];node=destination
        while node in prev:
            ids.append(node);node=prev[node]
        ids.append(node);ids.reverse()
        if len(ids)<2:return None
        coords=[self.points[x] for x in ids]
        length=sum(hav(a,b) for a,b in zip(coords,coords[1:]))
        if length>maxlen or length<direct*.6:return None
        underground=[bool(tunnel.get(x,False)) for x in ids]
        return coords,underground


def assemble(graph, stops, mode):
    all_points=[];flags=[]
    for a,b in zip(stops, stops[1:]):
        segment=graph.route(a,b,mode)
        if not segment:return None
        pts,under=segment
        if not all_points:all_points.extend(pts);flags.extend(under)
        else:all_points.extend(pts[1:]);flags.extend(under[1:])
    if len(all_points)<3:return None
    # 30m simplification keeps bends while bounding the JSON payload.
    out=[all_points[0]];sides=[flags[0]]
    for p,u in zip(all_points[1:-1],flags[1:-1]):
        if hav(out[-1],p)>31 or u!=sides[-1]:
            out.append(p);sides.append(u)
    out.append(all_points[-1]);sides.append(flags[-1])
    return tuple((round(p[0],5),round(p[1],5)) for p in out),sides


def enrich(global_routes, global_stops, global_shapes, per_day):
    if os.environ.get('OSM_GEOMETRY','1')!='1':
        print('OSM one-time geometry intentionally disabled',flush=True)
        return {}
    routes={idx:mode for (_,_,_,mode,_),idx in global_routes.items()}
    points={idx:(lat,lon) for (lat,lon,_),idx in global_stops.items()}
    candidates=collections.defaultdict(dict)
    for items in per_day.values():
        for item in items:
            if item[2]>=0:continue
            mode=routes[item[0]]
            if mode not in TYPES:continue
            sids=tuple(row[0] for row in item[3])
            if len(sids)<2 or len(sids)>70:continue
            if mode=='bus' and not all(59.15<=points[x][0]<=59.55 and 17.60<=points[x][1]<=18.48 for x in sids):continue
            if mode in {'metro','tram','localrail'} and not all(59.05<=points[x][0]<=59.83 and 17.35<=points[x][1]<=19.02 for x in sids):continue
            if mode=='ferry' and not all(59.05<=points[x][0]<=59.83 and 17.35<=points[x][1]<=19.08 for x in sids):continue
            if mode in {'rail','commuter'} and not all(59.03<=points[x][0]<=59.83 and 17.35<=points[x][1]<=19.05 for x in sids):continue
            candidates[mode].setdefault(sids,[]).append(item)
    print('OSM unique route patterns:',{k:len(v) for k,v in candidates.items()},flush=True)
    tunnel_shapes={}
    for kind in ('rail','bus','ferry'):
        modes=['metro','commuter','tram','localrail','rail'] if kind=='rail' else [kind]
        if not any(candidates.get(m) for m in modes):continue
        graph_by_mode={mode:Graph() for mode in modes}
        if kind=='rail':
            bounds=(59.03,17.31,59.83,19.08);tile_h=.4;tile_w=.9
        elif kind=='ferry':
            bounds=(59.05,17.31,59.83,19.08);tile_h=.39;tile_w=.885
        else:
            bounds=(59.14,17.59,59.56,18.49);tile_h=.21;tile_w=.45
        fetched=0
        for tile in tiles(*bounds,tile_h,tile_w):
            try:
                elements=fetch_elements(tile,kind)
                for mode in modes:graph_by_mode[mode].add_elements(elements,mode)
                fetched+=1
                print('OSM map tile loaded',kind,tile,'ways',len(elements),flush=True)
                time.sleep(2)
            except Exception as exc:
                print('OSM tile unavailable',kind,tile,repr(exc)[:120],flush=True)
        print('OSM',kind,'tiles:',fetched,'graph vertices:',{m:len(g.points) for m,g in graph_by_mode.items()},flush=True)
        for mode in modes:
            graph=graph_by_mode[mode]
            if not graph.edges:continue
            done=0;count=0
            for sids,items in candidates.get(mode,{}).items():
                count+=1
                result=assemble(graph,[points[x] for x in sids],mode)
                if not result:continue
                shape,flags=result
                sid=global_shapes.setdefault(shape,len(global_shapes))
                for item in items:item[2]=sid;done+=1
                if mode=='metro' and any(flags):
                    # Travel is only dimmed on ways tagged as underground in OSM.
                    tunnel_shapes[sid]=[i for i,u in enumerate(flags) if u]
            print('OSM',mode,'routed patterns',sum(1 for a in candidates.get(mode,{}).values() if a and a[0][2]>=0),'/',count,'trips',done,flush=True)
    return tunnel_shapes
