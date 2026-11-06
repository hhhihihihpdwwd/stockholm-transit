"""V8 regression tests: route-graph connectivity, modal isolation, data import,
search hooks, and workflow guard against publishing an empty metro world.
Run: python -m unittest discover -s tests -v
"""
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

BASE=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(BASE/'scripts'))
from osm_extract import graphs_from_way_elements
from osm_routes import hav,assemble
import build


def way(railway=None,highway=None,points=None,wayid=1,underground=False):
    points=points or [(59.300,18.010),(59.301,18.010),(59.302,18.010)]
    tag={}
    if railway:tag['railway']=railway
    if highway:tag['highway']=highway
    if underground:tag['tunnel']='yes'
    nodes=list(range(wayid*100,wayid*100+len(points)))
    return {'type':'way','tags':tag,'nodes':nodes,'geometry':[{'lat':p[0],'lon':p[1]} for p in points]}

class LocalGraphTests(unittest.TestCase):
    def test_metro_is_on_subway_track(self):
        graphs=graphs_from_way_elements([way(railway='subway',underground=True)])
        self.assertIsNotNone(graphs['metro'].route((59.300,18.010),(59.302,18.010),'metro'))
        self.assertFalse(graphs['bus'].edges)
        self.assertFalse(graphs['commuter'].edges)

    def test_bus_only_on_connected_roads(self):
        graphs=graphs_from_way_elements([way(highway='residential')])
        track=graphs['bus'].route((59.300,18.010),(59.302,18.010),'bus')
        self.assertIsNotNone(track)
        self.assertFalse(graphs['metro'].edges)

    def test_disconnected_water_gap_not_crossed(self):
        graphs=graphs_from_way_elements([
            way(highway='residential',points=[(59.300,18.010),(59.3005,18.010)],wayid=2),
            way(highway='residential',points=[(59.305,18.020),(59.306,18.020)],wayid=3)])
        self.assertIsNone(graphs['bus'].route((59.300,18.010),(59.306,18.020),'bus'))

    def test_subway_tunnel_flags_survive(self):
        graphs=graphs_from_way_elements([way(railway='subway',underground=True)])
        result=assemble(graphs['metro'],[(59.300,18.010),(59.302,18.010)],'metro')
        self.assertIsNotNone(result)
        self.assertTrue(any(result[1]))

    def test_tram_not_drive_on_regular_rail(self):
        graphs=graphs_from_way_elements([way(railway='rail')])
        self.assertFalse(graphs['tram'].edges)
        self.assertTrue(graphs['rail'].edges)

    def test_pbf_is_explicit_fixed_provider(self):
        from osm_extract import download_sweden
        with self.assertRaises(ValueError):download_sweden('https://evil.test/data.osm.pbf')

class BuildTests(unittest.TestCase):
    def test_gtfs_archive_reading_for_metro_bus_train(self):
        from datetime import date
        fixture={
          'agency.txt':'agency_id,agency_name\na,SL\n',
          'routes.txt':'route_id,agency_id,route_type,route_short_name,route_long_name\nm,a,1,14,Mörby\nb,a,3,4,Röda bussen\nr,a,2,521,Stockholm Uppsala\n',
          'stops.txt':'stop_id,stop_name,stop_lat,stop_lon\ns1,T-Centralen,59.331,18.060\ns2,Östermalmstorg,59.334,18.074\ns3,Stockholm Central,59.329,18.057\ns4,Uppsala C,59.858,17.638\n',
          'calendar.txt':'service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\nsvc,1,1,1,1,1,1,1,20261101,20261201\n',
          'trips.txt':'route_id,service_id,trip_id,trip_headsign\nm,svc,metro,Mörby\nb,svc,bus,Röda bussen\nr,svc,rail,Uppsala\n',
          'stop_times.txt':'trip_id,arrival_time,departure_time,stop_id,stop_sequence\nmetro,08:00:00,08:00:00,s1,1\nmetro,08:04:00,08:04:00,s2,2\nbus,08:00:00,08:00:00,s1,1\nbus,08:05:00,08:05:00,s2,2\nrail,08:00:00,08:00:00,s3,1\nrail,08:45:00,08:45:00,s4,2\n',
        }
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            for name,body in fixture.items():z.writestr(name,body)
        buf.seek(0)
        r={};st={};sh={};days={d:[] for d in build.DAYS}
        with zipfile.ZipFile(buf) as z:
            build.process_feed(z,'Archive Sverige 2',r,st,sh,days,set())
        modes={idx:key[3] for key,idx in r.items()}
        seen={modes[t[0]] for t in days[build.DAYS[0]]}
        self.assertEqual(seen,{'metro','bus','rail'})

    def test_stop_filter_in_stockholm(self):
        self.assertTrue(build.inside(build.STOCKHOLM_BBOX,59.34,18.05))
        self.assertFalse(build.inside(build.STOCKHOLM_BBOX,57.71,11.97))

    def test_metro_classification(self):
        self.assertEqual(build.route_mode({'route_type':'1','route_short_name':'14'},'SL'),'metro')

    def test_commuter_classification(self):
        self.assertEqual(build.route_mode({'route_type':'2','route_short_name':'41'},'SL'),'commuter')

    def test_simulated_headways_are_flagged(self):
        from datetime import date
        route={('SL','14','','metro','1976D2'):0}
        dates={date(2026,11,9):[[0,'Mörby',-1,[[1,25200,25200],[2,25500,25500]]]]}
        build.fill_simulation_gaps(dates,route)
        self.assertTrue(any(len(x)==5 and x[4]=='modelled' for x in dates[date(2026,11,9)]))

    def test_search_and_details_exist(self):
        html=(BASE/'public/index.html').read_text()
        for s in ('tripSearch','searchResults','searchTimetable','nextName','stopScroll','photoImg','routeDraw','undergroundHere'):
            self.assertIn(s,html)

    def test_workflow_has_no_overpass(self):
        wf=(BASE/'.github/workflows/build.yml').read_text()
        self.assertIn('pip install --disable-pip-version-check osmium',wf)
        self.assertIn('workflow_dispatch:',wf)
        self.assertNotIn('schedule:',wf)
        self.assertIn('geometry[\'metro\']',wf)

if __name__=='__main__':unittest.main()
