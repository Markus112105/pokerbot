"""Evaluator, feature, Monte Carlo and push/fold invariants."""
import itertools
import random
import unittest

from bot.strength import evaluate, percentile, preflop
from bot.tables import EQUITY, PUSHFOLD
from tables.gen_equity import DECK, class_weights, generate, hand_class, rank_python, starting_classes
from tables.pushfold import build, lookup
from tables import shortdeck


def reference_five(cards):
    """Independent five-card tuple evaluator used to check seven-card selection."""
    ranks = sorted(("23456789TJQKA".index(c[0]) + 2 for c in cards), reverse=True)
    groups = sorted(((ranks.count(r), r) for r in set(ranks)), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    unique = sorted(set(ranks))
    straight = 5 if unique == [2, 3, 4, 5, 14] else (
        unique[-1] if len(unique) == 5 and unique[-1] - unique[0] == 4 else 0)
    if flush and straight:
        category, kickers = 8, [straight]
    elif groups[0][0] == 4:
        category, kickers = 7, [r for _, r in groups]
    elif [n for n, _ in groups] == [3, 2]:
        category, kickers = 6, [r for _, r in groups]
    elif flush:
        category, kickers = 5, ranks
    elif straight:
        category, kickers = 4, [straight]
    else:
        category = 3 if groups[0][0] == 3 else 2 if [n for n, _ in groups][:2] == [2, 2] else 1 if groups[0][0] == 2 else 0
        kickers = [r for _, r in groups]
    return (category << 24) | sum(r << (16 - 4 * i) for i, r in enumerate(kickers))


class TablesStrengthTests(unittest.TestCase):
    def test_classes_and_data(self):
        self.assertEqual(len(starting_classes()), 169)
        self.assertEqual(len(EQUITY), 169)
        self.assertEqual(hand_class(["Ac", "Kh"]), "AKo")
        self.assertEqual(hand_class(["Ks", "As"]), "AKs")
        for row in EQUITY.values():
            self.assertEqual(set(row), {"1", "2", "4", "7"})
            values = [row[str(n)] for n in (1, 2, 4, 7)]
            self.assertTrue(all(0 <= v <= 1 for v in values))
            self.assertEqual(values, sorted(values, reverse=True))
        self.assertGreater(preflop(["As", "Ad"]), .83)
        self.assertLess(percentile(["As", "Ad"]), .01)

    def test_reference_evaluator(self):
        rng = random.Random(451)
        for _ in range(1000):
            cards = rng.sample(DECK, 7)
            expected = max(reference_five(c) for c in itertools.combinations(cards, 5))
            self.assertEqual(rank_python(cards[:2], cards[2:]), expected, cards)

    def test_wheel_and_board_ties(self):
        self.assertEqual(rank_python(["Ac", "2d"], ["3h", "4s", "5c"]) >> 24, 4)
        board = ["As", "Ks", "Qs", "Js", "Ts"]
        self.assertEqual(rank_python(["2d", "3d"], board), rank_python(["9h", "9d"], board))

    def test_features(self):
        f = evaluate(["As", "Ks"], ["Qs", "Js", "2d"])
        self.assertTrue(f.flush_draw)
        self.assertTrue(f.gutshot)
        self.assertFalse(f.open_ended)
        self.assertEqual(f.overcards, 2)
        self.assertTrue(evaluate(["8s", "9d"], ["6s", "7h", "Ac"]).open_ended)
        self.assertTrue(evaluate(["As", "Kd"], ["Ah", "7c", "2d"]).top_pair)
        self.assertFalse(evaluate(["Ks", "Qd"], ["Ah", "Ac", "2d"]).top_pair)
        self.assertTrue(evaluate(["Ks", "Qd"], ["Ah", "Ac", "Ad"]).board_only)
        self.assertTrue(evaluate(["2s", "3d"], ["Ah", "Ac", "Kd", "Ks"]).board_only)
        self.assertFalse(evaluate(["As", "Qd"], ["Ah", "Ac", "2d"]).board_only)
        self.assertFalse(evaluate(["2s", "3d"], ["6c", "7c", "8c", "9c"]).open_ended)
        self.assertFalse(evaluate(["As", "Ks"], ["Qs", "Js", "2d", "3h", "4d"]).flush_draw)

    def test_generator_custom_and_ties(self):
        result = generate(deck=DECK[:24], ranking=constant_rank, samples=2, workers=1)
        for row in result.values():
            for n in (1, 2, 4, 7):
                self.assertEqual(row[str(n)], 1 / (n + 1))

    def test_pushfold(self):
        self.assertTrue(lookup("AA", 15, 7, "early")["shove"])
        self.assertFalse(lookup("72o", 15, 7, "early")["call"])
        for context, hands in PUSHFOLD["bounds"].items():
            for hand, bounds in hands.items():
                for action in ("shove", "call"):
                    low, high = bounds[f"min_stack_to_{action}"], bounds[f"max_stack_to_{action}"]
                    if high is not None:
                        self.assertEqual(low, 2)
                        self.assertTrue(PUSHFOLD["by_stack"][f"{high}:{context}"][hand][action])

    def test_variant_weights(self):
        weights = class_weights(shortdeck.DECK)
        self.assertEqual(len(weights), 81)
        self.assertEqual(sum(weights.values()), 630)
        self.assertEqual(weights["AA"], 6)
        self.assertEqual(weights["AKs"], 4)
        self.assertEqual(weights["AKo"], 12)
        self.assertEqual(sum(class_weights(DECK).values()), 1326)
        # An arbitrary classifier and three hole cards must count concrete deals.
        self.assertEqual(class_weights(DECK[:6], 3, lambda _: "all"), {"all": 20})
        result = build({"strong": {"1": .8}, "weak": {"1": .2}},
                       {"strong": 1, "weak": 99})
        self.assertTrue(result["by_stack"]["15:7:early"]["strong"]["shove"])
        self.assertFalse(result["by_stack"]["15:7:early"]["weak"]["shove"])

    def test_shortdeck_rankings(self):
        flush = ["As", "Js", "9s", "7s", "6s"]
        fullhouse = ["Ah", "Ac", "Ad", "Kh", "Kc"]
        self.assertGreater(shortdeck.rank(flush[:2], flush[2:]),
                           shortdeck.rank(fullhouse[:2], fullhouse[2:]))
        self.assertLess(rank_python(flush[:2], flush[2:]),
                        rank_python(fullhouse[:2], fullhouse[2:]))
        wheel = shortdeck.rank(["As", "6h"], ["7d", "8c", "9s"])
        ten_high = shortdeck.rank(["Th", "6h"], ["7d", "8c", "9s"])
        self.assertEqual(wheel >> 24, 4)
        self.assertGreater(ten_high, wheel)
        self.assertEqual(len(starting_classes(shortdeck.DECK)), 81)


def constant_rank(hole, board):
    return 0


if __name__ == "__main__":
    unittest.main()
