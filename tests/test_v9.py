"""V9 tests for complete-rail routing architecture and safe route publication."""
import pathlib,sys,unittest,collections
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from osm_routes import Graph,hav
from osm_extract import graphs_from_way_elements,route_pattern,line_stop_patterns
import build

def way(points,way_id,mode='rail',tunnel=False):
    tags={'highway':'residential'} if mode=='bus' else {'railway':mode}
    if tunnel:tags['tunnel']='yes'
    ids=[way_id*10000+i for i in range(len(points))]
    return {'type':'way','tags':tags,'nodes':ids,'geometry':[{'lat':a,'lon':b} for a,b in points]}

class V9RailTest(unittest.TestCase):
    def test_commuter_route_preserves_uppsala_outside_stockholm_bbox(self):
        station={'in_stockholm':False,'in_national':True}
        self.assertTrue(build.stop_allowed('commuter',station))
        self.assertEqual(build.shape_clip_bbox('commuter'),build.NATIONAL_BBOX)

    def test_multiple_candidate_tracks_finds_connected_pair(self):
        # A spurious isolated track is closer to the second platform than
        # the actual connected railway. V8 frequently snapped to the wrong one.
        a=[(59.30,18.010),(59.301,18.010),(59.302,18.010),(59.303,18.010)]
        spur=[(59.302,18.01015),(59.3023,18.01015)]
        g=graphs_from_way_elements([way(a,1),way(spur,2)])['rail']
        result=g.route((59.30,18.010),(59.302,18.01014),'rail')
        self.assertIsNotNone(result)
        self.assertGreater(len(result[0]),1)
        self.assertLess(result[0][-1][1],18.0101)

    def test_router_rejects_disconnected_track_even_if_geographically_close(self):
        a=[(59.3,18.0),(59.301,18.0)]
        b=[(59.304,18.001),(59.305,18.001)]
        g=graphs_from_way_elements([way(a,3),way(b,4)])['rail']
        self.assertIsNone(g.route((59.3,18.0),(59.305,18.001),'rail'))

    def test_fully_matched_shape_has_railway_bends_not_straight_chords(self):
        points=[(59.3,18.01),(59.301,18.01),(59.301,18.011),(59.302,18.011),(59.303,18.011)]
        g=graphs_from_way_elements([way(points,5)])['rail']
        route=route_pattern(g,{0:points[0],1:points[-1]},(0,1),'rail',{})
        self.assertIsNotNone(route)
        shape,_=route
        self.assertGreaterEqual(len(shape),4)
        self.assertIn((59.301,18.011),shape)

    def test_route_pattern_never_fabricates_missing_bus_road(self):
        pts=[(59.300,18.010),(59.301,18.010)]
        g=graphs_from_way_elements([way(pts,6,mode='bus')])['bus']
        result=route_pattern(g,{0:pts[0],1:(59.306,18.04)},(0,1),'bus',{})
        self.assertIsNone(result)

    def test_no_estimated_straight_cord_for_intercity_train(self):
        code=(ROOT/'scripts/build.py').read_text()
        self.assertNotIn('estimated-corridor',code)
        self.assertIn('V9 UNROUTED TRIPS',code)

    def test_national_network_and_regional_streets_separated(self):
        code=(ROOT/'scripts/osm_extract.py').read_text()
        self.assertIn('download.geofabrik.de/europe/sweden-latest.osm.pbf',code)
        self.assertIn('complete_ways',code)
        self.assertIn('w/railway=',code)

    def test_speed_display_flags_infeasible_values(self):
        html=(ROOT/'public/index.html').read_text()
        self.assertIn('invalidSpeed?null',html)
        self.assertIn('pg.speed===null',html)

if __name__=='__main__':unittest.main()
