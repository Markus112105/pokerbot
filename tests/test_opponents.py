import unittest

from sim.engine import Engine
from sim.opponents import KINDS, Opponent


class OpponentTests(unittest.TestCase):
    def test_all_baselines_run_with_legal_actions(self):
        for kind in KINDS:
            result = Engine([Opponent(kind, i) for i in range(8)], cap=5).play()
            self.assertEqual(result.errors, 0, kind)
            self.assertAlmostEqual(sum(result.points), 28)

    def test_unknown_baseline_rejected(self):
        with self.assertRaises(ValueError):
            Opponent("not-a-bot")
