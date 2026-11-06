#!/usr/bin/env python3
"""Build V8 Stockholm-focused offline historical timetable simulation, once.
Real archive services are preserved. Optional added pattern-based synthetic services
are explicitly labelled SIMULATED in the published trip data. Street and rail
geometry is sourced only from connected OpenStreetMap ways; never fabricated.
"""
import csv, datetime as dt, io, json, os, re, sys, urllib.request, urllib.parse, urllib.error, zipfile, collections, math, pathlib, time, gzip, zlib
from zoneinfo import ZoneInfo

ROOT = pathlib.Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'public'
OUT = PUBLIC / 'data'
OUT.mkdir(exist_ok=True, parents=True)

# Local Stockholm area for city transit.
STOCKHOLM_BBOX = (58.95, 59.82, 17.35, 19.10)  # south, north, west, east
# Wide Sweden corridor for long-distance rail (includes Copenhagen/Öresund side of cross-border services).
NATIONAL_BBOX = (54.80, 69.60, 10.00, 24.80)
# Representative archived week (Mon..Sun), repeated by weekday in the UI.
DAY0 = dt.date(2026, 11, 12)
DAYS = [dt.date(2026, 11, 9) + dt.timedelta(days=i) for i in range(7)]
SKIP_MODES = {'other'}
LOCAL_ONLY_MODES = {'metro', 'tram', 'commuter', 'localrail', 'ferry'}


def fetch_feed(name, key, url):
    if not key:
        print(f'SKIP {name}: no key')
        return None
    # Important: Trafiklab / Samtrafiken can return HTTP 406 unless compression
    # support is explicitly advertised. Retain this fix in future versions.
    endpoint = url + '?' + urllib.parse.urlencode({'key': key})
    req = urllib.request.Request(endpoint, headers={
        'User-Agent': 'StockholmTransitObservatory/2.1 (+timetable-simulator)',
        'Accept': 'application/zip, application/octet-stream, */*',
        'Accept-Encoding': 'gzip, deflate',
    })
    for attempt in range(3):
        try:
            print('Downloading', name, flush=True)
            with urllib.request.urlopen(req, timeout=240) as resp:
                data = resp.read()
                encoding = resp.headers.get('Content-Encoding', '').lower().strip()
            if encoding == 'gzip':
                data = gzip.decompress(data)
            elif encoding == 'deflate':
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    data = zlib.decompress(data, -zlib.MAX_WBITS)
            elif encoding not in ('', 'identity'):
                raise ValueError('Unsupported response encoding: ' + encoding)
            if not zipfile.is_zipfile(io.BytesIO(data)):
                raise ValueError('Feed response is not a ZIP file')
            print('Read', name, len(data) // 1024 // 1024, 'MiB', flush=True)
            return zipfile.ZipFile(io.BytesIO(data))
        except urllib.error.HTTPError as exc:
            # HTTP 429 is a rate limit, NOT an invalid API key. Retrying three
            # times within a few seconds only makes it worse.
            if exc.code == 429:
                wait = exc.headers.get('Retry-After', 'not provided') if exc.headers else 'not provided'
                print(f'RATE LIMITED: {name} HTTP 429; Retry-After: {wait}. '
                      'Do not start repeated manual builds; wait for the quota to recover.', flush=True)
                return None
            print('Feed failure:', name, type(exc).__name__,
                  str(exc).replace(key, '[REDACTED]')[:260], flush=True)
        except Exception as exc:
            print('Feed failure:', name, type(exc).__name__,
                  str(exc).replace(key, '[REDACTED]')[:260], flush=True)
        if attempt < 2:
            time.sleep(attempt * 2 + 1)
    return None


def records(z, filename):
    try:
        with z.open(filename) as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding='utf-8-sig', errors='replace', newline='')):
                yield row
    except KeyError:
        return


def inside(box, lat, lon):
    return box[0] <= lat <= box[1] and box[2] <= lon <= box[3]


def pfloat(v):
    try:
        return float(v)
    except Exception:
        return None


def service_on(z):
    selected = {d: set() for d in DAYS}
    weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    for row in records(z, 'calendar.txt'):
        try:
            st = dt.datetime.strptime(row['start_date'], '%Y%m%d').date()
            en = dt.datetime.strptime(row['end_date'], '%Y%m%d').date()
        except Exception:
            continue
        for d in DAYS:
            if st <= d <= en and row.get(weekdays[d.weekday()]) == '1':
                selected[d].add(row['service_id'])
    for row in records(z, 'calendar_dates.txt'):
        try:
            d = dt.datetime.strptime(row['date'], '%Y%m%d').date()
        except Exception:
            continue
        if d in selected:
            if row.get('exception_type') == '1':
                selected[d].add(row['service_id'])
            elif row.get('exception_type') == '2':
                selected[d].discard(row['service_id'])
    return selected


def route_mode(r, agency):
    raw = r.get('route_type', '3')
    try:
        t = int(raw)
    except Exception:
        t = 3
    short = (r.get('route_short_name', '') or '').strip()
    long = (r.get('route_long_name', '') or '').strip()
    info = f"{short} {long} {agency}".lower()

    if t in (0, 900, 901, 902, 903, 904, 905, 906):
        return 'tram'
    if t == 1 or 400 <= t < 500 or 'tunnelbana' in info or 't-bana' in info:
        return 'metro'
    if t in (4, 1000, 1001, 1002):
        return 'ferry'
    if t == 2 or 100 <= t < 400:
        # Stronger heuristics to avoid classifying Pendeltåg or Roslagsbanan as generic rail.
        if any(s in info for s in ('pendel', 'pendeltåg', 'pendaltag', 'x60', 'x61', 'commuter')):
            return 'commuter'
        if short and re.fullmatch(r'4\d[A-Z]?', short):
            return 'commuter'
        if any(s in info for s in ('roslags', 'saltsjö', 'saltsjobanan')):
            return 'localrail'
        if short in {'25', '26', '27', '28', '29'}:
            return 'localrail'
        return 'rail'
    if t == 3 or 700 <= t < 900:
        return 'bus'
    return 'other'


def time_sec(s):
    try:
        h, m, sec = map(int, s.split(':'))
        return h * 3600 + m * 60 + sec
    except Exception:
        return None


def stop_allowed(mode, stock):
    return stock['in_national'] if mode in ('rail', 'commuter') else stock['in_stockholm']


def shape_clip_bbox(mode):
    return NATIONAL_BBOX if mode in ('rail', 'commuter') else STOCKHOLM_BBOX


def process_feed(z, label, global_routes, global_stops, global_shapes, per_day, seen_trips):
    print('Processing', label, flush=True)
    services = service_on(z)
    agencies = {r.get('agency_id', ''): r.get('agency_name', '') for r in records(z, 'agency.txt')}
    default_agency = next(iter(agencies.values()), label)

    routes = {}
    route_modes = {}
    for r in records(z, 'routes.txt'):
        agency = agencies.get(r.get('agency_id', ''), default_agency)
        mode = route_mode(r, agency)
        # SL provides local Stockholm services. Sweden 3 is used ONLY to add
        # nationwide rail so its overlapping SL trips do not duplicate.
        if label == 'Sweden 3' and mode != 'rail':
            continue
        if mode in SKIP_MODES:
            continue
        short = (r.get('route_short_name', '') or '').strip()
        long = (r.get('route_long_name', '') or '').strip()
        color = (r.get('route_color') or '').strip().lstrip('#')
        if not re.fullmatch(r'[a-fA-F0-9]{6}', color or ''):
            color = {
                'metro': '1976D2',
                'bus': '347CC2',
                'commuter': 'E55397',
                'tram': '28A6BA',
                'localrail': '7964C7',
                'rail': '818D9E',
                'ferry': '2298B3',
            }.get(mode, '919191')
        key = (agency, short, long, mode, color.upper())
        if key not in global_routes:
            global_routes[key] = len(global_routes)
        rid = r.get('route_id')
        routes[rid] = global_routes[key]
        route_modes[rid] = mode

    stop_meta = {}
    for r in records(z, 'stops.txt'):
        lat = pfloat(r.get('stop_lat'))
        lon = pfloat(r.get('stop_lon'))
        sid = r.get('stop_id')
        name = (r.get('stop_name', '') or '').strip()
        if lat is None or lon is None or not sid:
            continue
        in_stockholm = inside(STOCKHOLM_BBOX, lat, lon)
        in_national = in_stockholm or inside(NATIONAL_BBOX, lat, lon)
        if not in_national:
            continue
        key = (round(lat, 5), round(lon, 5), name)
        if key not in global_stops:
            global_stops[key] = len(global_stops)
        stop_meta[sid] = {
            'gid': global_stops[key],
            'in_stockholm': in_stockholm,
            'in_national': in_national,
            'lat': lat,
            'lon': lon,
        }
    print('Candidate stops', len(stop_meta), flush=True)

    trips = {}
    active_ids = set().union(*services.values())
    for r in records(z, 'trips.txt'):
        rid = r.get('route_id')
        if r.get('service_id') not in active_ids or rid not in routes:
            continue
        ident = r.get('trip_id')
        if not ident:
            continue
        dates = [d for d in DAYS if r.get('service_id') in services[d]]
        if dates:
            trips[ident] = (routes[rid], r.get('trip_headsign', ''), r.get('shape_id', ''), dates, route_modes[rid], (r.get('trip_short_name') or '').strip())
    print('Trips with active service', len(trips), flush=True)

    stop_times = collections.defaultdict(list)
    for r in records(z, 'stop_times.txt'):
        tid = r.get('trip_id')
        if tid not in trips:
            continue
        stop = stop_meta.get(r.get('stop_id'))
        if not stop:
            continue
        mode = trips[tid][4]
        if not stop_allowed(mode, stop):
            continue
        arr = time_sec(r.get('arrival_time', ''))
        dep = time_sec(r.get('departure_time', ''))
        if arr is None and dep is None:
            continue
        if arr is None:
            arr = dep
        if dep is None:
            dep = arr
        try:
            seq = int(r.get('stop_sequence', '0'))
        except Exception:
            seq = 0
        stop_times[tid].append((seq, stop['gid'], arr, dep))

    relevant = {tid: trips[tid] for tid, st in stop_times.items() if len(st) >= 2}
    needed_shapes = {r[2] for r in relevant.values() if r[2]}
    print('Trips with 2+ allowed stops', len(relevant), 'shapes', len(needed_shapes), flush=True)

    raw_shapes = collections.defaultdict(list)
    for r in records(z, 'shapes.txt'):
        sid = r.get('shape_id')
        if sid not in needed_shapes:
            continue
        lat = pfloat(r.get('shape_pt_lat'))
        lon = pfloat(r.get('shape_pt_lon'))
        if lat is None or lon is None:
            continue
        try:
            seq = int(r.get('shape_pt_sequence', '0'))
        except Exception:
            seq = 0
        raw_shapes[sid].append((seq, lat, lon))

    # Build per-mode shape map using a wider bbox for rail.
    shape_map = {}
    mode_for_shape = {}
    for tid, (_, _, sid, _, mode, train_no) in relevant.items():
        if sid and sid not in mode_for_shape:
            mode_for_shape[sid] = mode
    for sid, pts in raw_shapes.items():
        pts.sort()
        box = shape_clip_bbox(mode_for_shape.get(sid, 'rail'))
        kept = [
            (round(lat, 5), round(lon, 5))
            for _, lat, lon in pts
            if box[0] - 0.04 <= lat <= box[1] + 0.04 and box[2] - 0.04 <= lon <= box[3] + 0.04
        ]
        if len(kept) < 2:
            continue
        arr = [kept[0]]
        for p in kept[1:-1]:
            prev = arr[-1]
            if abs(p[0] - prev[0]) + abs(p[1] - prev[1]) >= 0.00008:
                arr.append(p)
        arr.append(kept[-1])
        limit = 3200 if mode_for_shape.get(sid) == 'rail' else 1800
        if len(arr) > limit:
            step = math.ceil(len(arr) / limit)
            arr = arr[::step] + [arr[-1]]
        coords = tuple(arr)
        if coords not in global_shapes:
            global_shapes[coords] = len(global_shapes)
        shape_map[sid] = global_shapes[coords]

    added = 0
    for tid, (route, head, shape, dates, mode, train_no) in relevant.items():
        sts = sorted(stop_times[tid], key=lambda row: row[0])
        clean = []
        for _, stop, a, b in sts:
            if clean and a < clean[-1][2] - 60:
                continue
            clean.append([stop, a, max(a, b)])
        if len(clean) < 2 or clean[-1][1] - clean[0][1] > 40 * 3600:
            continue
        # Avoid duplicates between feeds.
        trip_key = (route, tuple((a[0], a[1]) for a in clean))
        if trip_key in seen_trips:
            continue
        seen_trips.add(trip_key)
        # IMPORTANT: one fresh mutable trip per day. A shared item would be
        # reindexed multiple times during network compaction (KeyError).
        for d in dates:
            per_day[d].append([route, head, shape_map.get(shape, -1),
                               [stop.copy() for stop in clean], '', train_no])
            added += 1
    print('Completed', label, 'items added', added, flush=True)
    # O(trips) diagnostics (avoid scanning all route definitions for each trip).
    route_mode_by_idx = {idx: mode_name for (_, _, _, mode_name, _), idx in global_routes.items()}
    counts = collections.Counter(route_mode_by_idx[item[0]] for item in per_day[DAY0])
    print('MODE DIAGNOSTIC', label, dict(counts), flush=True)


def fill_simulation_gaps(per_day, global_routes):
    """Add MODELLed frequency trips from archived route patterns.

    Does not create invented stops or routes. Adds only scheduled departure
    variants on fully known stop patterns. Modelled trips are labelled in JSON.
    Useful when historical service calendar is sparse; not realtime data.
    """
    mode_by_idx = {idx:mode for (_,_,_,mode,_),idx in global_routes.items()}
    headway = {'metro':360, 'commuter':900, 'tram':720, 'localrail':1100,
               'bus':1100, 'ferry':1800}
    maximum = {'metro':1900, 'commuter':850, 'tram':450, 'localrail':300,
               'bus':2200, 'ferry':180}
    for day, trips in per_day.items():
        groups = collections.defaultdict(list)
        for item in trips:
            if mode_by_idx[item[0]] not in headway or len(item[3])<2:continue
            key=(item[0], item[3][0][0], item[3][-1][0], tuple(row[0] for row in item[3]))
            groups[key].append(item)
        # Pick a real observed full journey for each line & direction; individual
        # variants of the same route are limited to keep network size bounded.
        candidates=[]
        for key, observed in groups.items():
            m=mode_by_idx[key[0]]
            fastest=max(observed,key=lambda x:(len(x[3]),x[3][-1][1]-x[3][0][1]))
            travel=fastest[3][-1][1]-fastest[3][0][1]
            if 120 <= travel <= 5*3600:
                candidates.append((m,key,fastest,observed))
        candidates.sort(key=lambda x: (-len(x[3]),x[1]))
        seen_mode=collections.Counter()
        new_items=[]
        for mode,key,base,observed in candidates:
            if seen_mode[mode]>=maximum[mode]:continue
            # Do not duplicate observed departures within half a headway.
            existing=sorted(x[3][0][1] for x in observed)
            period=headway[mode]
            base_depart=base[3][0][1]
            offsets=[(st[0],st[1]-base_depart,st[2]-base_depart) for st in base[3]]
            if any(arr<0 or dep<arr for _,arr,dep in offsets):continue
            for depart in range(5*3600,24*3600+21*60,period):
                if seen_mode[mode]>=maximum[mode]:break
                if any(abs(depart-t)<period*.72 for t in existing):continue
                # Every new trip is a clearly marked synthetic timetable estimate.
                stops=[[sid,depart+arr,depart+dep] for sid,arr,dep in offsets]
                if stops[-1][1]>28*3600:continue
                new_items.append([base[0],base[1],base[2],stops,'modelled'])
                seen_mode[mode]+=1
        trips.extend(new_items)
        print('SIMULATED HEADWAY SUPPLEMENTS',str(day),dict(seen_mode),flush=True)
    return per_day


def main():
    # Offline snapshot: one historical national archive, NO API key / quota.
    url = os.environ.get('GTFS_ARCHIVE_URL',
        'https://data.samtrafiken.se/trafiklab/gtfs-sverige-2/2026/11/sweden-20261104.zip')
    if not url.startswith('https://data.samtrafiken.se/trafiklab/gtfs-sverige-2/'):
        raise ValueError('Only the verified public Samtrafiken historical archive is allowed')
    feeds = [('Archive Sverige 2', None, url)]

    global_routes = {}
    global_stops = {}
    global_shapes = {}
    per_day = {d: [] for d in DAYS}
    seen = set()
    used = []

    for label, _, url in feeds:
        print('Downloading public timetable archive once:', url, flush=True)
        request=urllib.request.Request(url,headers={'User-Agent':'StockholmTransitArchiveSimulator/1.0',
            'Accept-Encoding':'identity'})
        with urllib.request.urlopen(request,timeout=240) as response:
            raw=response.read()
        if not zipfile.is_zipfile(io.BytesIO(raw)):
            raise ValueError('Archived download is not a ZIP')
        print('Archive downloaded:',round(len(raw)/1024/1024,1),'MiB',flush=True)
        z=zipfile.ZipFile(io.BytesIO(raw))
        try:
            process_feed(z,label,global_routes,global_stops,global_shapes,per_day,seen)
            used.append(label)
        finally:
            z.close()
    if not used:
        print('No archived timetable processed.',file=sys.stderr)
        return 2

    # Focus V8 on every Stockholm transit service and intercity services that
    # actually touch the Stockholm area, rather than loading all Swedish rail.
    mode_by_route={idx:mode for (_,_,_,mode,_),idx in global_routes.items()}
    stop_by_id={idx:(lat,lon) for (lat,lon,_),idx in global_stops.items()}
    centre=(59.33,18.06)
    from osm_routes import hav
    rail_seen=rail_kept=0
    for d, items in per_day.items():
        retained=[]
        for item in items:
            if mode_by_route[item[0]] in {'rail','commuter'}:
                rail_seen+=1
                # Keep the *entire* journey to its far-away destination if it
                # visits any station in the greater Stockholm area.
                if not any(hav(stop_by_id[st[0]],centre)<=33000 for st in item[3]):
                    continue
                rail_kept+=1
            retained.append(item)
        per_day[d]=retained
    print('STOCKHOLM FILTER: retained national rail/commuter',rail_kept,'/',rail_seen,'dated trips',flush=True)
    fill_simulation_gaps(per_day,global_routes)

    # One Stockholm PBF extract, streamed to disk, parsed locally. This avoids
    # public Overpass request timeouts seen in V7.
    from osm_extract import enrich as enrich_pbf
    tunnel_shapes=enrich_pbf(global_routes,global_stops,global_shapes,per_day)

    # V9: do NOT create straight lines through stations for unrouted trains.
    # National railway geometry is sourced from the all-Sweden OSM track graph.
    # Any failure remains visible in diagnostics rather than masquerading as a
    # verified or geographically plausible railroad.
    missing_routes=collections.Counter()
    for trips in per_day.values():
        for item in trips:
            if item[2]<0:missing_routes[mode_by_route[item[0]]]+=1
    print('V9 UNROUTED TRIPS (held at stop, no fake geography):',dict(missing_routes),flush=True)

    routes = [None] * len(global_routes)
    for (agency, short, long, mode, color), i in global_routes.items():
        routes[i] = [short or long[:20], long, mode, color, agency]

    stops = [None] * len(global_stops)
    for (lat, lon, name), i in global_stops.items():
        stops[i] = [lat, lon, name]

    shapes = [None] * len(global_shapes)
    for coords, i in global_shapes.items():
        shapes[i] = coords

    # Compact the published network to the actual representative seven days. Sweden 3
    # contains many inactive routes/stops; never ship those unused tables to a phone.
    used_routes = set()
    used_stops = set()
    used_shapes = set()
    for trips in per_day.values():
        for item in trips:
            used_routes.add(item[0]);used_stops.update(st[0] for st in item[3])
            if item[2] >= 0:used_shapes.add(item[2])
    route_ids={old:i for i,old in enumerate(sorted(used_routes))}
    stop_ids={old:i for i,old in enumerate(sorted(used_stops))}
    shape_ids={old:i for i,old in enumerate(sorted(used_shapes))}
    routes=[routes[old] for old in sorted(used_routes)]
    stops=[stops[old] for old in sorted(used_stops)]
    shapes=[shapes[old] for old in sorted(used_shapes)]
    compact_tunnels={shape_ids[old]:flags for old,flags in tunnel_shapes.items() if old in shape_ids}
    # Defensive identity de-duplication: even if optional route enrichment
    # shared an object across days, transform each actual object only once.
    reindexed_items = set()
    for trips in per_day.values():
        for item in trips:
            identity = id(item)
            if identity in reindexed_items:
                continue
            reindexed_items.add(identity)
            item[0] = route_ids[item[0]]
            item[2] = shape_ids.get(item[2], -1)
            for stop in item[3]:
                stop[0] = stop_ids[stop[0]]
    print('PUBLISHED NETWORK:',len(routes),'routes,',len(stops),'stops,',len(shapes),'shapes',flush=True)
    geo_counts=collections.Counter();all_counts=collections.Counter()
    for trips in per_day.values():
        for item in trips:
            mode=routes[item[0]][2];all_counts[mode]+=1
            if item[2]>=0:geo_counts[mode]+=1
    print('REAL ROAD/RAIL GEOMETRY COVERAGE:',{k:f'{geo_counts[k]}/{v} ({geo_counts[k]/v:.1%})' for k,v in all_counts.items()},flush=True)
    # Auditable PER-LINE result. This is the source of truth for whether
    # "all routes" actually mapped; nobody should need to guess from the UI.
    by_line=collections.defaultdict(lambda: {'total':0,'mapped':0,'unmapped_examples':[]})
    for trips in per_day.values():
        for item in trips:
            route=routes[item[0]]
            key=(route[2],route[0],route[4])
            entry=by_line[key]
            entry['total']+=1
            if item[2]>=0:entry['mapped']+=1
            elif len(entry['unmapped_examples'])<3:
                entry['unmapped_examples'].append(stops[item[3][0][0]][2]+' → '+stops[item[3][-1][0]][2])
    line_report=[{'mode':mode,'line':line,'operator':operator,**values,
                  'percent':round(100*values['mapped']/values['total'],1)}
                 for (mode,line,operator),values in sorted(by_line.items())]
    (OUT/'route-coverage.json').write_text(json.dumps({
        'description':'Each archived departure is counted across seven days; mapped means aligned to an OSM network shape, not verified actual train movements.',
        'total_lines':len(line_report), 'lines':line_report},ensure_ascii=False,separators=(',',':')))
    print('ROUTE COVERAGE FILE: public/data/route-coverage.json,',len(line_report),'line/operator groups',flush=True)
    worst=sorted((l for l in line_report if l['total']>=10),key=lambda x:x['percent'])[:20]
    print('20 WORST LINE COVERAGES:',[(l['mode'],l['line'],l['percent']) for l in worst],flush=True)


    meta = {
        'source': used,
        'generated': dt.datetime.now(dt.timezone.utc).isoformat(),
        'simulation': True,
        'stockholm_bounds': STOCKHOLM_BBOX,
        'national_bounds': NATIONAL_BBOX,
        'excluded_modes': sorted(SKIP_MODES),
        'mode': 'historical-weekday-repeat', 'synthetic_supplements': True, 'osm_connected_geometry': True, 'stockholm_only_local': True,
        'snapshot': '2026-11-04',
        'historical': True,
    }
    net = {'meta': meta, 'routes': routes, 'stops': stops, 'shapes': shapes, 'tunnels': compact_tunnels}
    (OUT / 'network.json').write_text(json.dumps(net, ensure_ascii=False, separators=(',', ':')))
    for d, items in per_day.items():
        (OUT / (d.isoformat() + '.json')).write_text(json.dumps({'date': d.isoformat(), 'trips': items}, ensure_ascii=False, separators=(',', ':')))
    (OUT / 'manifest.json').write_text(json.dumps({
        'dates': [d.isoformat() for d in DAYS],
        'generated': meta['generated'],
        'sources': used,
        'counts': {str(d): len(per_day[d]) for d in DAYS},
        'weekly_repeat': True, 'snapshot': '2026-11-04',
    }, ensure_ascii=False, separators=(',', ':')))
    mode_counts = collections.Counter()
    for item in per_day[DAY0]:
        mode_counts[routes[item[0]][2]] += 1
    print('TODAY TRIPS BY MODE:',dict(mode_counts),flush=True)
    missing=[mode for mode in ('metro','commuter','bus','tram','rail') if not any(routes[item[0]][2]==mode for trips in per_day.values() for item in trips)]
    if missing:
        print('WARNING: Modes missing from archived feed:',missing,flush=True)
    print('OFFLINE WEEKLY SNAPSHOT: 2026-11-04, archived representative week:',[str(d) for d in DAYS],flush=True)
    # V10: main data builds never contact Wikimedia; only review committed local files.
    from local_photos import write_local_catalog
    report = write_local_catalog()
    print('OFFLINE PHOTO LIBRARY:', report['available'], '/', report['expected'], 'local images; no network requests', flush=True)
    for f in OUT.iterdir():
        print(f.name, round(f.stat().st_size / 1024 / 1024, 2), 'MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
