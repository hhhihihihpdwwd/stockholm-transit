import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from scripts import local_photos

class StaticPhotoTests(unittest.TestCase):
    def test_offline_catalog_does_not_keep_missing_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            photos=root/'public/assets/photos'
            photos.mkdir(parents=True)
            (photos/'x60.jpg').write_bytes(b'\xff\xd8\xff'+b'X'*3000)
            given={
                'commuter_x60':{'path':'assets/photos/x60.jpg','source':'https://commons.wikimedia.org/wiki/File:X60.jpg','author':'Tester','license':'CC BY 4.0'},
                'rail_arlanda':{'path':'assets/photos/missing.jpg','source':'https://commons.wikimedia.org/wiki/File:Train.jpg','author':'Tester','license':'CC BY 4.0'}}
            (photos/'catalog.json').write_text(json.dumps(given))
            with patch.object(local_photos,'ROOT',root),patch.object(local_photos,'PHOTOS',photos):
                report=local_photos.write_local_catalog(expected_keys=['commuter_x60','rail_arlanda'])
            self.assertEqual(report['available'],1)
            self.assertIn('rail_arlanda',report['missing'])
            saved=json.loads((photos/'catalog.json').read_text())
            self.assertEqual(set(saved),{'commuter_x60'})

    def test_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d)
            photos=root/'public/assets/photos'
            photos.mkdir(parents=True)
            (photos/'catalog.json').write_text(json.dumps({'bad':{'path':'assets/photos/../../secrets.jpg','source':'x','author':'x','license':'x'}}))
            with patch.object(local_photos,'ROOT',root),patch.object(local_photos,'PHOTOS',photos):
                report=local_photos.write_local_catalog(expected_keys=['bad'])
            self.assertIn('bad',report['missing'])

if __name__=='__main__':unittest.main()
