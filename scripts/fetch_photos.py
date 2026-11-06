"""Generate a LOCAL, attributed photo library from a curated list of exact Wikimedia files.

No arbitrary keyword search. Never insert photographs of a different vehicle type.
The normal webpage fetches /assets/photos/*.jpg, never Wikimedia.
Any failed/missing photo falls back to the user's generated realistic icon.
"""
import gzip
import html
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'public' / 'assets' / 'photos'
OUT.mkdir(parents=True, exist_ok=True)

# Titles selected by vehicle descriptions and categories on Wikimedia Commons.
# The image is an illustrative photo of the model / category, not the live vehicle.
CATALOG = {
    'metro_c30': ('Stockholm metro - SL C30 (1).jpg', 'Tunnelbana · C30'),
    'metro_c20': ('Söderströmsbron, SL C20 - 20251123 - 23.jpg', 'Tunnelbana · C20'),
    'commuter_x60': ('SL X60, Stockholm Centralstation, 20240106 - 06.jpg', 'Pendeltåg · X60, sichtbarer Zug'),
    'commuter_x60_alt': ('SL X60, Stockholm Centralstation, 20240106 - 02.jpg', 'Pendeltåg · X60'),
    'tram_a35': ('2015-08-29 1726 SL A35 463 mellan Ulvsundabron och Tranebergstunneln.jpg', 'Tvärbanan · A35'),
    'tram_a32': ('A32 spårvagn 2023 08.jpg', 'Spårvagn · A32'),
    'local_x15p': ('X15p vid Visinge station.jpg', 'Roslagsbanan · X15p'),
    'local_x15p_alt': ('X15p, Stockholms östra - 20250504 - 06.jpg', 'Roslagsbanan · X15p'),
    'rail_sj3000': ('Stockholm Central, SJ 3000 - 20260327 - 03.jpg', 'SJ · SJ 3000 / X55'),
    'rail_sj_x40': ('SJ X40, Stockholm Central - 20260311 - 05.jpg', 'SJ · X40 Doppelstockzug'),
    'rail_snalltaget': ('Snälltåget, Stockholms centralstation - 20260514 - 10.jpg', 'Snälltåget · Fernzug'),
    'rail_x2000': ('Stockholms central, X2000 - 20260515 - 09.jpg', 'SJ · X2000'),
    'rail_arlanda': ('Arlanda Express X3.JPG', 'Arlanda Express · X3'),
    'rail_malartag': ('Sverige Mälartåg ER1 111, Gävle IMG 6437.jpg', 'Mälartåg · ER1'),
    'rail_oresund': ('Öresundståg i östra Sölvesborg.JPG', 'Öresundståg · X31'),
    'ferry_djurgarden10': ('Djurgården 10.jpg', 'Djurgårdsfärjan · Djurgården 10'),
    'bus_red69': ('SL bus line 69 at Norrmalmstorg.jpg', 'SL buss · röd stadsbuss'),
    'bus_red75': ('SL Buss 75, Stockholm - 20240430 - 14.jpg', 'SL buss · röd stadsbuss'),
    'bus_blue2': ('SL bus line 2 at Norrmalmstorg.jpg', 'SL buss · blå innerstadsbuss'),
    'local_saltsjo': ('Saltsjöbanan at Saltsjöbaden station.jpg', 'Saltsjöbanan · C10/C11'),
    'ferry_84': ('Eskil November 2024 01.jpg', 'Pendelbåt 84 · M/S Eskil'),
    'rail_sj_rc6': ('SJ Rc 1383 Stockholm Central.jpg', 'SJ InterCity · Rc6'),
    'rail_vr_x74': ('VR X74 1.jpg', 'VR Snabbtåg · X74'),
}


# Only substitute photos depicting the same general vehicle family.
# These Commons titles were located in public Commons file/category listings;
# licensing and attribution are read from metadata at download time.
ALTERNATES = {
    'commuter_x60': ['SL X60 6010 A.jpg', 'SL X60, Stockholm Centralstation, 20240106 - 02.jpg'],
    'commuter_x60_alt': ['SL X60, Stockholm Centralstation, 20240106 - 06.jpg'],
    'rail_arlanda': ['Arlanda Express X3.JPG'],
    'rail_malartag': ['Sverige Mälartåg ER1 111, Gävle IMG 6427 1-8-2.jpg', 'Stockholm ER1.jpg'],
    'bus_red69': ['SL Buss 69, T-Centralen - 20250419 - 01.jpg', 'SL bus line 69 at Kungsträdgården.jpg'],
    'bus_red75': ['SL Buss 75, Stockholm - 20240430 - 14.jpg', 'SL bus line 69 at Norrmalmstorg.jpg'],
    'bus_blue2': ['SL bus line 2 at Norrmalmstorg.jpg'],
}



def request_bytes(url, timeout=12, limit=2_200_000):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'StockholmTransit/9.1 (Commons static images; open source transit map)',
        'Accept-Encoding': 'gzip',
    })
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = res.read(limit + 1)
                if res.headers.get('Content-Encoding', '').lower() == 'gzip':
                    data = gzip.decompress(data)
            if len(data) > limit:
                raise ValueError('image exceeds size limit')
            return data
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2 or isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 404, 410):
                raise
            time.sleep(1.5 * (attempt + 1))


def text_only(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def download_one(key, title, caption):
    api = 'https://commons.wikimedia.org/w/api.php?'
    params = {
        'action': 'query', 'format': 'json', 'titles': 'File:' + title,
        'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata', 'iiurlwidth': '720',
    }
    metadata = json.loads(request_bytes(api + urllib.parse.urlencode(params), timeout=18, limit=250_000))
    page = next(iter(metadata['query']['pages'].values()))
    imageinfo = page.get('imageinfo', [{}])[0]
    mime = imageinfo.get('mime', '')
    if mime not in ('image/jpeg', 'image/png', 'image/webp'):
        raise ValueError('missing or unsuitable image: ' + mime)
    url = imageinfo.get('thumburl') or imageinfo.get('url')
    if not url:
        raise ValueError('no file URL')
    data = request_bytes(url, timeout=25, limit=4_800_000)
    if not (data.startswith(b'\xff\xd8\xff') or data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'RIFF')):
        raise ValueError('downloaded content is not an image')
    suffix = '.jpg' if mime == 'image/jpeg' else ('.png' if mime == 'image/png' else '.webp')
    (OUT / (key + suffix)).write_bytes(data)
    ext = imageinfo.get('extmetadata', {})
    credit = text_only(ext.get('Artist', {}).get('value', ''))[:150]
    license_name = text_only(ext.get('LicenseShortName', {}).get('value', ''))[:80]
    # No photo without traceable source and author/license for attribution.
    source = imageinfo.get('descriptionurl', '')
    if not source or not license_name:
        (OUT / (key + suffix)).unlink(missing_ok=True)
        raise ValueError('source or license metadata missing')
    return {'path': 'assets/photos/' + key + suffix, 'label': caption,
            'source': source, 'author': credit, 'license': license_name,
            'commons_title': title, 'bytes': len(data)}


def generate():
    index, failures = {}, {}
    for key, (title, caption) in CATALOG.items():
        titles = list(dict.fromkeys([title] + ALTERNATES.get(key, [])))
        errors = []
        for candidate in titles:
            try:
                item = download_one(key, candidate, caption)
                index[key] = item
                print('PHOTO OK:', key, candidate, round(item['bytes'] / 1024), 'KB', flush=True)
                break
            except Exception as exc:
                errors.append(candidate + ': ' + type(exc).__name__ + ' ' + str(exc)[:130])
        if key not in index:
            failures[key] = errors
            print('PHOTO MISSING:', key, ' | '.join(errors)[:230], flush=True)
    (OUT / 'catalog.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    report = {'expected': len(CATALOG), 'downloaded': len(index), 'missing': failures,
              'available_keys': sorted(index)}
    (OUT / 'photo-health.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print('PHOTO HEALTH:',len(index),'/',len(CATALOG),'missing keys:',sorted(failures),flush=True)
    return index


if __name__ == '__main__':
    generate()
