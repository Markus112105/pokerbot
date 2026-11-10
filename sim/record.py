"""Record full hand histories for the replay viewer.

Runs tables through the normal engine with an observer attached and writes a
JSON replay: per table the seat names and payouts, then per hand the blinds,
button, private cards, every action with the resulting bets/stacks/pot, the
board per street, the settle snapshot, and final points.

Usage: python -m sim.record --tables 3 --lineup mixed --output results/replays/demo.json
"""
import argparse
import json
from pathlib import Path

from bot.agent import Agent
from sim.engine import DEFAULT_PAYOUTS, Engine
from sim.opponents import KINDS, Opponent


class Recorder:
    # groups raw observer events into one hands list per table so the viewer
    # can scrub hand by hand without reparsing a flat stream
    def __init__(self):
        self.hands = []

    def __call__(self, event):
        kind = event.pop("type")
        if kind == "hand":
            event["holes"] = {str(seat): hole for seat, hole in event["holes"].items()}
            self.hands.append(dict(event, acts=[], boards=[]))
        elif kind == "act":
            self.hands[-1]["acts"].append(event)
        elif kind == "board":
            self.hands[-1]["boards"].append(event)
        elif kind == "settle":
            self.hands[-1]["settle"] = event
        elif kind == "finish":
            self.finish = event


def record(tables=1, lineup="mixed", payouts=DEFAULT_PAYOUTS, seed=1):
    names = list(KINDS) + ["random"] if lineup == "mixed" else lineup.split(",")
    if len(names) == 1:
        names *= 7
    if len(names) != 7 or any(name not in KINDS for name in names):
        raise ValueError("lineup must be mixed, one opponent name, or seven comma-separated names")
    replays = []
    for table in range(tables):
        bots = [Agent()] + [Opponent(name, seed + table * 8 + i) for i, name in enumerate(names)]
        recorder = Recorder()
        result = Engine(bots, seed=seed + table, payouts=payouts, observer=recorder).play()
        replays.append({"table": table + 1, "names": result.names,
                        "payouts": list(payouts), "hands": recorder.hands,
                        "points": result.points, "final_stacks": result.stacks})
    return replays


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tables", type=int, default=1)
    parser.add_argument("--lineup", default="mixed")
    parser.add_argument("--payouts", default=",".join(map(str, DEFAULT_PAYOUTS)))
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("results/replays/demo.json"))
    args = parser.parse_args()
    replays = record(args.tables, args.lineup, tuple(map(float, args.payouts.split(","))), args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(replays) + "\n")
    hands = sum(len(r["hands"]) for r in replays)
    print(json.dumps({"tables": len(replays), "hands": hands, "output": str(args.output)}))


if __name__ == "__main__":
    main()
