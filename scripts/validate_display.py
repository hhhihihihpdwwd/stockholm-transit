"""Check whether *published* OSM shapes survive the browser's stop-to-track alignment.

The historical route-coverage.json only checks shape IDs. A trip with a shape can
still be displayed as stationary stop dots if the browser can't align stops to
that path. This report models the renderer alignment and counts both outcomes.
No external downloads, no fabricated geometry.
"""
import collections
import json
import math
from pathlib import Path
from route_quality import valid_anchors

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'public/data'


def distance(a,b):
    lat1,lon1=map(math.radians,a)
    lat2,lon2=map(math.radians,b)
    h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 12742000*math.asin(min(1,math.sqrt(h)))


def aligned(shape, points, mode):
    if not shape or len(shape)<2:return False,'missing_shape'
    limit={'rail':950,'bus':540}.get(mode,650)
    progress=0.0
    length=0
    # Computed once per shape and reused for every stop.
    segments=[]
    for a,b in zip(shape,shape[1:]):
        ln=distance(a,b)
        segments.append((a,b,length,ln))
        length+=ln
    anchors=[]
    for stop in points:
        nearest=(float('inf'),None)
        lat_scale=111130
        lon_scale=lat_scale*math.cos(math.radians(stop[0]))
        for a,b,start,ln in segments:
            dx=(b[1]-a[1])*lon_scale
            dy=(b[0]-a[0])*lat_scale
            px=(stop[1]-a[1])*lon_scale
            py=(stop[0]-a[0])*lat_scale
            denom=dx*dx+dy*dy
            frac=max(0.0,min(1.0,(px*dx+py*dy)/(denom or 1)))
            along=start+frac*ln
            if along<progress-100:continue
            error=math.hypot(px-frac*dx,py-frac*dy)
            if error<nearest[0]:nearest=(error,along)
        if nearest[1] is None or nearest[0]>limit:
            return False,'station_off_shape'
        progress=nearest[1]
        anchors.append(progress)
    if anchors[-1]-anchors[0]<=50:return False,'wrong_order_or_loop'
    return True,'renderable'


def audit(data=DATA):
    manifest=json.loads((data/'manifest.json').read_text())
    net=json.loads((data/'network.json').read_text())
    routes,shapes,stops=net['routes'],net['shapes'],net['stops']
    cache={}
    aggregate=collections.defaultdict(lambda:collections.Counter())
    examples=collections.defaultdict(list)
    for date in manifest['dates']:
        for item in json.loads((data/(date+'.json')).read_text())['trips']:
            route_id,_,shape_id,stop_rows=item[:4]
            route=routes[route_id]
            mode,short,operator=route[2],route[0],route[4]
            key=(mode,short,operator)
            aggregate[key]['total']+=1
            if shape_id<0:
                # Retain true OSM-only portions without claiming an entire
                # service has a complete mapped alignment.
                pieces=item[8] if len(item)>8 and isinstance(item[8],list) else []
                valid_pieces=0
                for piece in pieces:
                    if len(piece)==4 and 0<=piece[0]<len(shapes) and valid_anchors(shapes[piece[0]],piece[3],piece[2]-piece[1]+1):
                        valid_pieces+=1
                if valid_pieces:
                    aggregate[key]['partially_mapped']+=1
                    aggregate[key]['partial_osm_pieces']+=valid_pieces
                    reason='partial_route'
                else:
                    aggregate[key]['missing_shape']+=1
                    reason='missing_shape'
            else:
                aggregate[key]['has_shape']+=1
                baked=item[7] if len(item)>7 else None
                signature=(shape_id,tuple(s[0] for s in stop_rows),mode)
                if signature not in cache:
                    if valid_anchors(shapes[shape_id],baked,len(stop_rows)):
                        # Anchors are generated at the same time as the OSM
                        # graph path and kept through simplification.
                        cache[signature]=(True,'renderable')
                    else:
                        points=[stops[s[0]][:2] for s in stop_rows]
                        cache[signature]=aligned(shapes[shape_id],points,mode)
                valid,reason=cache[signature]
                aggregate[key]['displayable' if valid else 'not_displayable']+=1
                if not valid:aggregate[key][reason]+=1
            if reason!='renderable' and len(examples[key])<3:
                pair=(stops[stop_rows[0][0]][2]+' → '+stops[stop_rows[-1][0]][2])
                if pair not in examples[key]:examples[key].append(pair)
    lines=[]
    for key,c in sorted(aggregate.items()):
        mode,line,operator=key
        lines.append({'mode':mode,'line':line,'operator':operator,
                      'total':c['total'],'has_shape':c['has_shape'],
                      'displayable':c['displayable'],
                      'missing_shape':c['missing_shape'],
                      'invalid_shape':c['not_displayable'], 'partially_mapped':c['partially_mapped'], 'partial_osm_pieces':c['partial_osm_pieces'],
                      'percent':round(c['displayable']/c['total']*100,1),
                      'examples':examples[key]})
    result={'description':'Full routes use OSM stop anchors if available, otherwise the original browser snap; partial routes contain only individually verified OSM subpaths, never fabricated gap connections.',
            'total_groups':len(lines),'unique_patterns_checked':len(cache),
            'totals':dict(sum_counters(aggregate.values())), 'lines':lines}
    (data/'display-coverage.json').write_text(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    print('DISPLAY COVERAGE TOTALS:',result['totals'],flush=True)
    for l in sorted((x for x in lines if x['total']>=100),key=lambda x:x['percent'])[:15]:
        print('UNDISPLAYABLE:',l['mode'],l['line'],l['operator'],l['percent'],flush=True)
    return result


def sum_counters(items):
    out=collections.Counter()
    for c in items:out.update(c)
    return out


if __name__=='__main__':audit()
