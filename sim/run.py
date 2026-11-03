"""Run independent offline tables and report observed points and wall timings."""
import argparse
from array import array
from collections import defaultdict
import gc
import json
import math
from pathlib import Path

from bot.agent import Agent
from sim.engine import DEFAULT_PAYOUTS, Engine
from sim.opponents import KINDS, Opponent


def percentile(values, fraction=.99):
    """Nearest-rank percentile; measured wall time includes scheduling pauses."""
    return sorted(values)[max(0, math.ceil(len(values)*fraction)-1)] if values else 0


def run(tables=1000, lineup="mixed", payouts=DEFAULT_PAYOUTS, seed=1):
    if tables < 1:
        raise ValueError("tables must be positive")
    names = list(KINDS) + ["random"] if lineup == "mixed" else lineup.split(",")
    if len(names) == 1:
        names *= 7
    if len(names) != 7 or any(name not in KINDS for name in names):
        raise ValueError("lineup must be mixed, one opponent name, or seven comma-separated names")
    sums, counts = defaultdict(float), defaultdict(int)
    timeouts_by_name, errors_by_name = defaultdict(int), defaultdict(int)
    histogram = [0.0] * 8
    bust_buckets, survived = [0] * 8, 0
    errors = timeouts = stalls = capped = 0
    # Packed integers avoid making cyclic GC traverse hundreds of thousands
    # of historical timing objects during an unrelated bot decision.
    timings, hero_timings, hero_scores = array("Q"), array("Q"), []
    timeout_details, stall_details = [], []
    # Automatic collection is deferred to the gap between tables so a gen-2
    # GC pause over the shared process heap is never charged to a timed call.
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for table in range(tables):
            bots = [Agent()] + [Opponent(name, seed + table*8 + i) for i, name in enumerate(names)]
            result = Engine(bots, seed=seed+table, payouts=payouts).play()
            hero = result.names.index("hero")
            hero_scores.append(result.points[hero])
            bust = result.bust_hands[hero]
            if bust is None:
                survived += 1
            else:
                bust_buckets[min((bust - 1) // 25, 7)] += 1
            for name, points in zip(result.names, result.points):
                sums[name] += points
                counts[name] += 1
            histogram = [a+b for a, b in zip(histogram, result.positions[hero])]
            errors += result.errors
            timeouts += result.timeouts
            stalls += result.stalls
            capped += result.capped
            for name, count in result.timeouts_by_name.items():
                timeouts_by_name[name] += count
            for name, count in result.errors_by_name.items():
                errors_by_name[name] += count
            timeout_details.extend(dict(table=table+1, **detail) for detail in
                                   result.timeout_details[:max(0, 10-len(timeout_details))])
            stall_details.extend(dict(table=table+1, **detail) for detail in
                                 result.stall_details[:max(0, 10-len(stall_details))])
            timings.extend(result.timings_ns)
            hero_timings.extend(t for t, seat in zip(result.timings_ns, result.timing_seats) if seat == hero)
            gc.collect()
    finally:
        if gc_was_enabled:
            gc.enable()
    mean = sums["hero"] / tables
    stderr = (sum((v-mean)**2 for v in hero_scores)/(tables-1)/tables)**.5 if tables > 1 else 0
    return dict(tables=tables, seed=seed, lineup=names, payouts=list(payouts),
                average_points={name: round(sums[name]/counts[name], 6) for name in sums},
                hero_standard_error=round(stderr, 6),
                finishing_position_histogram={str(i+1): round(v, 6) for i, v in enumerate(histogram)},
                histogram_note="Tied finishes split counts; cap survivors use ICM rank probabilities.",
                hero_bust_by_blind_level={**{f"{25*i+1}-{25*(i+1)}": bust_buckets[i] for i in range(8)},
                                          "survived_or_won": survived},
                errors=errors, timeouts=timeouts, stalls=stalls, capped_tables=capped,
                hero_errors=errors_by_name.get("hero", 0),
                hero_timeouts=timeouts_by_name.get("hero", 0),
                timeouts_by_name=dict(timeouts_by_name), errors_by_name=dict(errors_by_name),
                timeout_details=timeout_details, stall_details=stall_details,
                p99_decision_ms=percentile(timings)/1e6,
                hero_p99_decision_ms=percentile(hero_timings)/1e6,
                max_decision_ms=max(timings, default=0)/1e6,
                decisions=len(timings))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=int, default=1000)
    parser.add_argument("--lineup", default="mixed", help="mixed, one baseline, or seven comma-separated baselines")
    parser.add_argument("--payouts", default=",".join(map(str, DEFAULT_PAYOUTS)))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", help="Optional local JSON report path")
    args = parser.parse_args()
    try:
        report = run(args.tables, args.lineup, tuple(map(float, args.payouts.split(","))), args.seed)
    except ValueError as error:
        parser.error(str(error))
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as output:
            output.write(text + "\n")


if __name__ == "__main__":
    main()
