"""Run 10,000 postflop evaluations; enforce p99 < 0.3 ms on this machine."""
import json
import random
import time

from bot.strength import evaluate
from tables.gen_equity import DECK, eval7


def main():
    rng = random.Random(191)
    hands = [rng.sample(DECK, rng.choice((5, 6, 7))) for _ in range(10000)]
    timings = []
    for cards in hands:
        start = time.perf_counter_ns()
        evaluate(cards[:2], cards[2:])
        timings.append(time.perf_counter_ns() - start)
    p99 = sorted(timings)[9899] / 1e6
    print(json.dumps({"evaluations": len(timings), "p99_ms": p99,
                      "max_ms": max(timings) / 1e6, "backend": "eval7" if eval7 else "python"}))
    assert p99 < .3, f"Postflop p99 {p99:.4f} ms exceeds budget"


if __name__ == "__main__":
    main()
