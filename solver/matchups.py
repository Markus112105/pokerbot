"""Heads-up class-vs-class equity matrix with exact card-removal weights.

For each ordered pair of the 169 starting-hand classes this produces:
  weights[i][j]: the exact number of disjoint ordered combo pairs (a in i,
                 b in j) -- the correct deal distribution with card removal;
  equity[i][j]:  Monte Carlo estimate of class i's showdown equity against
                 class j (ties count half), sampled uniformly over disjoint
                 combo pairs and random 5-card boards, so suit-overlap
                 effects (e.g. AKs vs QQ sharing a suit) are represented.

Only the upper triangle is sampled; equity[j][i] = 1 - equity[i][j] exactly.
Standard error per entry is 0.5/sqrt(samples) (~0.8% at the 4,000 default).

Usage: python -m solver.matchups --samples 4000 --workers 6
Writes tables/matchups.json (~1 MB), consumed by solver.pushfold_exploit.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from itertools import combinations
import json
import os
from pathlib import Path
from random import Random
import time

from tables.gen_equity import DECK, hand_class, rank_holdem

COMBOS = [frozenset(c) for c in combinations(DECK, 2)]
CLASSES = sorted({hand_class(tuple(c)) for c in COMBOS})
INDEX = {name: i for i, name in enumerate(CLASSES)}
BY_CLASS = [[] for _ in CLASSES]
for combo in COMBOS:
    BY_CLASS[INDEX[hand_class(tuple(combo))]].append(tuple(sorted(combo)))


def weights():
    """Exact disjoint ordered-pair counts for every class pair."""
    counts = [[0] * len(CLASSES) for _ in CLASSES]
    for i, mine in enumerate(BY_CLASS):
        for j, theirs in enumerate(BY_CLASS):
            counts[i][j] = sum(1 for a in mine for b in theirs
                               if not set(a) & set(b))
    return counts


def _sample_pairs(job):
    pairs, samples, seed = job
    rng = Random(seed)
    results = []
    for i, j in pairs:
        total = 0.0
        done = 0
        while done < samples:
            a = rng.choice(BY_CLASS[i])
            b = rng.choice(BY_CLASS[j])
            used = set(a) | set(b)
            if len(used) < 4:
                continue
            board = rng.sample([c for c in DECK if c not in used], 5)
            ra, rb = rank_holdem(a, board), rank_holdem(b, board)
            total += 1.0 if ra > rb else 0.5 if ra == rb else 0.0
            done += 1
        results.append((i, j, total / samples))
    return results


def generate(samples=4000, workers=None, seed=4621):
    workers = workers or min(8, os.cpu_count() or 1)
    n = len(CLASSES)
    pairs = [(i, j) for i in range(n) for j in range(i, n)]
    chunks = [(pairs[k::workers], samples, seed + k) for k in range(workers)]
    equity = [[0.0] * n for _ in range(n)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for results in pool.map(_sample_pairs, chunks):
            for i, j, value in results:
                equity[i][j] = value
                equity[j][i] = 1.0 - value
    return equity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=4000)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--seed", type=int, default=4621)
    parser.add_argument("--output", type=Path, default=Path("tables/matchups.json"))
    args = parser.parse_args()
    start = time.perf_counter()
    payload = {"classes": CLASSES, "equity": generate(args.samples, args.workers, args.seed),
               "weights": weights(),
               "meta": {"samples_per_pair": args.samples, "seed": args.seed,
                        "seconds": round(time.perf_counter() - start, 1),
                        "note": "equity[i][j] = P(class i beats j) + P(tie)/2, "
                                "card-removal sampled; weights are exact combo counts"}}
    tmp = args.output.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload) + "\n")
    os.replace(tmp, args.output)
    print(json.dumps(payload["meta"]))


if __name__ == "__main__":
    main()
