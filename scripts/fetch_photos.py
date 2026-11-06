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
APPROVALS = json.loads((ROOT / 'approved_photos.json').read_text(encoding='utf-8'))['photos']
CATALOG = {key:(item['title'],item['label']) for key,item in APPROVALS.items()}
ALTERNATES = {}  # No substitutions without explicit user approval.



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


def reusable_photo(previous, key):
    item = previous.get(key)
    if not isinstance(item, dict) or not item.get('source') or not item.get('license'):
        return None
    rel = item.get('path', '')
    path = ROOT / rel
    if not rel.startswith('assets/photos/') or not path.is_file():
        # Published paths are relative to public/, not repository root.
        path = ROOT / 'public' / rel
    try:
        with path.open('rb') as handle:
            header = handle.read(12)
        if path.stat().st_size < 2000 or not (header.startswith(b'\xff\xd8\xff') or header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'RIFF')):
            return None
    except OSError:
        return None
    return item


def generate():
    catalog_path = OUT / 'catalog.json'
    try:
        previous = json.loads(catalog_path.read_text())
    except (ValueError, OSError):
        previous = {}
    index, failures = {}, {}
    for key, (title, caption) in CATALOG.items():
        cached = reusable_photo(previous, key)
        if cached is not None and cached.get('commons_title') == title:
            index[key] = cached
            print('PHOTO REUSED:', key, flush=True)
            continue
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
