"""Small no-limit hold'em SNG engine with real betting rounds and side pots.

Raises are total street contributions. Blinds double every 25 hands by
default; the precise schedule, simultaneous-bust tie rule and odd-chip rule
are local assumptions to verify against the competition starter kit.
"""
from dataclasses import dataclass
from random import Random
from time import perf_counter_ns, thread_time_ns

from bot.icm import equity
from tables.gen_equity import DECK, rank_holdem

DEFAULT_PAYOUTS = (10, 7, 5, 3, 2, 1, 0, 0)
DEFAULT_BLINDS = tuple((10 * 2**i, 20 * 2**i) for i in range(8))


def settle_pots(contributions, contenders, ranks, button=0):
    """Split contribution layers, including folded money and uncalled refunds.

    Integer remainders go clockwise left of the button among tied winners.
    Each layer has its own eligible showdown players, so a short stack can
    win the main pot without winning money it never matched.
    """
    awards = [0] * len(contributions)
    previous = 0
    for level in sorted(set(contributions) - {0}):
        donors = [i for i, amount in enumerate(contributions) if amount >= level]
        amount = (level - previous) * len(donors)
        eligible = [i for i in donors if i in contenders]
        if len(donors) == 1:
            winners = donors  # Return an unmatched bet, even after a fold.
        else:
            if not eligible:
                raise ValueError("pot layer has no eligible player")
            best = max(ranks[i] for i in eligible)
            winners = [i for i in eligible if ranks[i] == best]
        winners.sort(key=lambda i: (i - button - 1) % len(contributions))
        share, remainder = divmod(amount, len(winners))
        for offset, seat in enumerate(winners):
            awards[seat] += share + (offset < remainder)
        previous = level
    return awards


@dataclass
class Result:
    names: list
    points: list
    positions: list
    stacks: list
    hands: int
    errors: int
    timeouts: int
    timings_ns: list
    timing_seats: list
    capped: bool
    timeout_details: list
    stalls: int
    stall_details: list
    timeouts_by_name: dict
    errors_by_name: dict
    bust_hands: list


class Engine:
    """One independent table; public states contain only the acting hole cards."""

    def __init__(self, bots, seed=1, payouts=DEFAULT_PAYOUTS, cap=200,
                 blinds=DEFAULT_BLINDS, chips=2000, shuffle=True):
        if not 2 <= len(bots) <= 8 or len(payouts) != len(bots):
            raise ValueError("need 2-8 bots and one payout per finishing place")
        if cap < 1 or chips < 1 or not blinds or any(a < 1 or b < a for a, b in blinds):
            raise ValueError("invalid tournament configuration")
        if any(p < 0 for p in payouts) or any(a < b for a, b in zip(payouts, payouts[1:])):
            raise ValueError("payouts must be nonnegative and descending")
        self.rng = Random(seed)
        self.bots = list(bots)
        if shuffle:
            self.rng.shuffle(self.bots)
        self.n = len(bots)
        self.stacks = [chips] * self.n
        self.total_chips = chips * self.n
        self.payouts, self.cap, self.blinds = tuple(payouts), cap, tuple(blinds)
        self.points = [0.0] * self.n
        self.positions = [[0.0] * self.n for _ in bots]
        self.errors = self.timeouts = self.stalls = 0
        self.timeout_details, self.stall_details = [], []
        self.timeouts_by_name, self.errors_by_name = {}, {}
        self.bust_hands = [None] * self.n
        self.timings, self.timing_seats = [], []
        self.button = self.rng.randrange(self.n)
        for bot in self.bots:
            bot.reset()

    def _next(self, seat, eligible):
        return next((seat + d) % self.n for d in range(1, self.n + 1)
                    if (seat + d) % self.n in eligible)

    def _emit(self, event):
        for bot in self.bots:
            bot.observe(event)

    def _pay(self, seat, amount, bets, contributions):
        amount = min(amount, self.stacks[seat])
        self.stacks[seat] -= amount
        bets[seat] += amount
        contributions[seat] += amount

    def _decision(self, seat, state):
        bot = self.bots[seat]
        before = getattr(bot, "errors", 0)
        start = perf_counter_ns()
        cpu_start = thread_time_ns()
        try:
            action = bot.act(state)
            if action["type"] not in state["legal_actions"]:
                raise ValueError("illegal action type")
            if action["type"] == "raise":
                amount = action["amount"]
                if (not isinstance(amount, int) or amount > state["max_raise"] or
                    amount < min(state["min_raise"], state["max_raise"])):
                    raise ValueError("illegal raise size")
        except Exception:
            self.errors += 1
            self.errors_by_name[bot.name] = self.errors_by_name.get(bot.name, 0) + 1
            action = {"type": "check" if state["to_call"] == 0 else "fold"}
        elapsed = perf_counter_ns() - start
        cpu_elapsed = thread_time_ns() - cpu_start
        internal = max(0, getattr(bot, "errors", 0) - before)
        self.errors += internal
        if internal:
            self.errors_by_name[bot.name] = self.errors_by_name.get(bot.name, 0) + internal
        self.timings.append(elapsed)
        self.timing_seats.append(seat)
        if elapsed > 1_000_000:
            # The cutoff is enforced on wall time, as the kit would. A call
            # whose thread-CPU time stayed under budget was descheduled by the
            # host, so it is a stall charged to the machine, not a bot timeout.
            detail = dict(bot=bot.name, hand=state.get("hand_number"),
                          street=state.get("street"), wall_ms=elapsed/1e6,
                          cpu_ms=cpu_elapsed/1e6)
            if cpu_elapsed > 1_000_000:
                self.timeouts += 1
                self.timeouts_by_name[bot.name] = self.timeouts_by_name.get(bot.name, 0) + 1
                if len(self.timeout_details) < 10:
                    self.timeout_details.append(detail)
            else:
                self.stalls += 1
                if len(self.stall_details) < 10:
                    self.stall_details.append(detail)
            action = {"type": "check" if state["to_call"] == 0 else "fold"}
        return action

    def _round(self, first, board, holes, alive, contenders, bets, contributions,
               bb, sb, hand, street):
        current = max(max(bets), bb if street == "preflop" else 0)
        increment, acted_at, aggressor, bet_fraction = bb, {}, None, 0.0
        pending = {i for i in contenders if self.stacks[i]}
        seat = first
        while pending and len(contenders) > 1:
            actionable = {i for i in contenders if self.stacks[i]}
            if len(actionable) <= 1 and all(bets[i] >= current for i in actionable):
                break
            if seat not in pending:
                seat = self._next(seat, pending)
            call = min(self.stacks[seat], max(0, current - bets[seat]))
            legal = ["fold", "call"] if call else ["check", "fold"]
            reopened = seat not in acted_at or current - acted_at[seat] >= increment
            if reopened and len(actionable) > 1 and bets[seat] + self.stacks[seat] > current:
                legal.append("raise")
            order = sorted(alive, key=lambda i: (i - self.button - 1) % self.n)
            position = ("sb" if seat == self.sb_seat else "bb" if seat == self.bb_seat
                        else "late" if seat == self.button or order.index(seat) >= len(order)-2
                        else "early" if order.index(seat) < 4 else "middle")
            state = dict(hole=holes[seat], board=tuple(board), stacks=tuple(self.stacks),
                         seat=seat, active=tuple(alive), in_hand=tuple(contenders),
                         street_bets=tuple(bets), total_contributions=tuple(contributions),
                         pot=sum(contributions), to_call=call, current_bet=current,
                         min_raise=current+increment, max_raise=bets[seat]+self.stacks[seat],
                         legal_actions=tuple(legal), bb=bb, sb=sb, button=self.button,
                         position=position, players_left_to_act=max(1, len(pending)-1),
                         hand_number=hand, payouts=self.payouts, cap=self.cap,
                         blind_schedule=self.blinds, aggressor=aggressor, street=street,
                         effective_stack=min(self.stacks[seat], max(
                             self.stacks[i] + max(0, bets[i]-bets[seat])
                             for i in contenders if i != seat)))
            action = self._decision(seat, state)
            faced_fraction = bet_fraction
            kind, old_bet, pot = action["type"], current, sum(contributions)
            pending.discard(seat)
            if kind == "fold":
                contenders.remove(seat)
            elif kind == "call":
                self._pay(seat, call, bets, contributions)
            elif kind == "raise":
                self._pay(seat, action["amount"] - bets[seat], bets, contributions)
                current = bets[seat]
                if current - old_bet >= increment:
                    increment = current - old_bet
                aggressor = seat
                bet_fraction = (current - old_bet)/max(1, pot + call)
                pending |= {i for i in contenders if i != seat and self.stacks[i] and bets[i] < current}
            acted_at[seat] = current
            self._emit(dict(type="action", seat=seat, action=kind, street=street,
                            hand_number=hand, voluntary=kind in ("call", "raise"),
                            faced_raise=call > 0 and (street != "preflop" or old_bet > bb),
                            bet_fraction=faced_fraction,
                            all_in=self.stacks[seat] == 0))
            if pending:
                seat = self._next(seat, pending)

    def play(self):
        """Run to a winner or cap, assigning tied bust payouts and ICM at cap."""
        for hand in range(1, self.cap + 1):
            alive = [i for i, stack in enumerate(self.stacks) if stack]
            if len(alive) == 1:
                break
            self.button = self._next(self.button, alive)
            self.sb_seat = self.button if len(alive) == 2 else self._next(self.button, alive)
            self.bb_seat = self._next(self.sb_seat, alive)
            sb, bb = self.blinds[min((hand-1)//25, len(self.blinds)-1)]
            before = self.stacks[:]
            deck = list(DECK)
            self.rng.shuffle(deck)
            holes = {i: (deck.pop(), deck.pop()) for i in alive}
            bets, contributions, board, contenders = [0]*self.n, [0]*self.n, [], set(alive)
            self._emit(dict(type="hand_start", hand_number=hand, active=alive,
                            stacks=tuple(self.stacks), bb=bb))
            self._pay(self.sb_seat, sb, bets, contributions)
            self._pay(self.bb_seat, bb, bets, contributions)
            first = self._next(self.bb_seat, alive)
            for street, cards in (("preflop", 0), ("flop", 3), ("turn", 1), ("river", 1)):
                if cards:
                    deck.pop()  # Burn before each community-card street.
                    board.extend(deck.pop() for _ in range(cards))
                    bets = [0]*self.n
                    first = self._next(self.button, contenders)
                self._round(first, board, holes, alive, contenders, bets, contributions, bb, sb, hand, street)
                if len(contenders) == 1:
                    break
            if len(contenders) == 1:
                self.stacks[next(iter(contenders))] += sum(contributions)
            else:
                ranks = {i: rank_holdem(holes[i], board) for i in contenders}
                for i in contenders:
                    self._emit(dict(type="showdown", seat=i, hole=holes[i], board=tuple(board)))
                awards = settle_pots(contributions, contenders, ranks, self.button)
                self.stacks = [a+b for a, b in zip(self.stacks, awards)]
            assert sum(self.stacks) == self.total_chips and min(self.stacks) >= 0
            busted = [i for i in alive if self.stacks[i] == 0]
            for i in busted:
                self.bust_hands[i] = hand
            place = len(alive)
            for chips in sorted({before[i] for i in busted}):
                group = [i for i in busted if before[i] == chips]
                places = range(place-len(group), place)
                for i in group:
                    self.points[i] = sum(self.payouts[j] for j in places)/len(group)
                    for j in places:
                        self.positions[i][j] = 1/len(group)
                place -= len(group)
            if len(alive)-len(busted) == 1:
                break
        survivors = [i for i, stack in enumerate(self.stacks) if stack]
        chips = tuple(self.stacks[i] for i in survivors)
        awards = equity(chips, self.payouts[:len(survivors)])
        for i, value in zip(survivors, awards):
            self.points[i] = value
        for rank in range(len(survivors)):
            probabilities = equity(chips, tuple(int(j == rank) for j in range(len(survivors))))
            for i, probability in zip(survivors, probabilities):
                self.positions[i][rank] = probability
        return Result([bot.name for bot in self.bots], self.points, self.positions,
                      self.stacks, hand, self.errors, self.timeouts, self.timings,
                      self.timing_seats, len(survivors) > 1, self.timeout_details,
                      self.stalls, self.stall_details, self.timeouts_by_name,
                      self.errors_by_name, self.bust_hands)
