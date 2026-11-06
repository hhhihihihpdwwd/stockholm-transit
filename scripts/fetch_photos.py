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
    'commuter_x60': ('Railway bridge and Alstom X60 in Stockholm, 2016.jpg', 'Pendeltåg · X60'),
    'commuter_x60_alt': ('Alstom X60 med kamera 20221001 04.jpg', 'Pendeltåg · X60'),
    'tram_a35': ('2015-08-29 1726 SL A35 463 mellan Ulvsundabron och Tranebergstunneln.jpg', 'Tvärbanan · A35'),
    'tram_a32': ('A32 spårvagn 2023 08.jpg', 'Spårvagn · A32'),
    'local_x15p': ('X15p vid Visinge station.jpg', 'Roslagsbanan · X15p'),
    'local_x15p_alt': ('X15p, Stockholms östra - 20250504 - 06.jpg', 'Roslagsbanan · X15p'),
    'rail_x2000': ('Stockholms central, X2000 - 20260515 - 09.jpg', 'SJ · X2000'),
    'rail_arlanda': ('Arlanda Express, Stockholm Centralstation - 20240831 - 03.jpg', 'Arlanda Express · X3'),
    'rail_malartag': ('Stockholm ER1.jpg', 'Mälartåg · ER1'),
    'rail_oresund': ('Öresundståg i östra Sölvesborg.JPG', 'Öresundståg · X31'),
    'ferry_djurgarden10': ('Djurgården 10.jpg', 'Djurgårdsfärjan · Djurgården 10'),
    'bus_red69': ('SL Buss 69, T-Centralen - 20250419 - 01.jpg', 'SL buss · röd stadsbuss'),
    'bus_red75': ('SL Buss 75, Stockholm - 20240430 - 14.jpg', 'SL buss · röd stadsbuss'),
    'bus_blue2': ('SL bus line 2 at Norrmalmstorg.jpg', 'SL buss · blå innerstadsbuss'),
}


def request_bytes(url, timeout=12, limit=2_200_000):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'StockholmTransitObservatory/1.0 (daily static Wikimedia Commons attribution downloader)',
        'Accept-Encoding': 'gzip',
    })
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = res.read(limit + 1)
        if res.headers.get('Content-Encoding', '').lower() == 'gzip':
            data = gzip.decompress(data)
    if len(data) > limit:
        raise ValueError('image exceeds size limit')
    return data


def text_only(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def generate():
    index = {}
    api = 'https://commons.wikimedia.org/w/api.php?'
    for key, (title, caption) in CATALOG.items():
        try:
            params = {
                'action': 'query', 'format': 'json', 'titles': 'File:' + title,
                'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata', 'iiurlwidth': '850',
            }
            metadata = json.loads(request_bytes(api + urllib.parse.urlencode(params), timeout=12, limit=200_000))
            page = next(iter(metadata['query']['pages'].values()))
            imageinfo = page.get('imageinfo', [{}])[0]
            mime = imageinfo.get('mime', '')
            if mime not in ('image/jpeg', 'image/png', 'image/webp'):
                raise ValueError('missing or unsuitable image: ' + mime)
            img_url = imageinfo.get('thumburl') or imageinfo.get('url')
            if not img_url:
                raise ValueError('no file download URL')
            data = request_bytes(img_url, timeout=18, limit=2_200_000)
            valid = (data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n' or data[:4] == b'RIFF')
            if not valid:
                raise ValueError('unexpected image file content')
            suffix = '.jpg' if mime == 'image/jpeg' else ('.png' if mime == 'image/png' else '.webp')
            (OUT / (key + suffix)).write_bytes(data)
            ext = imageinfo.get('extmetadata', {})
            credit = text_only(ext.get('Artist', {}).get('value', ''))[:150]
            license_name = text_only(ext.get('LicenseShortName', {}).get('value', ''))[:80]
            index[key] = {'path': 'assets/photos/' + key + suffix, 'label': caption,
                          'source': imageinfo.get('descriptionurl', ''),
                          'author': credit, 'license': license_name}
            print('Photo available:', key, round(len(data) / 1024), 'KB', flush=True)
        except Exception as exc:
            # Build remains functional without photos. Never use a mismatching generic photo.
            print('Photo fallback (icon):', key, str(exc)[:140], flush=True)
    (OUT / 'catalog.json').write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')))
    print('Photo library:', len(index), '/', len(CATALOG), 'verified file types downloaded')
    return index


if __name__ == '__main__':
    generate()
