"""Engine-facing adapter. Amounts are total street contributions, never increments.

Only normalize_state / encode_action change when targeting a new engine
interface (mit/player.py is a worked example). Timing and logging are opt-in
local instrumentation; the plain Agent() performs no logging or I/O.
"""
import logging
import math
from time import perf_counter_ns
from bot.tracker import Tracker
from bot.strategy import decide
from bot.icm import reset_cache


def fallback(state):
    return {'type': 'check' if 'check' in state.get('legal_actions', ()) else 'fold'}


def clamp(action, state):
    legal = state['legal_actions']
    kind = action['type']
    if kind not in legal:
        return fallback(state)
    if kind != 'raise':
        return {'type': kind}
    amount = action.get('amount')
    if not isinstance(amount, (int, float)) or not math.isfinite(amount):
        return fallback(state)
    maximum = min(state['max_raise'], state['street_bets'][state['seat']] + state['stacks'][state['seat']])
    minimum = min(state['min_raise'], maximum)
    if maximum <= state['current_bet']:
        return fallback(state)
    return {'type': 'raise', 'amount': max(minimum, min(maximum, int(amount)))}


class Agent:
    name = 'hero'
    def __init__(self, local_testing=False):
        self.local_testing = local_testing
        self.tracker = Tracker()
        self.errors = 0
        self.slow_calls = 0

    def reset(self):
        self.tracker.reset()
        reset_cache()
        self.errors = self.slow_calls = 0

    def observe(self, event):
        self.tracker.observe(event)

    def normalize_state(self, state):
        return dict(state, tracker=self.tracker)

    def encode_action(self, action):
        return action

    def act(self, state):
        start = perf_counter_ns() if self.local_testing else 0
        try:
            result = self.encode_action(clamp(decide(self.normalize_state(state)), state))
        except Exception:
            self.errors += 1
            result = fallback(state)
        if self.local_testing and perf_counter_ns() - start > 500_000:
            self.slow_calls += 1
            logging.getLogger(__name__).warning('Decision exceeded 0.5 ms')
        return result
