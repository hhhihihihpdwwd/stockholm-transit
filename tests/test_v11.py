"""V11 regressions: real road geometry, partial coverage, approved media & deployment guards."""
import json
import pathlib
import sys
import unittest

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from osm_extract import graphs_from_way_elements,route_pattern_detailed,partial_route_segments
from route_quality import cumulative,valid_anchors
from local_photos import valid_image


def road(points,offset):
    return {'type':'way','tags':{'highway':'residential'},
            'nodes':[offset+i for i in range(len(points))],
            'geometry':[{'lat':a,'lon':b} for a,b in points]}


class GeometryV11Tests(unittest.TestCase):
    def test_baked_stop_anchors_on_real_osm_bends(self):
        coords=[(59.30,18.01),(59.301,18.01),(59.301,18.011),
                (59.302,18.011),(59.303,18.011)]
        graph=graphs_from_way_elements([road(coords,1)])['bus']
        points={0:coords[0],1:coords[2],2:coords[4]}
        res=route_pattern_detailed(graph,points,(0,1,2),'bus',{})
        self.assertIsNotNone(res)
        shape,tunnels,anchors=res
        self.assertIn(coords[2],shape)
        self.assertEqual(len(anchors),3)
        self.assertTrue(valid_anchors(shape,anchors,3))
        self.assertGreater(anchors[2],anchors[1])
        self.assertGreater(anchors[1],anchors[0])
        self.assertAlmostEqual(anchors[2],cumulative(shape)[-1],delta=3)

    def test_duplicate_platform_keeps_full_line(self):
        coords=[(59.3,18.01),(59.301,18.01),(59.302,18.01)]
        graph=graphs_from_way_elements([road(coords,10)])['bus']
        p={0:coords[0],1:coords[0],2:coords[2]}
        res=route_pattern_detailed(graph,p,(0,1,2),'bus',{})
        self.assertIsNotNone(res)
        self.assertAlmostEqual(res[2][0],res[2][1],delta=.1)
        self.assertTrue(valid_anchors(res[0],res[2],3))

    def test_disconnected_streets_are_partial_not_fabricated(self):
        west=[(59.3,18.01),(59.301,18.01),(59.302,18.01)]
        east=[(59.32,18.04),(59.321,18.04),(59.322,18.04)]
        graph=graphs_from_way_elements([road(west,20),road(east,30)])['bus']
        p={0:west[0],1:west[-1],2:east[0],3:east[-1]}
        self.assertIsNone(route_pattern_detailed(graph,p,(0,1,2,3),'bus',{}))
        pieces=partial_route_segments(graph,p,(0,1,2,3),'bus',{})
        self.assertEqual([(a,b) for a,b,*_ in pieces],[(0,1),(2,3)])
        for a,b,shape,under,anchors in pieces:
            self.assertTrue(valid_anchors(shape,anchors,b-a+1))
            self.assertTrue(all(lon<18.02 for _,lon in shape) or all(lon>18.03 for _,lon in shape))

    def test_anchor_rejects_nonmonotonic_and_out_of_range(self):
        s=[(59.30,18.01),(59.31,18.01)]
        self.assertFalse(valid_anchors(s,[0,110,109],3))
        self.assertFalse(valid_anchors(s,[0,999999],2))
        self.assertTrue(valid_anchors(s,[0,cumulative(s)[-1]],2))


class ReleaseGuards(unittest.TestCase):
    def test_exact_25_approved_photos_and_no_substitution(self):
        data=json.loads((ROOT/'approved_photos.json').read_text())
        from fetch_photos import CATALOG,ALTERNATES
        self.assertEqual(len(data['photos']),25)
        self.assertEqual(set(data['photos']),set(CATALOG))
        self.assertFalse(ALTERNATES)
        self.assertTrue(all(v['url'].startswith('https://commons.wikimedia.org/wiki/File:') for v in data['photos'].values()))

    def test_frontend_does_not_drop_all_photos_if_local_catalog_missing(self):
        html=(ROOT/'public/index.html').read_text()
        self.assertIn('const APPROVED_PHOTOS=',html)
        self.assertIn('Special:Redirect/file/',html)
        self.assertIn("if(!(agency==='sl'",html)
        self.assertIn('new Image()',html)

    def test_route_renderer_reuses_map_layers_and_clock_is_smooth(self):
        html=(ROOT/'public/index.html').read_text()
        self.assertIn('routeGrey.setLatLngs(future)',html)
        self.assertIn('segmentLines[si].blue.setLatLngs(past)',html)
        self.assertIn('performance.now()-clockReferenceMs',html)
        self.assertIn('v.segments?.find',html)

    def test_deploy_gated_for_photo_and_route_regression(self):
        yml=(ROOT/'.github/workflows/build.yml').read_text()
        self.assertIn("if v['available']<20",yml)
        self.assertIn('Prevent publishing a route-visibility regression',yml)
        self.assertIn('uses: actions/deploy-pages@v4',yml)
        self.assertLess(yml.index('Import ONLY the 25 photos'),yml.index('Generate historical services'))


class MediaEncodingV11(unittest.TestCase):
    def test_same_approved_photo_resizes_without_switching_subject(self):
        # Network calls are mocked; verifies the exact approved Wikimedia API
        # response is decoded and stored as an optimized image with attribution.
        import io, tempfile
        from unittest.mock import patch
        from PIL import Image
        import fetch_photos
        buf=io.BytesIO()
        Image.new('RGB',(1700,900),(120,160,220)).save(buf,format='JPEG')
        data=buf.getvalue()
        metadata={'query':{'pages':{'10':{'imageinfo':[{
           'mime':'image/jpeg','thumburl':'https://thumb.wikimedia.org/test.jpg',
           'url':'https://upload.wikimedia.org/test.jpg',
           'descriptionurl':'https://commons.wikimedia.org/wiki/File:Known.jpg',
           'extmetadata':{'Artist':{'value':'Example photographer'},'LicenseShortName':{'value':'CC BY-SA 4.0'}}
        }]}}}}
        responses=[json.dumps(metadata).encode('utf8'),data]
        with tempfile.TemporaryDirectory() as tmp, patch.object(fetch_photos,'OUT',pathlib.Path(tmp)),patch.object(fetch_photos,'request_bytes',side_effect=responses):
            item=fetch_photos.download_one('test_vehicle','Known.jpg','Known train')
            self.assertEqual(item['commons_title'],'Known.jpg')
            self.assertEqual(item['author'],'Example photographer')
            self.assertEqual(item['license'],'CC BY-SA 4.0')
            name=pathlib.Path(tmp)/'test_vehicle.jpg'
            self.assertTrue(valid_image(name))
            with Image.open(name) as result:
                result.verify()
            with Image.open(name) as result:
                self.assertLessEqual(result.width,1100)
                self.assertEqual(result.format,'JPEG')


if __name__ == '__main__': unittest.main()
