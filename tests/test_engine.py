"""Engine accounting, action order and tournament boundary regression tests."""
import unittest
from unittest.mock import patch

from sim.engine import Engine, settle_pots


class Scripted:
    name = "scripted"

    def __init__(self, action="call"):
        self.action = action
        self.reset()

    def reset(self):
        self.states, self.events = [], []

    def observe(self, event):
        self.events.append(event)

    def act(self, state):
        self.states.append(state)
        if self.action == "raise" and "raise" in state["legal_actions"]:
            return {"type": "raise", "amount": state["max_raise"]}
        return {"type": ("call" if self.action == "raise" else self.action) if state["to_call"] else "check"}


class EngineTests(unittest.TestCase):
    def test_side_pots_and_uncalled_refund(self):
        self.assertEqual(settle_pots([50, 100, 200], {0, 1, 2}, {0: 3, 1: 2, 2: 1}), [150, 100, 100])

    def test_folded_money_and_odd_chip(self):
        self.assertEqual(settle_pots([5, 5, 5], {0, 1}, {0: 1, 1: 1}, button=0), [7, 8, 0])

    def test_folded_largest_unmatched_bet_refunded(self):
        self.assertEqual(settle_pots([100, 80, 50], {1, 2}, {1: 2, 2: 1}), [20, 210, 0])

    def test_heads_up_button_acts_first_preflop(self):
        bots = [Scripted(), Scripted()]
        engine = Engine(bots, payouts=(10, 7), cap=1, shuffle=False)
        result = engine.play()
        first_actions = [e for e in bots[0].events if e["type"] == "action"]
        self.assertEqual(first_actions[0]["seat"], engine.button)
        self.assertEqual(first_actions[0]["street"], "preflop")
        post = [e for e in first_actions if e["street"] == "flop"]
        self.assertEqual(post[0]["seat"], engine.bb_seat)
        self.assertEqual(sum(result.stacks), 4000)
        self.assertAlmostEqual(sum(result.points), 17)

    def test_cap_icm_and_fractional_histogram(self):
        result = Engine([Scripted() for _ in range(8)], cap=1).play()
        self.assertTrue(result.capped)
        self.assertAlmostEqual(sum(result.points), 28)
        for histogram in result.positions:
            self.assertAlmostEqual(sum(histogram), 1)

    def test_short_allin_does_not_reopen_raise(self):
        # Seat 0 bets 100, seat 1 calls, seat 2 can raise only to 150.
        class Sequence(Scripted):
            def act(self, state):
                self.states.append(state)
                if state["seat"] == 0 and state["current_bet"] == 0:
                    return {"type": "raise", "amount": 100}
                if state["seat"] == 2 and "raise" in state["legal_actions"]:
                    return {"type": "raise", "amount": 150}
                return {"type": "call" if state["to_call"] else "check"}
        bots = [Sequence() for _ in range(3)]
        engine = Engine(bots, payouts=(10, 7, 5), shuffle=False)
        engine.stacks = [1000, 1000, 150]
        engine.sb_seat, engine.bb_seat = 1, 2
        engine._round(0, ["2c", "3d", "4h"], {0:("Ac","Ad"),1:("Kc","Kd"),2:("Qc","Qd")},
                      [0,1,2], {0,1,2}, [0,0,0], [0,0,0], 20,10,1,"flop")
        self.assertNotIn("raise", bots[0].states[-1]["legal_actions"])
        self.assertNotIn("raise", bots[1].states[-1]["legal_actions"])

    def test_all_in_tournament_conserves_points(self):
        result = Engine([Scripted("raise") for _ in range(8)], cap=20).play()
        self.assertEqual(sum(result.stacks), 16000)
        self.assertAlmostEqual(sum(result.points), 28)
        self.assertEqual(result.errors, 0)

    def test_cumulative_short_raises_reopen_action(self):
        class Sequence(Scripted):
            def act(self, state):
                self.states.append(state)
                targets = {0: 100, 1: 150, 2: 200}
                if state["seat"] in targets and len(self.states) == 1:
                    return {"type": "raise", "amount": targets[state["seat"]]}
                return {"type": "call" if state["to_call"] else "check"}
        bots = [Sequence() for _ in range(4)]
        engine = Engine(bots, payouts=(10, 7, 5, 3), shuffle=False)
        engine.stacks = [1000, 150, 200, 1000]
        engine.sb_seat, engine.bb_seat = 1, 2
        holes = {i: ("Ac", "Ad") for i in range(4)}
        engine._round(0, ["2c", "3d", "4h"], holes, [0,1,2,3], {0,1,2,3},
                      [0]*4, [0]*4, 20, 10, 1, "flop")
        self.assertIn("raise", bots[0].states[-1]["legal_actions"])
        self.assertEqual(bots[0].states[-1]["min_raise"], 300)

    def test_timeout_falls_back_and_is_counted(self):
        engine = Engine([Scripted(), Scripted()], payouts=(10, 7))
        state = {"legal_actions": ("fold", "call"), "to_call": 20}
        with patch("sim.engine.perf_counter_ns", side_effect=[0, 1_000_001]), \
             patch("sim.engine.thread_time_ns", side_effect=[0, 1_000_001]):
            action = engine._decision(0, state)
        self.assertEqual(action, {"type": "fold"})
        self.assertEqual(engine.timeouts, 1)
        self.assertEqual(engine.stalls, 0)
        self.assertEqual(engine.timeouts_by_name, {"scripted": 1})

    def test_preempted_call_stalls_without_timeout(self):
        # Wall time over the cutoff with idle CPU is host scheduling, so the
        # action is still replaced by the fallback but no timeout is charged.
        engine = Engine([Scripted(), Scripted()], payouts=(10, 7))
        state = {"legal_actions": ("fold", "call"), "to_call": 20}
        with patch("sim.engine.perf_counter_ns", side_effect=[0, 5_000_000]), \
             patch("sim.engine.thread_time_ns", side_effect=[0, 50_000]):
            action = engine._decision(0, state)
        self.assertEqual(action, {"type": "fold"})
        self.assertEqual(engine.timeouts, 0)
        self.assertEqual(engine.stalls, 1)
        self.assertEqual(engine.stall_details[0]["bot"], "scripted")

    def test_invalid_action_is_counted(self):
        engine = Engine([Scripted("bad"), Scripted("bad")], payouts=(10, 7))
        action = engine._decision(0, {"legal_actions": ("fold", "call"), "to_call": 20})
        self.assertEqual(action, {"type": "fold"})
        self.assertEqual(engine.errors, 1)

    def test_reset_and_private_cards(self):
        bots = [Scripted() for _ in range(2)]
        bots[0].states.append("stale")
        engine = Engine(bots, payouts=(10, 7), cap=1)
        self.assertEqual(bots[0].states, [])
        engine.play()
        self.assertNotIn("holes", bots[0].states[0])
        self.assertEqual(len(bots[0].states[0]["hole"]), 2)

    def test_blinds_increase_at_hand_26(self):
        bots = [Scripted("fold") for _ in range(8)]
        Engine(bots, cap=26).play()
        states = [s for bot in bots for s in bot.states]
        self.assertEqual({s["bb"] for s in states if s["hand_number"] == 25}, {20})
        self.assertEqual({s["bb"] for s in states if s["hand_number"] == 26}, {40})


if __name__ == "__main__":
    unittest.main()
