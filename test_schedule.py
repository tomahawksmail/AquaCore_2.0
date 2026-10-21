import unittest
from datetime import datetime,timedelta
from scheduler import scheduled_state,next_transition

class ScheduleTest(unittest.TestCase):
    def test_day(self):
        o={'co2_on':timedelta(hours=7),'co2_off':timedelta(hours=10)}
        self.assertFalse(scheduled_state('co2_status',o,datetime(2026,10,21,6,59)))
        self.assertTrue(scheduled_state('co2_status',o,datetime(2026,10,21,7)))
        self.assertFalse(scheduled_state('co2_status',o,datetime(2026,10,21,10)))
        self.assertEqual(next_transition('co2_status',o,datetime(2026,10,21,9)),datetime(2026,10,21,10))
    def test_overnight(self):
        o={'o2_on':timedelta(hours=20),'o2_off':timedelta(hours=6)}
        self.assertTrue(scheduled_state('o2_status',o,datetime(2026,10,21,23)))
        self.assertTrue(scheduled_state('o2_status',o,datetime(2026,10,22,3)))
        self.assertFalse(scheduled_state('o2_status',o,datetime(2026,10,21,12)))
        self.assertEqual(next_transition('o2_status',o,datetime(2026,10,21,23)),datetime(2026,10,22,6))
    def test_same_time_rejected(self):
        with self.assertRaises(ValueError):scheduled_state('co2_status',{'co2_on':timedelta(hours=7),'co2_off':timedelta(hours=7)},datetime.now())
if __name__=='__main__':unittest.main()
