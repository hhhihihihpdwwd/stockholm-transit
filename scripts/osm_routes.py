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
    """Topology-aware A* routing on verified OSM road or rail segments.

    Several candidate tracks per station are considered. Component matching
    prevents a wrong nearby but isolated track from shadowing a valid track.
    """
    def __init__(self):
        self.points={}
        self.edges=collections.defaultdict(list)
        self.grid=collections.defaultdict(list)
        self.parent={}
        self._snap_cache={}
        self._path_cache={}

    def root(self, x):
        p=self.parent
        while p[x]!=x:
            p[x]=p[p[x]]
            x=p[x]
        return x

    def union(self,a,b):
        a=self.root(a);b=self.root(b)
        if a!=b:self.parent[b]=a

    def add_elements(self, elements, mode):
        count=0
        self._snap_cache.clear();self._path_cache.clear()
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
                    point=(float(coord['lat']),float(coord['lon']))
                    self.points[nid]=point
                    self.parent[nid]=nid
                    self.grid[(int(point[0]*250),int(point[1]*250))].append(nid)
            underground=tags.get('tunnel') in {'yes','true','1','building_passage'} or tags.get('layer') in {'-1','-2','-3','-4'}
            for a,b in zip(nodes,nodes[1:]):
                if a not in self.points or b not in self.points:continue
                length=hav(self.points[a],self.points[b])
                if 0.25<length<2500:
                    self.edges[a].append((b,length,underground))
                    self.edges[b].append((a,length,underground))
                    self.union(a,b)
                    count+=1
        return count

    def nearby(self, point, limit, max_nodes=32):
        key=(round(point[0],6),round(point[1],6),limit,max_nodes)
        if key in self._snap_cache:return self._snap_cache[key]
        cy=int(point[0]*250);cx=int(point[1]*250)
        lat_cells=math.ceil(limit/444)+1
        lon_cells=math.ceil(limit/(444*max(.1,math.cos(math.radians(point[0])))))+1
        found=[]
        for i in range(cy-lat_cells,cy+lat_cells+1):
            for j in range(cx-lon_cells,cx+lon_cells+1):
                for nid in self.grid.get((i,j),()):
                    d=hav(self.points[nid],point)
                    if d<limit and nid in self.edges:found.append((d,nid))
        found.sort()
        # 35 metres was too restrictive with parallel tracks and stations.
        # Several nearby *connected components* must be represented.
        selected=[];seen_components=collections.Counter()
        for d,n in found:
            comp=self.root(n)
            if seen_components[comp]>=8:continue
            if found and d>found[0][0]+min(450,limit*.8) and selected:break
            selected.append((d,n))
            seen_components[comp]+=1
            if len(selected)>=max_nodes:break
        self._snap_cache[key]=selected
        return selected

    def route(self,p,q,mode):
        direct=hav(p,q)
        if direct<15:return None
        cache_key=(round(p[0],6),round(p[1],6),round(q[0],6),round(q[1],6),mode)
        if cache_key in self._path_cache:return self._path_cache[cache_key]
        max_snap=580 if mode=='bus' else (1000 if mode=='ferry' else 740)
        # Try narrow platform/roadside snapping first. Only when no compatible
        # connected component exists, expand to neighbouring graph components.
        # The extension is bounded; it never creates guessed inter-stop roads.
        best_pair=None
        for radius,tolerance in ((max_snap,min(125,max(28,direct*.23))),(max_snap*1.55,max(130,min(360,direct*.38)))):
            starts=self.nearby(p,radius,max_nodes=50)
            ends=self.nearby(q,radius,max_nodes=50)
            if not starts or not ends:continue
            nearest_a,nearest_b=starts[0][0],ends[0][0]
            starts=[pair for pair in starts if pair[0]<=nearest_a+tolerance]
            ends=[pair for pair in ends if pair[0]<=nearest_b+tolerance]
            end_components={self.root(n) for d,n in ends}
            starts=[pair for pair in starts if self.root(pair[1]) in end_components]
            if not starts:continue
            components={self.root(n) for d,n in starts}
            ends=[pair for pair in ends if self.root(pair[1]) in components]
            if ends:
                best_pair=(starts,ends)
                break
        if not best_pair:return None
        starts,ends=best_pair
        targets={n:d for d,n in ends}
        # A* with explicit snap costs. Strict detour and expansion caps prevent
        # a disconnected/wrong network corridor masquerading as a real route.
        maxlen=max(2300,direct*(5.5 if mode=='bus' else 4.4)+2300)
        heap=[];costs={};prev={};tunnel={}
        for d,n in starts:
            if d<costs.get(n,math.inf):
                costs[n]=d
                heapq.heappush(heap,(d+hav(self.points[n],q),d,n))
        destination=None;best_score=math.inf
        iterations=0
        while heap:
            lower,cost,node=heapq.heappop(heap)
            if cost!=costs.get(node):continue
            if cost>maxlen:continue
            if lower>best_score:break
            # Do not consider a zero-edge path valid when two distinct bus
            # stops happen to snap to the same street intersection.
            if node in targets and node in prev:
                score=cost+targets[node]
                if score<best_score:best_score=score;destination=node
            for nxt,edge,under in self.edges.get(node,()):
                alt=cost+edge
                if alt<costs.get(nxt,math.inf) and alt<=maxlen:
                    costs[nxt]=alt;prev[nxt]=node;tunnel[nxt]=under
                    heapq.heappush(heap,(alt+hav(self.points[nxt],q),alt,nxt))
            iterations+=1
            if iterations>180000:break
        if destination is None:return None
        ids=[];node=destination
        while node in prev:
            ids.append(node);node=prev[node]
        ids.append(node);ids.reverse()
        if len(ids)<2:return None
        coords=[self.points[x] for x in ids]
        length=sum(hav(a,b) for a,b in zip(coords,coords[1:]))
        if length>maxlen or length<direct*.45:return None
        underground=[bool(tunnel.get(x,False)) for x in ids]
        result=(coords,underground)
        if len(self._path_cache)>30000:self._path_cache.clear()
        self._path_cache[cache_key]=result
        return result

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
