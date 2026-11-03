"""Fast preflop lookups and deterministic postflop made-hand/draw features."""
from dataclasses import dataclass

from bot.tables import EQUITY, PERCENTILES, hand_class, opponent_bucket, rank_holdem
from bot.tables import FEATURE_EXTRACTOR
from tables.gen_equity import CARD_INFO, _straight


@dataclass(frozen=True, slots=True)
class Features:
    category: int
    flush_draw: bool
    open_ended: bool
    gutshot: bool
    board_paired: bool
    board_monotone: bool
    overcards: int
    top_pair: bool
    strength: int
    board_only: bool


def preflop(hole, opponents=1):
    return EQUITY[hand_class(hole)][str(opponent_bucket(opponents))]


def percentile(hole, opponents=1):
    return PERCENTILES[opponent_bucket(opponents)][hand_class(hole)]


def evaluate(hole, board):
    """Draws require a hole-card contribution and an uncompleted board.

    Open-ended means four consecutive ranks with two distinct completing ends;
    double-gutshots are represented as gutshots. Board-only draws are excluded.
    Top pair includes an overpair but never a pair solely on the board.
    """
    if FEATURE_EXTRACTOR is not None:
        return FEATURE_EXTRACTOR(hole, board)
    if not 3 <= len(board) <= 5:
        raise ValueError("Postflop board must contain three to five cards")
    hr = [CARD_INFO[c][0] for c in hole]
    br = [CARD_INFO[c][0] for c in board]
    all_cards = (*hole, *board)
    ranks = set(hr + br)
    board_ranks = set(br)
    if 14 in ranks:
        ranks.add(1)
    if 14 in board_ranks:
        board_ranks.add(1)
    suits = [c[1] for c in all_cards]
    draws = len(board) < 5
    flush_draw = draws and any(suits.count(s) == 4 and any(c[1] == s for c in hole)
                              for s in "cdhs")
    mask = sum(1 << r for r in ranks)
    open_ended = gutshot = False
    if draws and not _straight(mask):
        for low in range(2, 11):
            window = set(range(low, low + 4))
            if window <= ranks and not window <= board_ranks:
                open_ended = True
        if not open_ended:
            for low in range(1, 11):
                window = set(range(low, low + 5))
                present = window & ranks
                if len(present) == 4 and not present <= board_ranks:
                    gutshot = True
                    break
    strength = rank_holdem(hole, board)
    top = max(br)
    top_pair = top in hr or (len(hr) == 2 and hr[0] == hr[1] and hr[0] > top)
    board_only = len(board) == 5 and strength == rank_holdem((), board)
    if len(board) < 5 and strength >> 24 in (1, 2, 3):
        # A paired/tripped board alone is not a value hand just because the
        # absolute made-hand category is high. Distinct hole ranks must improve it.
        board_only = not any(r in br for r in hr) and len(set(hr)) == len(hr)
    return Features(strength >> 24, flush_draw, open_ended, gutshot,
                    len(set(br)) < len(br), len({c[1] for c in board}) == 1,
                    sum(r > top for r in hr), top_pair, strength, board_only)
