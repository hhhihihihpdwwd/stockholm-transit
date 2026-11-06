"""Regression checks for the frontend geometry audit."""
import sys,unittest,pathlib
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'scripts'))
from validate_display import aligned

class DisplayAuditTests(unittest.TestCase):
    def test_correct_path_and_stops_render(self):
        shape=[(59.3,18.0),(59.3005,18.0005),(59.301,18.001)]
        self.assertEqual(aligned(shape,[shape[0],shape[-1]],'commuter')[0],True)
    def test_station_too_far_not_displayable(self):
        shape=[(59.3,18.0),(59.301,18.0)]
        self.assertEqual(aligned(shape,[(59.3,18.01),(59.301,18.01)],'bus')[0],False)
    def test_no_track_not_displayable(self):
        self.assertEqual(aligned(None,[(59.3,18.0),(59.301,18.0)],'rail'),(False,'missing_shape'))

if __name__=='__main__':unittest.main()
