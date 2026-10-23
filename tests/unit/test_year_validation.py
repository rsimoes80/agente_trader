from datetime import datetime, timezone
import unittest

from run_year_validation import windows


class CalendarYearWindowsTests(unittest.TestCase):
    def test_partial_year_never_creates_future_months(self):
        end = datetime(2026, 10, 23, 14, tzinfo=timezone.utc)
        result = windows(2026, end)
        self.assertEqual(len(result), 11)
        self.assertEqual(result['all'][0], datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(result['2026-10'][1], end)
        self.assertNotIn('2026-11', result)
        self.assertTrue(all(b <= end for a, b in result.values()))

    def test_full_year_has_twelve_contiguous_months(self):
        end = datetime(2027, 1, 1, tzinfo=timezone.utc)
        result = windows(2026, end)
        self.assertEqual(len(result), 13)
        months = [v for k, v in result.items() if k != 'all']
        self.assertEqual(months[-1][1], end)
        self.assertTrue(all(a[1] == b[0] for a, b in zip(months, months[1:])))

    def test_invalid_cutoff_is_rejected(self):
        for end in ('2025-12-31T00:00:00+00:00', '2027-01-02T00:00:00+00:00'):
            with self.assertRaises(ValueError):
                windows(2026, end)
