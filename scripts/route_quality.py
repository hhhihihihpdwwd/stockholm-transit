"""V11 route geometry helpers: explicit audited distance anchors.

We keep only actual GTFS/OSM polylines. A fallback straight line is never
misrepresented as a navigable road or track.
"""
from __future__ import annotations
import math


def hav(a, b):
    a1, o1 = map(math.radians, a)
    a2, o2 = map(math.radians, b)
    f = math.sin((a2-a1)/2)**2 + math.cos(a1)*math.cos(a2)*math.sin((o2-o1)/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(f)))


def cumulative(shape):
    out=[0.0]
    for a,b in zip(shape,shape[1:]):
        out.append(out[-1]+hav(a,b))
    return out


def valid_anchors(shape, anchors, count):
    if not isinstance(anchors,list) or len(anchors)!=count or count<2 or not shape or len(shape)<2:
        return False
    length=cumulative(shape)[-1]
    if length<=50:return False
    if any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in anchors):
        return False
    if anchors[0]<-1 or anchors[-1]>length+3 or anchors[-1]-anchors[0]<40:
        return False
    return all(a<=b+0.1 for a,b in zip(anchors,anchors[1:]))


def direct_stop_distance_to_shape(shape, stop):
    """Minimum stop-to-polyline separation in metres, not point-only distance."""
    ls=111130.0
    best=math.inf
    for a,b in zip(shape,shape[1:]):
        xs=ls*math.cos(math.radians(stop[0]))
        dx=(b[1]-a[1])*xs;dy=(b[0]-a[0])*ls
        px=(stop[1]-a[1])*xs;py=(stop[0]-a[0])*ls
        t=max(0,min(1,(px*dx+py*dy)/(dx*dx+dy*dy or 1)))
        best=min(best,math.hypot(px-t*dx,py-t*dy))
    return best
