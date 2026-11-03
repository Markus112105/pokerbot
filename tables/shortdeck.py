"""Example 36-card hold'em rules: flush beats full house; A6789 is a straight.

Generate with --variant tables.shortdeck. This explicit five-card reference
implementation favors clarity over speed; profile before a time-limited rebuild.
An Omaha callback should instead iterate combinations(hole, 2) crossed with
combinations(board, 3), evaluating only those legal five-card selections.
"""
from collections import Counter
from itertools import combinations

from tables.gen_equity import hand_class as classify

DECK = tuple(r + s for r in "6789TJQKA" for s in "cdhs")
HOLE_COUNT = 2


def _five(cards):
    ranks = sorted(("23456789TJQKA".index(c[0]) + 2 for c in cards), reverse=True)
    counts = Counter(ranks)
    groups = sorted(((n, r) for r, n in counts.items()), reverse=True)
    flush = len({c[1] for c in cards}) == 1
    unique = sorted(counts)
    straight = 9 if unique == [6, 7, 8, 9, 14] else (
        unique[-1] if len(unique) == 5 and unique[-1] - unique[0] == 4 else 0)
    if flush and straight:
        category, kickers = 8, [straight]
    elif groups[0][0] == 4:
        category, kickers = 7, [r for _, r in groups]
    elif flush:
        category, kickers = 6, ranks
    elif [n for n, _ in groups] == [3, 2]:
        category, kickers = 5, [r for _, r in groups]
    elif straight:
        category, kickers = 4, [straight]
    else:
        category = 3 if groups[0][0] == 3 else 2 if [n for n, _ in groups][:2] == [2, 2] else 1 if groups[0][0] == 2 else 0
        kickers = [r for _, r in groups]
    return (category << 24) | sum(r << (16 - 4 * i) for i, r in enumerate(kickers))


def rank(hole, board):
    """Return a comparable integer for the best legal short-deck five cards."""
    return max(_five(cards) for cards in combinations((*hole, *board), 5))
