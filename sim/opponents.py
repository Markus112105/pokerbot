"""Six intentionally simple baselines; all see the same public state as Agent."""
from random import Random

from bot.strength import evaluate, preflop

KINDS = ("random", "always-call", "always-raise", "tight-passive",
         "loose-aggressive", "naive-pushfold")


class Opponent:
    """Baseline policy with a private reproducible RNG and no cross-table reads."""

    def __init__(self, name, seed=1):
        if name not in KINDS:
            raise ValueError(f"unknown opponent: {name}")
        self.name, self.seed = name, seed
        self.reset()

    def reset(self):
        self.rng = Random(self.seed)

    def observe(self, event):
        pass

    def act(self, state):
        legal, call = state["legal_actions"], state["to_call"]
        passive = {"type": "call" if call else "check"}
        fold = {"type": "fold" if call else "check"}
        target = min(state["max_raise"], max(state["min_raise"],
                     state["current_bet"] + max(state["bb"], state["pot"])))
        raise_action = {"type": "raise", "amount": target} if "raise" in legal else passive
        if self.name == "always-call":
            return passive
        if self.name == "always-raise":
            return raise_action
        if self.name == "random":
            return self.rng.choice((passive, fold, raise_action))
        if state["board"]:
            features = evaluate(state["hole"], state["board"])
            strong = features.category >= 2 or features.top_pair
            medium = features.category >= 1 or features.flush_draw or features.open_ended
            if self.name == "tight-passive":
                return passive if strong or (medium and call <= state["pot"] * .25) else fold
            if self.name == "loose-aggressive":
                return raise_action if strong or self.rng.random() < .25 else passive if medium else fold
            return passive if medium else fold
        strength = preflop(state["hole"], 1)
        if self.name == "tight-passive":
            return passive if strength >= .61 else fold
        if self.name == "loose-aggressive":
            return raise_action if strength >= .49 else passive if strength >= .43 else fold
        if state["effective_stack"] / state["bb"] < 15:
            if strength >= .50:
                return {"type": "raise", "amount": state["max_raise"]} if "raise" in legal else passive
            return fold
        return passive if strength >= .55 else fold
