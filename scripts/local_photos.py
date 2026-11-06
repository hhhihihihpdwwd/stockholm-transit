"""V10 static media manifest. Never downloads images, never fabricates photo credits."""
from __future__ import annotations
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PHOTOS = ROOT / 'public' / 'assets' / 'photos'


def valid_image(path: pathlib.Path) -> bool:
    if not path.is_file() or path.stat().st_size < 2000:
        return False
    with path.open('rb') as f:
        first=f.read(16)
    return first.startswith(b'\xff\xd8\xff') or first.startswith(b'\x89PNG\r\n\x1a\n') or (first.startswith(b'RIFF') and first[8:12]==b'WEBP')


def write_local_catalog(expected_keys=None) -> dict:
    PHOTOS.mkdir(parents=True, exist_ok=True)
    catalog_file=PHOTOS/'catalog.json'
    try:
        current=json.loads(catalog_file.read_text(encoding='utf-8'))
        if not isinstance(current,dict):current={}
    except (OSError,ValueError):
        current={}
    if expected_keys is None:
        # Import here to preserve the exact same set of keys approved for V9.1.
        from fetch_photos import CATALOG
        expected_keys=list(CATALOG)
    expected_keys=list(expected_keys)
    available={}
    missing={}
    for key in expected_keys:
        item=current.get(key)
        if not isinstance(item,dict):
            missing[key]='missing metadata'
            continue
        rel=item.get('path','')
        if not isinstance(rel,str) or not rel.startswith('assets/photos/') or '..' in pathlib.PurePosixPath(rel).parts:
            missing[key]='invalid local image path'
            continue
        photo=ROOT/'public'/rel
        if not valid_image(photo):
            missing[key]='local image file absent or invalid'
            continue
        if not item.get('source') or not item.get('license') or not item.get('author'):
            missing[key]='photo source/author/license absent'
            continue
        available[key]=item
    catalog_file.write_text(json.dumps(available,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report={'policy':'LOCAL_ONLY_NO_BUILD_DOWNLOAD', 'expected':len(expected_keys),'available':len(available),'missing':missing,'keys':sorted(available)}
    (PHOTOS/'photo-health.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__=='__main__':
    report=write_local_catalog()
    print(f"Local vehicle photos: {report['available']}/{report['expected']}; missing: {', '.join(report['missing']) or 'none'}")
