"""Offline Monte Carlo equity generator; custom rank(hole, board) returns higher=better.

Suit symmetry is used only for a complete, equal-rank four-suit deck. Supply a
custom classify function for asymmetric decks. Opponents are sampled jointly
without replacement, and tied winners divide the pot. Spawn-safe ranking and
classification functions must be top-level module functions.
"""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import importlib
import itertools
import json
import os
from pathlib import Path
import random
import time

try:
    import eval7
except ImportError:
    eval7 = None

RANKS = "23456789TJQKA"
DECK = tuple(r + s for r in RANKS for s in "cdhs")
CARD_INFO = {c: (RANKS.index(c[0]) + 2, c[1]) for c in DECK}
EVAL_CARDS = {c: eval7.Card(c) for c in DECK} if eval7 else {}


def _straight(mask):
    if mask & (1 << 14):
        mask |= 1 << 1
    runs = mask & (mask >> 1) & (mask >> 2) & (mask >> 3) & (mask >> 4)
    return runs.bit_length() + 3 if runs else 0


def rank_python(hole, board):
    """Best five from 5-9 cards, using rank counts and suit bitsets, not subsets."""
    counts = [0] * 15
    suits = {}
    mask = 0
    for card in (*hole, *board):
        rank, suit = CARD_INFO[card]
        counts[rank] += 1
        suits[suit] = suits.get(suit, 0) | (1 << rank)
        mask |= 1 << rank
    flush = next((m for m in suits.values() if m.bit_count() >= 5), 0)
    straight_flush = _straight(flush) if flush else 0
    groups = sorted(((n, r) for r, n in enumerate(counts) if n), reverse=True)
    descending = [r for r in range(14, 1, -1) if counts[r]]
    if straight_flush:
        category, kickers = 8, [straight_flush]
    elif groups[0][0] == 4:
        quad = groups[0][1]
        category, kickers = 7, [quad, next(r for r in descending if r != quad)]
    elif groups[0][0] >= 3 and len(groups) > 1 and groups[1][0] >= 2:
        category, kickers = 6, [groups[0][1], groups[1][1]]
    elif flush:
        category, kickers = 5, [r for r in descending if flush & (1 << r)][:5]
    elif _straight(mask):
        category, kickers = 4, [_straight(mask)]
    elif groups[0][0] == 3:
        trip = groups[0][1]
        category, kickers = 3, [trip] + [r for r in descending if r != trip][:2]
    elif groups[0][0] == 2:
        pairs = sorted((r for n, r in groups if n == 2), reverse=True)
        if len(pairs) >= 2:
            category, kickers = 2, pairs[:2] + [r for r in descending if r not in pairs[:2]][:1]
        else:
            category, kickers = 1, pairs + [r for r in descending if r != pairs[0]][:3]
    else:
        category, kickers = 0, descending[:5]
    value = category << 24
    for i, rank in enumerate(kickers):
        value |= rank << (16 - 4 * i)
    return value


def rank_holdem(hole, board):
    if eval7 is not None:
        return eval7.evaluate([EVAL_CARDS[c] for c in (*hole, *board)])
    return rank_python(hole, board)


def hand_class(hole):
    """Canonical hold'em class, or suit-isomorphic key for other hole counts."""
    cards = sorted(hole, key=lambda c: RANKS.index(c[0]), reverse=True)
    if len(cards) == 2:
        a, b = cards
        return a[0] + b[0] + ("" if a[0] == b[0] else "s" if a[1] == b[1] else "o")
    return min("".join(sorted(c[0] + mapping[c[1]] for c in cards))
               for perm in itertools.permutations("abcd")
               for mapping in [dict(zip("cdhs", perm))])


def starting_classes(deck=DECK, hole_count=2, classify=hand_class):
    classes = {}
    for hole in itertools.combinations(deck, hole_count):
        classes.setdefault(classify(hole), hole)
    return classes


def class_weights(deck=DECK, hole_count=2, classify=hand_class):
    """Count concrete deals per class, including arbitrary hole-card counts."""
    return dict(Counter(classify(hole) for hole in itertools.combinations(deck, hole_count)))


def _sample_class(task):
    key, hole, deck, hole_count, ranking, samples, seed = task
    rng = random.Random(seed)
    available = [c for c in deck if c not in hole]
    result = {}
    # Reuse one seven-opponent deal for each requested field size. This gives
    # each size exactly `samples` unbiased deals while avoiding repeated work.
    totals = {n: 0.0 for n in (1, 2, 4, 7)}
    for _ in range(samples):
        draw = rng.sample(available, 5 + 7 * hole_count)
        board = draw[:5]
        hero = ranking(hole, board)
        best, ties = hero, 1
        for n in range(1, 8):
            start = 5 + (n - 1) * hole_count
            score = ranking(draw[start:start + hole_count], board)
            if score > best:
                best, ties = score, 1
            elif score == best:
                ties += 1
            if n in totals and best == hero:
                totals[n] += 1 / ties
    for n, total in totals.items():
        result[str(n)] = total / samples
    return key, result


def generate(deck=DECK, hole_count=2, ranking=rank_holdem, samples=20000,
             workers=None, seed=713, classify=hand_class):
    if samples < 1 or len(set(deck)) != len(deck):
        raise ValueError("Samples must be positive and deck cards unique")
    if len(deck) < 8 * hole_count + 5:
        raise ValueError("Deck cannot deal eight players plus five board cards")
    classes = starting_classes(deck, hole_count, classify)
    tasks = [(key, hole, tuple(deck), hole_count, ranking, samples, seed + i)
             for i, (key, hole) in enumerate(sorted(classes.items()))]
    if workers == 1:
        return dict(map(_sample_class, tasks))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return dict(pool.map(_sample_class, tasks))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--seed", type=int, default=713)
    parser.add_argument("--output", type=Path, default=Path("tables/equity_holdem.json"))
    parser.add_argument("--variant", help="Python module exporting DECK, HOLE_COUNT, rank; optional classify")
    args = parser.parse_args()
    variant = importlib.import_module(args.variant) if args.variant else None
    start = time.perf_counter()
    deck = variant.DECK if variant else DECK
    hole_count = variant.HOLE_COUNT if variant else 2
    classify = getattr(variant, "classify", hand_class)
    result = generate(deck, hole_count,
                      variant.rank if variant else rank_holdem,
                      args.samples, args.workers, args.seed,
                      classify)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Replace atomically: a bot importing bot/tables.py mid-write must never
    # see a truncated JSON file.
    tmp = args.output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(result, indent=2) + "\n")
    os.replace(tmp, args.output)
    elapsed = time.perf_counter() - start
    metadata = {"samples_per_class_per_opponent_count": args.samples,
                "seed": args.seed, "seconds": elapsed, "classes": len(result),
                "backend": "custom" if variant else "eval7" if eval7 else "python",
                "variant": args.variant or "holdem", "deck": list(deck),
                "hole_count": hole_count, "class_weights": class_weights(deck, hole_count, classify)}
    args.output.with_suffix(".meta.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({k: v for k, v in metadata.items() if k not in ("deck", "class_weights")}))


if __name__ == "__main__":
    main()
