"""Kuhn poker and Leduc hold'em as exact game trees for CFR and best response.

Chance is pre-dealt: a "deal" fixes all private cards (and Leduc's board), so
the traversal never meets a chance node; the board simply becomes visible to
infosets after round one. Player and legal actions depend only on the public
history, which the best-response recursion relies on.

Conventions: player 0 acts first in every round. Actions are 'c' (check or
call), 'r' (bet or raise), 'f' (fold). Utilities are chips won by player 0.

Kuhn: 3 cards, ante 1, one bet of 1, no raises. Nash value for player 0 is
exactly -1/18 (Kuhn 1950), used as the engine's correctness oracle.

Leduc (standard research spec): 6 cards (J,J,Q,Q,K,K), ante 1, one private
card each, one board card after round one. Bet size 2 in round one, 4 in
round two, at most two raises per round. Pairing the board beats high card.
"""
from itertools import permutations

RANKS = "JQK"


class Kuhn:
    TERMINAL = {"cc", "crc", "crf", "rc", "rf"}

    def deals(self):
        return [((a, b), 1.0 / 6) for a, b in permutations(range(3), 2)]

    def player(self, deal, history):
        return None if history in self.TERMINAL else len(history) % 2

    def actions(self, deal, history):
        return ("c", "f") if history.endswith("r") else ("c", "r")

    def infoset(self, deal, history):
        return RANKS[deal[len(history) % 2]] + ":" + history

    def utility(self, deal, history):
        if history == "crf":
            return -1.0  # player 0 folded after betting round check-raise
        if history == "rf":
            return 1.0   # player 1 folded to player 0's bet
        stake = 1.0 if history == "cc" else 2.0
        return stake if deal[0] > deal[1] else -stake


class Leduc:
    DECK = (0, 0, 1, 1, 2, 2)
    BETS = (2.0, 4.0)
    MAX_RAISES = 2

    def deals(self):
        # aggregate duplicate rank triples since the deck holds two of each
        # rank -- consumers treat deals as dict keys so each must appear once
        # or belief weights silently collapse
        counts = {}
        for a, b, c in permutations(range(6), 3):
            deal = (self.DECK[a], self.DECK[b], self.DECK[c])
            counts[deal] = counts.get(deal, 0) + 1
        total = sum(counts.values())
        return [(deal, count / total) for deal, count in sorted(counts.items())]

    def _state(self, history):
        """Return (round, to_act, contributions, raises, pending, folder)."""
        contributions = [1.0, 1.0]
        game_round, to_act, raises, pending = 0, 0, 0, False
        for action in history:
            if action == "/":
                game_round, to_act, raises, pending = 1, 0, 0, False
                continue
            if action == "f":
                return game_round, to_act, contributions, raises, pending, to_act
            if action == "r":
                owed = max(contributions) - contributions[to_act]
                contributions[to_act] += owed + self.BETS[game_round]
                raises += 1
                pending = True
            else:  # check or call
                contributions[to_act] += max(contributions) - contributions[to_act]
            to_act ^= 1
        return game_round, to_act, contributions, raises, pending, None

    def _round_over(self, history):
        tail = history.rsplit("/", 1)[-1]
        return tail in ("cc",) or (len(tail) >= 2 and tail.endswith("c") and "r" in tail)

    def player(self, deal, history):
        if history.endswith("f"):
            return None
        if self._round_over(history):
            if history.count("/"):
                return None  # round-two betting closed: showdown
            return 0  # caller advances the round via the '/' marker in actions
        return self._state(history)[1]

    def actions(self, deal, history):
        if self._round_over(history) and not history.count("/"):
            return ("/",)  # deterministic round transition, probability one
        _, _, _, raises, pending, _ = self._state(history)
        if pending:
            return ("c", "f", "r") if raises < self.MAX_RAISES else ("c", "f")
        return ("c", "r")

    def infoset(self, deal, history):
        board = RANKS[deal[2]] if history.count("/") else "?"
        # the round-transition pseudo-node belongs to player 0 per player()
        # so it must be keyed by player 0s card -- keying by the natural
        # next-to-act after odd closing sequences like crc would build the
        # key from player 1s card and let a best response split beliefs on
        # the opponents hidden hand which no legal strategy can do
        if self._round_over(history) and not history.count("/"):
            seat = 0
        else:
            seat = self._state(history)[1]
        return RANKS[deal[seat]] + board + ":" + history

    def utility(self, deal, history):
        _, _, contributions, _, _, folder = self._state(history)
        if folder is not None:
            lost = contributions[folder]
            return lost if folder == 1 else -lost
        mine, theirs, board = deal
        rank0 = 3 + mine if mine == board else mine
        rank1 = 3 + theirs if theirs == board else theirs
        if rank0 == rank1:
            return 0.0
        return contributions[1] if rank0 > rank1 else -contributions[0]


GAMES = {"kuhn": Kuhn, "leduc": Leduc}
