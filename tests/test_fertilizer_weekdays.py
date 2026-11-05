import unittest
from datetime import datetime

class WeeklyMaskTests(unittest.TestCase):
    def test_default(self):
        mask = 127
        self.assertEqual(mask.bit_count(), 7)
    def test_mon_wed_fri(self):
        mask = sum(1 << d for d in (0, 2, 4))
        self.assertEqual(mask.bit_count(), 3)
        self.assertTrue(mask & (1 << datetime(2026, 11, 6).weekday()))
        self.assertFalse(mask & (1 << datetime(2026, 11, 5).weekday()))
    def test_disabled(self):
        self.assertFalse(0 & (1 << 4))
if __name__ == "__main__":
    unittest.main()
