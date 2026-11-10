"""Our bot adapted to the MIT Pokerbots 2026 engine (3 hole cards, discard
one onto the board after a two-card flop, heads-up cash over 1000 rounds).

Reuses this repo's precomputed equity table and hand evaluator; the ICM and
tournament layers stay home because bankroll poker is chip-EV poker. Staged
next to a copy of bot/ and tables/ by mit/benchmark.py.
"""
from skeleton.actions import FoldAction, CallAction, CheckAction, RaiseAction, DiscardAction
from skeleton.bot import Bot
from skeleton.runner import parse_args, run_bot

from bot.tables import PERCENTILES, hand_class
from tables.gen_equity import CARD_INFO, rank_holdem

BIG_BLIND = 2


def pct(two_cards):
    # lower is better -- fraction of starting classes with more equity vs one
    # random hand which is the right baseline for a heads-up variant
    return PERCENTILES[1][hand_class(tuple(two_cards))]


def best_two(cards):
    # the hand that actually reaches showdown is the best pair of the three
    # hole cards so all preflop strength runs through this projection
    options = [(cards[0], cards[1]), (cards[0], cards[2]), (cards[1], cards[2])]
    best = min(options, key=pct)
    return best, pct(best)


def discard_index(cards, board):
    # score each keep-two option by class strength plus board synergy since
    # the discard lands face up on the board for both players to use
    board_ranks = {CARD_INFO[c][0] for c in board}
    board_suits = [CARD_INFO[c][1] for c in board]
    best_index, best_score = 0, -9.9
    for toss in range(3):
        kept = [cards[i] for i in range(3) if i != toss]
        score = -pct(kept)
        if any(CARD_INFO[c][0] in board_ranks for c in kept):
            score += 0.12
        suits = [CARD_INFO[c][1] for c in kept]
        if suits[0] == suits[1]:
            score += 0.05 * min(3, board_suits.count(suits[0]))
        if best_score < score:
            best_index, best_score = toss, score
    return best_index


def postflop_win(kept, board, opponent_aggressive):
    # category from the shared evaluator -- conservative because an 8 card
    # showdown makes big board-made hands common for both players
    category = rank_holdem(tuple(kept), tuple(board)) >> 24
    board_category = rank_holdem((), tuple(board)) >> 24 if len(board) >= 5 else -1
    hole_ranks = [CARD_INFO[c][0] for c in kept]
    board_ranks = [CARD_INFO[c][0] for c in board]
    paired = any(r in board_ranks for r in hole_ranks)
    overpair = hole_ranks[0] == hole_ranks[1] and hole_ranks[0] > max(board_ranks)
    if category <= board_category:
        return 0.28  # the board plays and anyone holds at least this
    if category >= 5:
        return 0.90
    if category >= 3:
        return 0.80
    if category == 2 or overpair:
        return 0.70
    if category == 1 and paired:
        return 0.58 if max(board_ranks) in hole_ranks else 0.46
    return 0.30 if opponent_aggressive else 0.24


class Player(Bot):
    def __init__(self):
        self.opp_bets = 0
        self.opp_chances = 0

    def handle_new_round(self, game_state, round_state, active):
        pass

    def handle_round_over(self, game_state, terminal_state, active):
        pass

    def get_action(self, game_state, round_state, active):
        try:
            return self.decide(round_state, active)
        except Exception:
            legal = round_state.legal_actions()
            if DiscardAction in legal:
                return DiscardAction(0)
            return CheckAction() if CheckAction in legal else FoldAction()

    def decide(self, round_state, active):
        legal = round_state.legal_actions()
        cards = [str(c) for c in round_state.hands[active]]
        board = [str(c) for c in round_state.board]
        if DiscardAction in legal:
            return DiscardAction(discard_index(cards, board))
        if len(legal) == 1:
            return CheckAction()
        my_pip = round_state.pips[active]
        opp_pip = round_state.pips[1 - active]
        cost = opp_pip - my_pip
        pot = sum(round_state.pips) + (800 - sum(round_state.stacks) - sum(round_state.pips))
        if cost > 0:
            self.opp_bets += 1
        self.opp_chances += 1
        # a crude aggression read widens calls against bots that bet anything
        aggressive = self.opp_chances >= 30 and self.opp_bets / self.opp_chances > 0.45
        if round_state.street == 0:
            return self.preflop(round_state, legal, cards, my_pip, opp_pip, cost, aggressive)
        kept = cards if len(cards) == 2 else list(best_two(cards)[0])
        win = postflop_win(kept, board, aggressive)
        return self.bet_or_call(round_state, legal, win, pot, cost, my_pip)

    def preflop(self, round_state, legal, cards, my_pip, opp_pip, cost, aggressive):
        _, strength = best_two(cards)
        raises_so_far = max(my_pip, opp_pip) // (3 * BIG_BLIND)
        if cost == 0:
            # bb versus a limp or opening the betting after a call
            if strength <= 0.30 and RaiseAction in legal:
                low, high = round_state.raise_bounds()
                return RaiseAction(min(high, max(low, 4 * BIG_BLIND)))
            return CheckAction()
        pot_odds = cost / (sum(round_state.pips) + cost)
        if strength <= (0.04 if raises_so_far >= 2 else 0.10) and RaiseAction in legal:
            low, high = round_state.raise_bounds()
            return RaiseAction(min(high, max(low, 3 * (my_pip + cost))))
        if cost <= BIG_BLIND and strength <= 0.72 and RaiseAction in legal:
            # open the button with a raise instead of limping
            low, high = round_state.raise_bounds()
            return RaiseAction(min(high, max(low, 3 * BIG_BLIND)))
        call_cut = 0.55 if cost <= 3 * BIG_BLIND else 0.30 if cost <= 10 * BIG_BLIND else 0.12
        if aggressive:
            call_cut += 0.08
        if strength <= call_cut and (1 - strength) > pot_odds:
            return CallAction() if CallAction in legal else CheckAction()
        return FoldAction() if cost > 0 else CheckAction()

    def bet_or_call(self, round_state, legal, win, pot, cost, my_pip):
        if cost == 0:
            if win >= 0.58 and RaiseAction in legal:
                low, high = round_state.raise_bounds()
                return RaiseAction(min(high, max(low, my_pip + int(0.6 * max(pot, BIG_BLIND)))))
            return CheckAction()
        pot_odds = cost / (pot + cost)
        if win >= 0.85 and RaiseAction in legal:
            low, high = round_state.raise_bounds()
            return RaiseAction(min(high, max(low, my_pip + cost + pot)))
        if win > pot_odds + 0.06:
            return CallAction()
        return FoldAction()


if __name__ == "__main__":
    run_bot(Player(), parse_args())
