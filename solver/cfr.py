"""Exact counterfactual regret minimization (canonical CFR+).

Enumerates every deal each iteration (no sampling), with alternating
updates: each iteration traverses the tree once per player, updating only
that player's regrets while the opponent plays the current strategy.
Alternation is required for CFR+'s convergence guarantee — regret
matching+ (negative regrets clipped) with simultaneous updates stalls on
games as small as Leduc. With `plus` the average strategy is linearly
weighted (CFR+); with `plus=False` this is alternating vanilla CFR.

Game interface (see solver.games): deals(), player(), actions(), infoset(),
utility(). utility() is from player 0's perspective; traversals re-sign it
for the updating player.
"""


def regret_matching(regrets):
    positive = [max(0.0, r) for r in regrets]
    total = sum(positive)
    if total <= 0:
        return [1.0 / len(regrets)] * len(regrets)
    return [p / total for p in positive]


class CFRTrainer:
    def __init__(self, game, plus=True):
        self.game = game
        self.plus = plus
        self.regrets = {}
        self.strategy_sum = {}
        self.iteration = 0

    def run(self, iterations):
        for _ in range(iterations):
            self.iteration += 1
            for updating in (0, 1):
                for deal, probability in self.game.deals():
                    self._cfr(deal, "", updating, 1.0, probability)
        return self

    def _cfr(self, deal, history, updating, my_reach, opp_reach):
        """Expected utility for `updating` given both reach probabilities.

        my_reach: product of the updating player's own strategy choices.
        opp_reach: chance probability times the opponent's strategy reach —
        the counterfactual weight applied to regret updates.
        """
        game = self.game
        player = game.player(deal, history)
        if player is None:
            utility = game.utility(deal, history)
            return utility if updating == 0 else -utility
        key = game.infoset(deal, history)
        actions = game.actions(deal, history)
        regrets = self.regrets.setdefault(key, [0.0] * len(actions))
        strategy = regret_matching(regrets)
        if player != updating:
            node_utility = 0.0
            for probability, action in zip(strategy, actions):
                if probability > 0:
                    node_utility += probability * self._cfr(
                        deal, history + action, updating, my_reach, opp_reach * probability)
            return node_utility
        utilities = [self._cfr(deal, history + action, updating,
                               my_reach * probability, opp_reach)
                     for probability, action in zip(strategy, actions)]
        node_utility = sum(p * u for p, u in zip(strategy, utilities))
        averaged = self.strategy_sum.setdefault(key, [0.0] * len(actions))
        weight = self.iteration if self.plus else 1
        for i in range(len(actions)):
            regrets[i] += opp_reach * (utilities[i] - node_utility)
            if self.plus and regrets[i] < 0:
                regrets[i] = 0.0
            averaged[i] += weight * my_reach * strategy[i]
        return node_utility

    def average_strategy(self):
        """Infoset -> action probabilities; the quantity that converges to Nash."""
        profile = {}
        for key, sums in self.strategy_sum.items():
            total = sum(sums)
            profile[key] = ([s / total for s in sums] if total > 0
                            else [1.0 / len(sums)] * len(sums))
        return profile


def expected_value(game, profile):
    """Expected utility for player 0 when both players follow `profile`."""
    def walk(deal, history):
        player = game.player(deal, history)
        if player is None:
            return game.utility(deal, history)
        actions = game.actions(deal, history)
        strategy = profile.get(game.infoset(deal, history))
        if strategy is None:
            strategy = [1.0 / len(actions)] * len(actions)
        return sum(p * walk(deal, history + a) for p, a in zip(strategy, actions) if p > 0)

    return sum(probability * walk(deal, "") for deal, probability in game.deals())
