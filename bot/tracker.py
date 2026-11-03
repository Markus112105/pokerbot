"""Per-table seat statistics; sets prevent counting repeated actions as hands.

Beta-style prior mass k is measured in opportunities for each statistic.
Fold buckets use the faced bet divided by the pot before that bet.
"""
from dataclasses import dataclass, field


def bucket(fraction):
    """40%, 60%, 80% belong to the 40-60, 40-60, 60-80 buckets."""
    return 0 if fraction < .4 else 1 if fraction <= .6 else 2 if fraction <= .8 else 3


@dataclass
class Seat:
    hands: int = 0
    vpip: int = 0
    pfr: int = 0
    folds_to_raise: int = 0
    times_faced_raise: int = 0
    shoves: int = 0
    showdowns: int = 0
    short_hands: int = 0
    short_shoves: int = 0
    faced_buckets: list = field(default_factory=lambda: [0] * 4)
    fold_buckets: list = field(default_factory=lambda: [0] * 4)
    seen: set = field(default_factory=set)
    revealed: list = field(default_factory=list)


class Tracker:
    def __init__(self, k=15, priors=None):
        self.k = k
        self.priors = {'vpip': .32, 'pfr': .15, 'fold': .5, 'shove': .18}
        self.priors.update(priors or {})
        self.reset()

    def reset(self):
        self.seats = [Seat() for _ in range(8)]

    def estimate(self, seat, metric, size_bucket=None):
        s = self.seats[seat]
        if metric == 'fold':
            hits, trials = (s.folds_to_raise, s.times_faced_raise) if size_bucket is None else (
                s.fold_buckets[size_bucket], s.faced_buckets[size_bucket])
        elif metric == 'shove':
            hits, trials = s.short_shoves, s.short_hands
        else:
            hits, trials = getattr(s, metric), s.hands
        return (self.priors[metric] * self.k + hits) / (self.k + trials)

    def observe(self, event):
        kind = event['type']
        if kind == 'hand_start':
            for i in event['active']:
                s = self.seats[i]
                s.hands += 1
                s.seen.clear()
                if event.get('stacks', [float('inf')] * 8)[i] < 15 * event.get('bb', 0):
                    s.short_hands += 1
                    s.seen.add('short')
            return
        s = self.seats[event['seat']]
        if kind == 'showdown':
            s.showdowns += 1
            s.revealed.append((tuple(event.get('hole', ())), tuple(event.get('board', ()))))
            return
        if kind != 'action':
            return
        action = event['action']
        for metric, occurred in (
            ('vpip', event.get('street') == 'preflop' and event.get('voluntary', False)),
            ('pfr', event.get('street') == 'preflop' and action == 'raise'),
            ('shoves', event.get('all_in', False)),
        ):
            if occurred and metric not in s.seen:
                setattr(s, metric, getattr(s, metric) + 1)
                s.seen.add(metric)
                if metric == 'shoves' and 'short' in s.seen:
                    s.short_shoves += 1
        if event.get('faced_raise', False):
            b = bucket(event.get('bet_fraction', 0))
            s.times_faced_raise += 1
            s.faced_buckets[b] += 1
            if action == 'fold':
                s.folds_to_raise += 1
                s.fold_buckets[b] += 1
