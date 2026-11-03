import unittest
from array import array

from sim.run import percentile, run


class RunTests(unittest.TestCase):
    def test_percentile(self):
        self.assertEqual(percentile(range(1, 101)), 99)
        self.assertEqual(percentile(array("Q", range(1, 101))), 99)

    def test_invalid_count_and_lineup(self):
        for count, lineup in [(0, "mixed"), (1, "missing"), (1, "random,random")]:
            with self.assertRaises(ValueError):
                run(count, lineup)

    def test_report(self):
        report = run(2, "always-call")
        self.assertEqual(report["tables"], 2)
        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["hero_errors"], 0)
        self.assertIn("hero_timeouts", report)
        self.assertIn("stalls", report)
        self.assertAlmostEqual(sum(report["finishing_position_histogram"].values()), 2, places=5)
        averages = report["average_points"]
        self.assertAlmostEqual(averages["hero"]+7*averages["always-call"], 28, places=5)
