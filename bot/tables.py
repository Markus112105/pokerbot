"""Variant seam: all disk reads and precomputed range ordering happen at import."""
import json
from pathlib import Path

from tables.gen_equity import DECK, hand_class, rank_holdem

ROOT = Path(__file__).resolve().parent.parent / "tables"
# Variants can supply a callable(hole, board) returning the Features contract.
# Keeping this hook here avoids editing the core feature or decision modules.
FEATURE_EXTRACTOR = None
EQUITY = json.loads((ROOT / "equity_holdem.json").read_text())
METADATA_PATH = ROOT / "equity_holdem.meta.json"
METADATA = json.loads(METADATA_PATH.read_text()) if METADATA_PATH.exists() else {}
CLASS_WEIGHTS = METADATA.get("class_weights") or {
    h: 6 if len(h) == 2 else 4 if h.endswith("s") else 12 for h in EQUITY}


def _percentiles(opponents):
    # Metadata counts concrete deals, so short decks and extra hole cards retain
    # their actual probability mass rather than assuming 1,326 hold'em deals.
    result, seen = {}, 0
    total = sum(CLASS_WEIGHTS[h] for h in EQUITY)
    for hand in sorted(EQUITY, key=lambda h: EQUITY[h][str(opponents)], reverse=True):
        weight = CLASS_WEIGHTS[hand]
        result[hand] = (seen + weight / 2) / total
        seen += weight
    return result


PERCENTILES = {n: _percentiles(n) for n in (1, 2, 4, 7)}
PUSHFOLD = json.loads((ROOT / "pushfold.json").read_text()) if (ROOT / "pushfold.json").exists() else {}


def opponent_bucket(opponents):
    return min((1, 2, 4, 7), key=lambda n: abs(n - opponents))
