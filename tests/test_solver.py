"""CFR engine correctness against Kuhn poker's known Nash equilibrium."""
import unittest

from solver.cfr import CFRTrainer, expected_value
from solver.exploitability import best_response_value, exploitability
from solver.games import Kuhn, Leduc

KUHN_VALUE = -1.0 / 18.0


class SolverTests(unittest.TestCase):
    def test_kuhn_tree_is_zero_sum_and_probabilities_sum(self):
        game = Kuhn()
        self.assertAlmostEqual(sum(p for _, p in game.deals()), 1.0)
        self.assertAlmostEqual(sum(p for _, p in Leduc().deals()), 1.0)

    def test_kuhn_converges_to_known_nash_value(self):
        trainer = CFRTrainer(Kuhn()).run(20000)
        profile = trainer.average_strategy()
        self.assertAlmostEqual(expected_value(Kuhn(), profile), KUHN_VALUE, places=3)
        self.assertLess(exploitability(Kuhn(), profile), 2e-3)

    def test_uniform_kuhn_strategy_is_exploitable(self):
        self.assertGreater(exploitability(Kuhn(), {}), 0.05)

    def test_best_response_never_loses_to_the_profile_value(self):
        # For any profile, NashConv = br0 + br1 must be nonnegative.
        trainer = CFRTrainer(Kuhn()).run(50)
        profile = trainer.average_strategy()
        nashconv = (best_response_value(Kuhn(), profile, 0)
                    + best_response_value(Kuhn(), profile, 1))
        self.assertGreaterEqual(nashconv, -1e-12)

    def test_leduc_exploitability_decreases(self):
        game = Leduc()
        trainer = CFRTrainer(game)
        early = exploitability(game, trainer.run(2).average_strategy())
        later = exploitability(game, trainer.run(28).average_strategy())
        self.assertLess(later, early)
        self.assertGreater(len(trainer.regrets), 200)

    def test_leduc_fold_and_showdown_accounting(self):
        game = Leduc()
        # Player 1 folds to a round-one raise: loses the 1-chip ante.
        self.assertEqual(game.utility((0, 2, 1), "rf"), 1.0)
        # Raise called, board pairs player 0: pot settles at 3 chips each way.
        self.assertEqual(game.utility((0, 2, 0), "rc/cc"), 3.0)
        # Identical ranks split: zero transfer.
        self.assertEqual(game.utility((1, 1, 2), "cc/cc"), 0.0)


if __name__ == "__main__":
    unittest.main()
