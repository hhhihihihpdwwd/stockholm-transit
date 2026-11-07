"""Generate a LOCAL, attributed photo library from a curated list of exact Wikimedia files.

No arbitrary keyword search. Never insert photographs of a different vehicle type.
The normal webpage fetches /assets/photos/*.jpg, never Wikimedia.
Any failed/missing photo falls back to the user's generated realistic icon.
"""
import gzip
import io
import concurrent.futures
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



def request_bytes(url, timeout=13, limit=2_200_000):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'StockholmTransitV11/1.0 (https://github.com/hhhihihihpdwwd/stockholm-transit; static photo library)',
        'Accept': '*/*',
        'Accept-Encoding': 'identity',
    })
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                data = res.read(limit + 1)
                if res.headers.get('Content-Encoding', '').lower() == 'gzip':
                    data = gzip.decompress(data)
            if len(data) > limit:
                raise ValueError('image exceeds size limit')
            return data
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            if attempt == 1 or isinstance(exc, urllib.error.HTTPError) and exc.code in (400, 404, 410):
                raise
            time.sleep(1.0 * (attempt + 1))


def text_only(s):
    return html.unescape(re.sub(r'<[^>]+>', '', s or '')).strip()


def download_one(key, title, caption):
    api = 'https://commons.wikimedia.org/w/api.php?'
    params = {
        'action': 'query', 'format': 'json', 'titles': 'File:' + title,
        'prop': 'imageinfo', 'iiprop': 'url|mime|extmetadata', 'iiurlwidth': '960',
    }
    metadata = json.loads(request_bytes(api + urllib.parse.urlencode(params), timeout=18, limit=250_000))
    page = next(iter(metadata['query']['pages'].values()))
    imageinfo = page.get('imageinfo', [{}])[0]
    mime = imageinfo.get('mime', '')
    if mime not in ('image/jpeg', 'image/png', 'image/webp'):
        raise ValueError('missing or unsuitable image: ' + mime)
    # Both URLs point to the *same approved Commons original*.  On Commons,
    # generating a thumbnail can intermittently return 4xx/5xx.  Fallback to
    # the original, then shrink locally, never substitute another photograph.
    urls=list(dict.fromkeys(u for u in (imageinfo.get('thumburl'), imageinfo.get('url')) if u))
    if not urls:
        raise ValueError('no file URL')
    failures=[]
    data=None
    for download_url in urls:
        try:
            data=request_bytes(download_url, timeout=45, limit=25_000_000)
            break
        except Exception as exc:
            failures.append(type(exc).__name__+': '+str(exc)[:100])
    if data is None:
        raise RuntimeError('approved thumbnail and approved original unavailable: '+'; '.join(failures))
    # Reject truncated/corrupt downloads and keep GitHub Pages lightweight.
    # Pillow is a small, deterministic import-time dependency in Actions.
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as opened:
        opened.load() # fully decode before approving, not just magic bytes
        img=ImageOps.exif_transpose(opened)
        img.thumbnail((1100,1100),resample=Image.Resampling.LANCZOS)
        if img.mode in ('RGBA','LA') or (img.mode=='P' and 'transparency' in img.info):
            rgb=Image.new('RGB',img.size,'white')
            if img.mode!='RGBA':img=img.convert('RGBA')
            rgb.paste(img,mask=img.getchannel('A'))
            img=rgb
        else:
            img=img.convert('RGB')
        out=io.BytesIO()
        img.save(out,'JPEG',quality=86,optimize=True,progressive=True)
        data=out.getvalue()
    if len(data)<2_000 or len(data)>2_200_000:
        raise ValueError('approved image could not be encoded to a usable lightweight JPEG')
    suffix='.jpg'
    ext = imageinfo.get('extmetadata', {})
    credit = (text_only(ext.get('Artist', {}).get('value', '')) or 'Fotograf: siehe Originaldatei auf Wikimedia Commons')[:150]
    license_name = text_only(ext.get('LicenseShortName', {}).get('value', ''))[:80]
    # No photo without traceable source and author/license for attribution.
    source = imageinfo.get('descriptionurl', '')
    if not source or not license_name:
        raise ValueError('source or license metadata missing')
    # Atomic write: a failed request never truncates a previously approved file.
    target=OUT/(key+suffix)
    part=OUT/(key+suffix+'.part')
    part.write_bytes(data)
    part.replace(target)
    return {'path': 'assets/photos/' + key + suffix, 'label': caption,
            'source': source, 'author': credit, 'license': license_name,
            'commons_title': title, 'bytes': len(data), 'processed': 'JPEG 1100px, quality 86'}


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


def _job(key, title, caption, previous):
    cached = reusable_photo(previous, key)
    if cached is not None and cached.get('commons_title') == title:
        return key, cached, []
    errors=[]
    for candidate in [title]: # never substitute another user's rejected photo
        try:
            item=download_one(key,candidate,caption)
            return key,item,[]
        except Exception as exc:
            errors.append(candidate+': '+type(exc).__name__+' '+str(exc)[:150])
    return key,None,errors


def generate():
    """Import up to 25 approved originals, with bounded parallelism and audit.

    A failed download never silently swaps a vehicle for another model. The
    bundled public HTML uses only these exact approved titles as a remote
    fallback until they have been committed locally.
    """
    catalog_path = OUT / 'catalog.json'
    try:
        previous = json.loads(catalog_path.read_text(encoding='utf-8'))
        if not isinstance(previous,dict):previous={}
    except (ValueError, OSError):
        previous={}
    index, failures = {}, {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures={pool.submit(_job,k,title,caption,previous):k for k,(title,caption) in CATALOG.items()}
        for future in concurrent.futures.as_completed(futures):
            key=futures[future]
            try:
                _, item, errors=future.result()
            except Exception as exc:
                item=None;errors=[type(exc).__name__+': '+str(exc)[:180]]
            if item:
                index[key]=item
                print('PHOTO '+('REUSED' if previous.get(key)==item else 'DOWNLOADED')+':',key,round(item.get('bytes',0)/1024),'KiB',flush=True)
            else:
                failures[key]=errors
                print('PHOTO MISSING:',key,' | '.join(errors)[:240],flush=True)
    index=dict(sorted(index.items()))
    catalog_path.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'expected':len(CATALOG), 'available':len(index), 'missing':failures,
            'available_keys':sorted(index),'approved_titles_only':True}
    (OUT/'photo-health.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('V11 PHOTO HEALTH:',len(index),'/',len(CATALOG),'missing:',sorted(failures),flush=True)
    return index

if __name__ == '__main__':
    generate()
