"""Benchmark our bot inside the MIT Pokerbots 2026 engine.

Stages an arena from locally cloned MIT repos (kept out of this repo in
vendor/ because their license is unspecified), plays our adapter against the
published skeleton and the three 2026 reference bots, and reports bankrolls.

Setup (once):
    mkdir -p vendor && cd vendor
    git clone https://github.com/mitpokerbots/engine-2026
    git clone https://github.com/mitpokerbots/reference-1-2026
    git clone https://github.com/mitpokerbots/reference-2-2026
    git clone https://github.com/mitpokerbots/reference-3-2026
    uv pip install pkrbot --python ../.venv/bin/python

Run:
    python -m mit.benchmark --games 3
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
ARENA = VENDOR / "arena"
ENGINE = VENDOR / "engine-2026"
OPPONENTS = {
    "skeleton": ENGINE / "python_skeleton",
    "reference-1-toss-smallest": VENDOR / "reference-1-2026" / "python_toss_smallest",
    "reference-2-good-cards": VENDOR / "reference-2-2026" / "python_good_cards",
    "reference-3-monte-carlo": VENDOR / "reference-3-2026" / "python_monte_carlo",
}


def stage_bot(source, target, python):
    # copy a bot directory and point its run command at a python that has
    # pkrbot installed since reference 3 imports it inside the bot process
    shutil.copytree(source, target)
    commands = {"build": [], "run": [python, "player.py"]}
    (target / "commands.json").write_text(json.dumps(commands) + "\n")


def stage(python):
    if not ENGINE.exists():
        sys.exit("vendor/engine-2026 missing - see the setup commands in this file's docstring")
    shutil.rmtree(ARENA, ignore_errors=True)
    ARENA.mkdir(parents=True)
    shutil.copy(ENGINE / "engine.py", ARENA / "engine.py")
    ourbot = ARENA / "ourbot"
    stage_bot(ENGINE / "python_skeleton", ourbot, python)
    shutil.rmtree(ourbot / "__pycache__", ignore_errors=True)
    shutil.copy(ROOT / "mit" / "player.py", ourbot / "player.py")
    # the adapter needs the repo's lookup stack beside it: code plus tables
    shutil.copytree(ROOT / "bot", ourbot / "bot",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (ourbot / "tables").mkdir()
    for name in ("gen_equity.py", "pushfold.py", "equity_holdem.json", "equity_holdem.meta.json"):
        shutil.copy(ROOT / "tables" / name, ourbot / "tables" / name)
    for name, source in OPPONENTS.items():
        if source.exists():
            stage_bot(source, ARENA / name, python)
    return ourbot


def run_match(opponent, rounds, python, log_name):
    config = f'''PLAYER_1_NAME = "HERO"
PLAYER_1_PATH = "./ourbot"
PLAYER_2_NAME = "VILLAIN"
PLAYER_2_PATH = "./{opponent}"
GAME_LOG_FILENAME = "{log_name}"
PLAYER_LOG_SIZE_LIMIT = 524288
ENFORCE_GAME_CLOCK = True
STARTING_GAME_CLOCK = 60.0
BUILD_TIMEOUT = 10.0
CONNECT_TIMEOUT = 10.0
NUM_ROUNDS = {rounds}
STARTING_STACK = 400
BIG_BLIND = 2
SMALL_BLIND = 1
PLAYER_TIMEOUT = 120
'''
    (ARENA / "config.py").write_text(config)
    subprocess.run([python, "engine.py"], cwd=ARENA, check=True,
                   stdout=subprocess.DEVNULL, timeout=1800)
    text = (ARENA / f"{log_name}.txt").read_text()
    final = re.search(r"Final.*?HERO \((-?\d+)\)", text)
    if not final:
        raise RuntimeError(f"no final score in {log_name}.txt")
    return int(final.group(1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=3, help="matches per opponent")
    parser.add_argument("--rounds", type=int, default=1000)
    parser.add_argument("--opponents", default=",".join(OPPONENTS))
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "mit_benchmark.json")
    args = parser.parse_args()
    python = str(ROOT / ".venv" / "bin" / "python")
    stage(python)
    report = {"rounds_per_game": args.rounds, "games_per_opponent": args.games,
              "engine": "mitpokerbots/engine-2026", "opponents": {}}
    for name in args.opponents.split(","):
        if not (ARENA / name).exists():
            print(json.dumps({"opponent": name, "skipped": "not cloned"}))
            continue
        deltas = []
        for game in range(args.games):
            delta = run_match(name, args.rounds, python, f"log_{name}_{game}")
            deltas.append(delta)
            print(json.dumps({"opponent": name, "game": game + 1, "hero_delta": delta}))
        report["opponents"][name] = {
            "hero_deltas": deltas,
            "wins": sum(d > 0 for d in deltas),
            "mean_bb_per_hand": round(sum(deltas) / len(deltas) / args.rounds / 2, 4)}
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: data["mean_bb_per_hand"]
                      for name, data in report["opponents"].items()}))


if __name__ == "__main__":
    main()
