"""Direct eval7 / rank_python agreement: categories and pairwise ordering.

The two backends must be interchangeable: bot/strategy.py reads the made-hand
category from value >> 24, and sim/engine.py settles pots by comparing raw
values of hands on a shared board. Matching tournament averages between runs
is not evidence of that (host stalls make runs diverge); this test checks the
properties the code actually relies on, on a deterministic sample.
"""
import random
import unittest

from tables.gen_equity import DECK, EVAL_CARDS, eval7, rank_python


@unittest.skipIf(eval7 is None, "eval7 not installed; pure-Python path is primary")
class BackendAgreementTests(unittest.TestCase):
    def test_categories_and_ordering_match(self):
        rng = random.Random(90210)
        for _ in range(4000):
            cards = rng.sample(DECK, 9)
            board = cards[:rng.choice((5, 6, 7)) - 2]  # 3-5 community cards
            holes = [tuple(cards[-4:-2]), tuple(cards[-2:])]
            values = {}
            for hole in holes:
                py = rank_python(hole, board)
                ev = eval7.evaluate([EVAL_CARDS[c] for c in (*hole, *board)])
                self.assertEqual(py >> 24, ev >> 24,
                                 f"category differs for {hole} on {board}")
                values[hole] = (py, ev)
            (pa, ea), (pb, eb) = values[holes[0]], values[holes[1]]
            self.assertEqual((pa > pb) - (pa < pb), (ea > eb) - (ea < eb),
                             f"ordering differs for {holes} on {board}")
