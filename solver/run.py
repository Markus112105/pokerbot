"""Train CFR+ on a bundled game and report convergence to Nash equilibrium.

Example:
    python -m solver.run --game kuhn --iterations 20000
    python -m solver.run --game leduc --iterations 2000 --report-every 200

Reported per checkpoint: expected game value for player 0 under the average
strategy profile, and exploitability (NashConv/2, chips per hand; zero at
equilibrium). Kuhn's exact Nash value, -1/18 = -0.0556, is the oracle that
the implementation is correct; Leduc's value is reported as measured.
"""
import argparse
import json
import time
from pathlib import Path

from solver.cfr import CFRTrainer, expected_value
from solver.exploitability import exploitability
from solver.games import GAMES


def train(game_name, iterations, report_every, plus=True):
    game = GAMES[game_name]()
    trainer = CFRTrainer(game, plus=plus)
    start = time.perf_counter()
    checkpoints = []
    done = 0
    while done < iterations:
        step = min(report_every, iterations - done)
        trainer.run(step)
        done += step
        profile = trainer.average_strategy()
        checkpoints.append({
            "iteration": done,
            "value_player0": expected_value(game, profile),
            "exploitability": exploitability(game, profile),
            "seconds": round(time.perf_counter() - start, 3),
        })
        print(json.dumps(checkpoints[-1]))
    return {
        "game": game_name,
        "algorithm": "CFR+ (regret matching+, linear averaging)" if plus else "vanilla CFR",
        "iterations": iterations,
        "infosets": len(trainer.regrets),
        "checkpoints": checkpoints,
        "final": checkpoints[-1],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", choices=sorted(GAMES), default="kuhn")
    parser.add_argument("--iterations", type=int, default=10000)
    parser.add_argument("--report-every", type=int, default=1000)
    parser.add_argument("--vanilla", action="store_true", help="plain CFR instead of CFR+")
    parser.add_argument("--output", type=Path, help="write the full report as JSON")
    args = parser.parse_args()
    report = train(args.game, args.iterations, args.report_every, plus=not args.vanilla)
    print(json.dumps({k: report[k] for k in ("game", "algorithm", "infosets", "final")}, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
