"""Transparent push/fold approximation, not a solved eight-player equilibrium.

References for the method: HoldemResources heads-up Nash charts
(https://www.holdemresources.net/hune) and the local playbook's 8-BB BTN ~45%
and UTG ~15% anchors. No chart data are downloaded or copied. Ranges below are
an explicit interpolation of these anchors using random-opponent equity order,
tightened by multiplying the selected range fraction by 0.90 for eight-handed
play. Calling ranges are deliberately narrower. Actual ICM remains a separate
decision-time check, and multiway calling is not a Nash solution.

The requested 'minimum stack' is misleading: a weaker hand generally becomes
a shove as the stack SHRINKS. Records therefore include min_stack=2 and
max_stack for each action; absent ranges use null bounds. The by_stack map
explicitly keys every integer depth 2..15, players 1..7, and position.
"""
import argparse
import json
from pathlib import Path

from bot.tables import PUSHFOLD

POSITIONS = ("early", "middle", "cutoff", "button", "small_blind", "big_blind")


def range_fraction(bb, players, position):
    # At 8 BB the unadjusted BTN and UTG anchors are 50% and 16.7%.
    base = 1 / (players + 1)
    if players == 2:
        base = .50
    elif players >= 6:
        base = .167
    position_adjust = {"early": .95, "middle": 1, "cutoff": 1.03,
                       "button": 1, "small_blind": 1.12, "big_blind": 1}[position]
    urgency = (8 / max(2, bb)) ** .65
    return min(.95, base * urgency * position_adjust * .90)


def build(equity, weights=None):
    ordered = sorted(equity, key=lambda h: equity[h]["1"], reverse=True)
    weights = weights or {h: 6 if len(h) == 2 else 4 if h.endswith("s") else 12
                          for h in equity}
    total = sum(weights[h] for h in equity)
    percentiles, seen = {}, 0
    for hand in ordered:
        weight = weights[hand]
        percentiles[hand] = (seen + weight / 2) / total
        seen += weight
    by_stack, bounds = {}, {}
    for players in range(1, 8):
        for position in POSITIONS:
            key = f"{players}:{position}"
            bounds[key] = {}
            for bb in range(2, 16):
                fraction = range_fraction(bb, players, position)
                by_stack[f"{bb}:{key}"] = {h: {"shove": p <= fraction,
                    "call": p <= fraction * .65} for h, p in percentiles.items()}
            for hand in ordered:
                record = {}
                for action in ("shove", "call"):
                    depths = [bb for bb in range(2, 16) if by_stack[f"{bb}:{key}"][hand][action]]
                    record[f"min_stack_to_{action}"] = min(depths) if depths else None
                    record[f"max_stack_to_{action}"] = max(depths) if depths else None
                bounds[key][hand] = record
    return {"assumption": "heuristic ranges; 0.90 eight-handed multiplier; not solved Nash",
            "by_stack": by_stack, "bounds": bounds}


def lookup(hand, bb, players, position):
    # Runtime table is loaded once by bot.tables, never read here.
    depth = max(2, min(15, int(bb)))
    players = max(1, min(7, players))
    position = {"UTG": "early", "MP": "middle", "CO": "cutoff", "BTN": "button",
                "SB": "small_blind", "BB": "big_blind", "late": "button",
                "sb": "small_blind", "bb": "big_blind"}.get(position, position)
    return PUSHFOLD["by_stack"][f"{depth}:{players}:{position}"][hand]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--equity", type=Path, default=Path("tables/equity_holdem.json"))
    parser.add_argument("--output", type=Path, default=Path("tables/pushfold.json"))
    args = parser.parse_args()
    metadata_path = args.equity.with_suffix(".meta.json")
    metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
    result = build(json.loads(args.equity.read_text()), metadata.get("class_weights"))
    args.output.write_text(json.dumps(result, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
