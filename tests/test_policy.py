"""Policy contract and automated portions of the playbook failure checklist."""
import ast
import inspect
import itertools
import random
from pathlib import Path
import unittest
from unittest.mock import patch

from bot.agent import Agent, clamp
from bot.icm import equity, hero_equity
from bot.strategy import decide, mode, _cap_fold, _icm_allows
from bot.tracker import Tracker, bucket


def state(n=8, **changes):
    value = dict(hole=('As', 'Ah'), board=(), stacks=(2000,) * n,
                 seat=0, active=tuple(range(n)), in_hand=tuple(range(n)),
                 street_bets=(0,) * n, total_contributions=(0,) * n,
                 pot=30, to_call=20, current_bet=20, min_raise=40,
                 max_raise=2000, legal_actions=('fold', 'call', 'raise'),
                 bb=20, sb=10, button=n-1, position='early',
                 players_left_to_act=n-1, hand_number=1,
                 payouts=(10, 7, 5, 3, 2, 1, 0, 0)[:n], cap=200,
                 effective_stack=2000, aggressor=None, street='preflop')
    value.update(changes)
    return value


class ICMTests(unittest.TestCase):
    def test_against_enumerated_orders(self):
        rng = random.Random(8)
        for n in range(2, 7):
            stacks = tuple(rng.randrange(1, 100) for _ in range(n))
            payouts = tuple(rng.randrange(11) for _ in range(n))
            expected = [0.] * n
            for order in itertools.permutations(range(n)):
                remaining, probability = sum(stacks), 1.
                for i in order:
                    probability *= stacks[i] / remaining
                    remaining -= stacks[i]
                for rank, i in enumerate(order):
                    expected[i] += probability * payouts[rank]
            for i, actual in enumerate(equity(stacks, payouts)):
                self.assertAlmostEqual(actual, expected[i])
                self.assertAlmostEqual(hero_equity(stacks, payouts, i), expected[i])

    def test_symmetry_zero_and_scale(self):
        self.assertEqual(equity([1] * 8, [8] * 8), (8.,) * 8)
        self.assertEqual(equity([10, 0, 0], [10, 7, 5]), (10., 6., 6.))
        self.assertEqual(equity([0, 0], [10, 4]), (7., 7.))
        self.assertEqual(equity([1, 3], [10]), (2.5, 7.5))
        self.assertEqual(equity([100, 300], [10]), (2.5, 7.5))
        with self.assertRaises(ValueError):
            equity([-1, 5], [10])


class TrackerTests(unittest.TestCase):
    def test_hand_counters_and_prior(self):
        tracker = Tracker()
        tracker.observe({'type': 'hand_start', 'active': [0], 'stacks': [100], 'bb': 20})
        event = dict(type='action', seat=0, street='preflop', action='raise',
                     voluntary=True, faced_raise=True, all_in=True, bet_fraction=.7)
        tracker.observe(event)
        tracker.observe(event)
        seat = tracker.seats[0]
        self.assertEqual((seat.vpip, seat.pfr, seat.shoves, seat.short_shoves), (1, 1, 1, 1))
        self.assertEqual(seat.times_faced_raise, 2)
        self.assertAlmostEqual(tracker.estimate(0, 'vpip'), (.32*15+1)/16)
        tracker.observe(dict(event, action='fold', voluntary=False, all_in=False))
        self.assertAlmostEqual(tracker.estimate(0, 'fold', 2), (7.5+1)/18)
        tracker.observe({'type':'showdown', 'seat':0, 'hole':['As','Ah'], 'board':[]})
        self.assertEqual(seat.showdowns, 1)
        tracker.reset()
        self.assertEqual(tracker.seats[0].hands, 0)
        self.assertEqual(tracker.seats[0].revealed, [])

    def test_buckets(self):
        self.assertEqual([bucket(x) for x in (.39, .4, .6, .61, .8, .81)], [0,1,1,2,2,3])


class PolicyTests(unittest.TestCase):
    def test_modes_and_every_table_size(self):
        self.assertEqual([mode(v) for v in (14.9,15,30,30.1)], ['short','middle','middle','deep'])
        for n in range(2,9):
            agent = Agent()
            for depth in (2, 8, 15, 30, 100):
                s = state(n, effective_stack=20*depth)
                self.assertIn(agent.act(s)['type'], s['legal_actions'])
            self.assertEqual(agent.errors, 0)

    def test_safety_and_legal_clamp(self):
        agent = Agent()
        for s, expected in ((state(), 'fold'), (state(legal_actions=('check','raise')), 'check')):
            with patch('bot.agent.decide', side_effect=RuntimeError('test')):
                self.assertEqual(agent.act(s), {'type':expected})
        self.assertEqual(agent.errors, 2)
        self.assertEqual(clamp({'type':'raise','amount':1}, state())['amount'], 40)
        self.assertEqual(clamp({'type':'raise','amount':9999}, state())['amount'], 2000)
        self.assertEqual(clamp({'type':'raise','amount':float('nan')}, state())['type'], 'fold')
        self.assertEqual(clamp({'type':'check'}, state())['type'], 'fold')
        self.assertEqual(clamp({'type':'raise','amount':50}, state(max_raise=30))['amount'],30)

    def test_large_risks_pass_icm(self):
        s = state(2, effective_stack=150, stacks=(150,2000), max_raise=150,
                  position='sb', players_left_to_act=1)
        with patch('bot.strategy._icm_allows', return_value=False) as check:
            self.assertEqual(decide(s)['type'], 'fold')
            check.assert_called_once()

    def test_big_pot_scenarios_conserve_chips(self):
        s = state(3, stacks=(100,200,300), pot=150, street_bets=(20,80,50), aggressor=1)
        observed = []
        def record(stacks, payouts, hero):
            observed.append(stacks)
            return 1
        with patch('bot.strategy.hero_equity', side_effect=record):
            _icm_allows(s, 100, .7, True)
        self.assertEqual(len(observed), 4)
        self.assertTrue(all(sum(chips)==750 and min(chips)>=0 for chips in observed))

    def test_cap_flat_payout_and_early_hand(self):
        self.assertFalse(_cap_fold(state()))
        self.assertTrue(_cap_fold(state(2, hand_number=199, payouts=(5,5), pot=0)))

    def test_board_only_and_all_in_postflop(self):
        agent = Agent()
        s = state(3, hole=('2s','3h'), board=('Ac','Ad','Ah','Ks','Qd'),
                  street='river', current_bet=1500,to_call=1500,aggressor=1)
        self.assertEqual(agent.act(s)['type'], 'fold')
        self.assertEqual(agent.errors,0)

    def test_submission_no_io_and_size(self):
        source = ast.parse(inspect.getsource(decide))
        self.assertFalse(any(isinstance(n,(ast.Import,ast.ImportFrom)) for n in ast.walk(source)))
        for node in ast.walk(source):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
                self.assertNotIn(node.func.id, ('open','print','eval','exec'))
        agent = Agent()
        with patch('builtins.open', side_effect=AssertionError('decision I/O')):
            agent.act(state())
        self.assertEqual(agent.errors,0)
        size = sum(p.stat().st_size for root in ('bot','tables') for p in Path(root).rglob('*') if p.is_file())
        self.assertLess(size,100_000_000)
