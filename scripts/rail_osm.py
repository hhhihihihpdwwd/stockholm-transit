"""Optional OSM railway centerline enrichment for Stockholm–Arlanda services.

The geometry is a routable OSM railway graph (not a station-to-station
straight segment). If routing cannot be validated, keep shape=-1; the UI
must indicate unavailable track geometry.
"""
import collections
import heapq
import io
import json
import math
import os
import urllib.request

BOUNDS = (59.27,17.76,59.75,18.23)
ENDPOINT = 'https://overpass.kumi.systems/api/interpreter'


def hav(a,b):
    la,lo=map(math.radians,a);lb,lob=map(math.radians,b)
    q=math.sin((la-lb)/2)**2+math.cos(la)*math.cos(lb)*math.sin((lo-lob)/2)**2
    return 12742000*math.asin(min(1,math.sqrt(q)))


def tracks_to_graph(elements):
    # OSM way vertices provide shared node IDs; connectivity follows actual rail ways.
    pts={};graph=collections.defaultdict(list)
    for item in elements:
        if item.get('type')!='way':continue
        nodes=item.get('nodes') or []
        geometry=item.get('geometry') or []
        if len(nodes)!=len(geometry):continue
        for node,point in zip(nodes,geometry):
            if 'lat' in point and 'lon' in point:pts[node]=(point['lat'],point['lon'])
        for a,b in zip(nodes,nodes[1:]):
            if a not in pts or b not in pts:continue
            dist=hav(pts[a],pts[b])
            if 1<dist<2000:
                graph[a].append((b,dist));graph[b].append((a,dist))
    return pts,graph


def shortest(pts,graph,point_a,point_b):
    # Platform coordinates can be up to a few hundred metres from the track centerline.
    starts=sorted(((hav(x,point_a),i) for i,x in pts.items()))[:5]
    ends=sorted(((hav(x,point_b),i) for i,x in pts.items()))[:5]
    # Keep only genuinely nearest rail vertices; otherwise multiple sources may
    # overlap near the destination and yield a false zero-length path.
    da=starts[0][0] if starts else math.inf
    db=ends[0][0] if ends else math.inf
    starts=[(d,i) for d,i in starts if d<850 and d<=da+85]
    ends={i:d for d,i in ends if d<850 and d<=db+85}
    if not starts or not ends:return None
    direct=hav(point_a,point_b)
    # Avoid assigning an unrelated line merely because it is connected eventually.
    if direct<250:return None
    pq=[];dist={};prev={}
    for d,node in starts:
        dist[node]=d;heapq.heappush(pq,(d,node))
    best_node=None
    while pq:
        cost,node=heapq.heappop(pq)
        if cost!=dist.get(node):continue
        if node in ends:
            best_node=node;break
        if cost>max(6000,direct*2.5):break
        for nxt,edge in graph.get(node,[]):
            ncost=cost+edge
            if ncost<dist.get(nxt,math.inf):
                dist[nxt]=ncost;prev[nxt]=node;heapq.heappush(pq,(ncost,nxt))
    if best_node is None:return None
    result=[];node=best_node
    while True:
        result.append(pts[node])
        if node not in prev:break
        node=prev[node]
    result.reverse()
    if len(result)<3 or len(result)>5000:return None
    # Strict validation; no map-centerline if implausibly distant.
    if hav(result[0],point_a)>850 or hav(result[-1],point_b)>850:return None
    ratio=sum(hav(a,b) for a,b in zip(result,result[1:]))/direct
    if ratio>2.0:return None
    return result


def fetch_tracks():
    if os.environ.get('OSM_RAIL_FALLBACK','1')=='0':return None
    s,w,n,e=BOUNDS
    q=f'[out:json][timeout:25];way["railway"="rail"]({s},{w},{n},{e});out geom;'
    req=urllib.request.Request(ENDPOINT,data=q.encode(),headers={'User-Agent':'StockholmTransitObservatory/1.0 (+one daily offline railway import)','Content-Type':'application/x-www-form-urlencoded','Accept-Encoding':'gzip, deflate'})
    try:
        with urllib.request.urlopen(req,timeout=35) as response:
            content=response.read(30*1024*1024)
            encoding=response.headers.get('Content-Encoding','').lower()
            if encoding=='gzip':
                import gzip
                content=gzip.decompress(content)
            elif encoding=='deflate':
                import zlib
                content=zlib.decompress(content)
        obj=json.loads(content)
        return tracks_to_graph(obj['elements'])
    except Exception as exc:
        print('OSM optional track fetch skipped:',str(exc)[:180],flush=True)
        return None


def enrich_arlanda_shapes(global_routes,global_stops,global_shapes,per_day):
    route_names={idx:(agency+' '+short+' '+long).lower() for (agency,short,long,mode,color),idx in global_routes.items()}
    stops_by_id={idx:(lat,lon,name) for (lat,lon,name),idx in global_stops.items()}
    candidates=[]
    for trips in per_day.values():
        for tr in trips:
            if tr[2]!=-1:continue
            route=route_names.get(tr[0],'')
            names=[stops_by_id[x[0]][2].lower() for x in tr[3]]
            if 'arlanda' not in (route+' '+' '.join(names)):continue
            if len(tr[3])>12:continue
            if all(BOUNDS[0]-.03<=stops_by_id[x[0]][0]<=BOUNDS[2]+.03 for x in tr[3]):
                candidates.append(tr)
    if not candidates:
        print('OSM: no missing Arlanda corridor shapes',flush=True);return
    result=fetch_tracks()
    if not result:return
    pts,graph=result
    if not graph:return
    cache={};repaired=0
    for tr in candidates:
        coords=tuple((stops_by_id[sid][0],stops_by_id[sid][1]) for sid,_,_ in tr[3])
        if coords not in cache:
            joined=[]
            for a,b in zip(coords,coords[1:]):
                path=shortest(pts,graph,a,b)
                if not path:joined=[];break
                joined.extend(path if not joined else path[1:])
            cache[coords]=joined if len(joined)>3 else None
        route=cache[coords]
        if route:
            # Deduplicate every ~20-50m to bound JSON size; preserve bends.
            compact=[route[0]]
            for pt in route[1:-1]:
                if hav(compact[-1],pt)>24:compact.append(pt)
            compact.append(route[-1]);shape=tuple((round(a,5),round(b,5)) for a,b in compact)
            if shape not in global_shapes:global_shapes[shape]=len(global_shapes)
            tr[2]=global_shapes[shape];repaired+=1
    print('OSM Arlanda track shapes repaired:',repaired,'of',len(candidates),flush=True)
