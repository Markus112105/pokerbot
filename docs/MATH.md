# The Math, With Game Context

Every technique in this repo exists to answer a concrete in-game question
under one constraint: a decision must return in under 1 millisecond, and any
overrun is scored as an automatic fold. This document walks through each
piece of math, what question it answers at the table, and what it measured.

## 1. Why the 1 ms rule shapes everything

The rule splits the math into two worlds. Anything slow runs **offline**,
before play, and is saved as a lookup table. Anything that runs **during a
hand** must be a dictionary lookup or short closed-form arithmetic with a
known worst case.

The arithmetic that forces the split: one simulated deal in Python costs
about 11 microseconds, so a millisecond buys roughly 50-100 random deals. An
equity estimate from 100 deals is noisy by plus or minus 5-9 percentage
points (see the standard error formula below), while real decisions hinge on
margins of 3-5 points. Live simulation would be noisier than the decisions
it feeds. So the bot never simulates during a hand: it spent ~25 seconds at
build time on 13.5 million deals, and answers from that work in ~0.01 ms,
with a measured p99 decision time of 0.13 ms on the slowest path and zero
timeouts over roughly four million decisions.

## 2. Monte Carlo: building the preflop equity table

**In-game question: "how often does this starting hand win?"**

There is no clean formula for AKs against three random opponents, so
`tables/gen_equity.py` deals the future thousands of times and counts: deal
random opponent hands and a random board, check who won, average. Each
sample is unbiased; averaging converges on the truth.

Two facts keep the table small and the error known. First, suit symmetry
collapses the 1,326 two-card holdings into **169 classes** (13 pairs, 78
suited, 78 offsuit), because before the flop only ranks and suitedness
matter. Second, the error of a win-rate estimate from $n$ samples is the
standard error of a proportion:

$$SE = \sqrt{\frac{p(1-p)}{n}} \le \frac{0.5}{\sqrt{n}}$$

At 20,000 samples per class that bound is ±0.35 percentage points, far
tighter than any decision threshold. The generator runs each class against
1, 2, 4, and 7 random opponents because hand values collapse multiway: AKo
wins ~65% heads-up but under 30% against seven callers.

The table feeds two lookups at the table:

- **Equity** answers "am I getting the right price?" against pot odds.
- **Percentile** (what fraction of hands are stronger) drives the open
  ranges: "raise the top 12% from early position" is one comparison.

The same machinery built the 169×169 hand-vs-hand matrix the solver uses
(`solver/matchups.py`), with card removal respected: opponent combos are
sampled only among those not colliding with yours, and exact disjoint-combo
counts weight every matchup.

## 3. Hand evaluation as bit arithmetic

**In-game question: "what did I make, and does it beat theirs?"**

`rank_python` in `tables/gen_equity.py` turns a hand into bitmasks: one
15-bit mask of ranks present, one mask per suit. A straight is five
consecutive set bits, detected in constant time:

```python
runs = mask & (mask >> 1) & (mask >> 2) & (mask >> 3) & (mask >> 4)
```

Rank counts find pairs, trips, and quads; a suit mask with five or more bits
is a flush. The result packs into a single integer, category in the high
bits, kickers below:

$$\text{value} = \text{category} \cdot 2^{24} + \sum_i \text{kicker}_i \cdot 2^{16-4i}$$

so "which hand wins?" is integer comparison and "what did I make?" is
`value >> 24`. It evaluates the best five cards out of 5-9, which is why the
same function scores a hold'em showdown (7 cards) and the MIT variant's
8-card showdowns unchanged. Equivalence with the C library eval7 was proven
two ways: a pairwise ordering test over thousands of random boards, and a
same-seed regeneration of the whole equity table that reproduced it byte
for byte across 13.5 million showdowns.

## 4. ICM: converting chips into tournament points

**In-game question: "this shove risks my tournament life — is it worth it
in prize money, not chips?"**

In a tournament, chips are not points. If payouts are 10/7/5 for three
players left, doubling your stack does not double your expected payout, and
busting costs everything. Losing 1,000 chips hurts more than winning 1,000
helps. The Independent Chip Model makes that precise: it assumes each
player's finishing chances follow their chip share, models finishing order
as an "exponential race", and computes each player's expected points
exactly.

The core identity: the probability that your stack $s$ outlasts a subset
$T$ of opponents (finishes ahead of all of them) is

$$P(\text{beat } T) = \frac{s}{s + \sum_{j \in T} s_j}$$

`bot/icm.py` combines these race terms over all $2^{n-1}$ opponent subsets
with inclusion-exclusion, weighting each subset by a finite difference of
the payout vector built from binomial coefficients. For 8 players that is
128 terms: exact, around 0.1 ms cold and effectively free memoized. Tests
check it against brute-force enumeration of every finishing order.

Where it bites in-game:

- **The 25% gate.** Any action risking more than a quarter of the stack is
  checked as: expected points if I fold, versus
  $P(\text{win}) \cdot \text{ICM}(\text{stacks if I win}) + P(\text{lose}) \cdot \text{ICM}(\text{stacks if I lose})$,
  with a fold-equity term when raising. Near a payout cliff (the biggest gap
  between adjacent prizes) the required edge rises by 10-15 points, which is
  why the bot folds hands near the bubble that a cash game would snap-call.
- **The cap fold-out.** From hand 170 of the 200-hand cap, the bot projects
  paying every remaining forced blind, hands those chips to the largest
  rival, and compares ICM now versus ICM then. If folding everything locks
  in an equal or better payout, it folds everything. With flat payouts this
  fires often; with graded payouts rarely, because surrendered blinds are
  surrendered equity.

## 5. Live decision math: pot odds, EV, and sizing

**In-game question: "is this call, bet, or bluff profitable right now?"**

The breakeven for a call is pure pot odds. Calling $c$ into a pot $P$ needs
win probability

$$p^* = \frac{c}{P + c}$$

and the bot requires measured margins above it, not equality: +5 points of
equity to call a short-stack shove, +8 postflop, +10-15 more near a payout
cliff. The margins absorb estimation error (equity-vs-random is a proxy for
equity-vs-range) and buy survival, deliberately.

Raising adds a fold-equity term. If each live opponent folds with
probability $f_i$, the raise's value is

$$EV = \Big(\prod_i f_i\Big) \cdot \text{ICM}(\text{uncontested}) + \Big(1 - \prod_i f_i\Big) \cdot EV_{\text{called}}$$

with the fold probabilities read from the opponent tracker.

Bet sizing is drawn uniformly from 55-75% of pot, same band for value bets
and bluffs so sizing leaks no information, clamped to the legal bounds. The
generator is a module-level RNG seeded once at import: no clock access, no
entropy calls, nothing time-dependent inside a decision.

## 6. Bayesian opponent modeling

**In-game question: "this player has folded six times — can I steal yet?"**

Raw frequencies lie early: an opponent who folded twice in two chances is
not a 100% folder. The tracker (`bot/tracker.py`) blends every observed
rate toward a population prior with shrinkage:

$$\hat{p} = \frac{k \cdot p_{\text{prior}} + n \cdot \bar{x}}{k + n}, \qquad k = 15$$

With $k=15$, five observed hands move the estimate only a quarter of the way
from the prior to the data; after ~60 hands the data dominates. That speed
is matched to the game: a table lasts at most 200 hands, so reads must be
usable after ~20 and never explode off two samples.

Three archetype rules consume the estimates:

| Read | Trigger | Response |
| --- | --- | --- |
| Calling station | VPIP > 45% and fold-to-raise < 40% | never bluff, value-bet thinner |
| Folder | fold-to-raise > 70% | steal relentlessly from late position |
| Maniac | preflop raise rate > 35% | call wider, trap with premiums |

The tracker also buckets fold rates by bet size (under 40% pot, 40-60,
60-80, over 80), so fold-equity estimates match the size actually used.

## 7. Push/fold: the solved endgame

**In-game question: "8 big blinds on the button — which hands do I shove?"**

Short-stack play is nearly a solved game because the tree collapses: with
under ~15 big blinds, raising small just commits you anyway, so the only
sane actions are all-in or fold, and the opponent's only answers are call
or fold. One street, no postflop. The EVs are three lines of algebra (from
the small blind, stacks $S$ in big blinds):

$$EV_{\text{fold}} = -\tfrac{1}{2}, \qquad EV_{\text{shove}} = P(\text{fold}) \cdot (+1) + P(\text{call}) \cdot \big(2S \cdot \text{eq} - S\big)$$

and the caller's mirror: call when $2S \cdot \text{eq} - S > -1$. Solving
the two ranges against each other at every depth gives the Nash jam/fold
equilibrium. The repo's tables (`tables/pushfold.py`) interpolate published
Nash anchors over the equity ordering, then tighten the selected fraction by
×0.90 for full-ring play, keyed on (stack depth 2-15 bb, players left to
act, position).

This phase is where most of the bot's edge lives, because badly built
opponents limp, min-raise, or blind away at depths where the chart punishes
every one of those mechanically.

## 8. The solver: CFR+ and exploitability

**The question here is not "what should I play?" but "how good are the
tables I already play?"**

Counterfactual Regret Minimization is iterated self-play: after each
iteration, every decision point accumulates *regret* for each action (how
much better that action would have done than the mix actually played), and
the next iteration plays actions in proportion to positive regret:

$$\sigma(a) = \frac{R^+(a)}{\sum_b R^+(b)}$$

The time-averaged strategy provably converges to a Nash equilibrium in
two-player zero-sum games. `solver/cfr.py` implements the CFR+ variant:
regrets clipped at zero, linear averaging, and **alternating** updates
(one player updated per traversal — with simultaneous updates the clipped
variant demonstrably stalls, which this repo reproduced before fixing).

**Exploitability** is the yardstick: compute the best response to a
strategy (the perfect counter-strategy, via a belief-state recursion that
maxes per information set), and measure how much it wins.

$$\text{exploitability} = \frac{br_0 + br_1}{2}$$

Zero means unexploitable (Nash); any positive value is the bounty a perfect
opponent collects per hand. Measured results:

| Measurement | Result |
| --- | --- |
| Kuhn poker value, 200k iterations (exact Nash: $-1/18 = -0.0556$) | $-0.05558$ |
| Kuhn exploitability | $0.00034$ |
| Leduc hold'em value, 25k iterations (published $\approx -0.0856$) | $-0.08580$ |
| Leduc exploitability | $0.0083$ |
| This repo's push/fold tables, mean over depths 2-15 bb | $0.088$ bb/hand |

Kuhn's closed-form value is the correctness oracle. The push/fold number is
the punchline: the bot's tables leak 0.088 bb/hand to a *perfect* exploiter,
concentrated in the deliberately tightened calling ranges, while the shove
ranges are near-unexploitable. That is the measured price of playing
exploitatively instead of GTO, paid on purpose because real fields shove
less than Nash. The solver exists to price that trade, not to play.

## 9. Summary: every method in one table

| Method | Runs | In-game job | Measured |
| --- | --- | --- | --- |
| Monte Carlo sampling | offline | preflop equity and percentile tables | ±0.35% per entry |
| Suit-isomorphism combinatorics | offline | 1,326 hands → 169 classes | exact |
| Bitmask hand evaluation | live, ~0.01 ms | showdowns, made-hand category | byte-identical to eval7 over 13.5M deals |
| ICM (inclusion-exclusion) | live, <0.1 ms | big-risk gate, cliff tightening, cap fold-out | matches brute-force enumeration |
| Pot odds + EV arithmetic | live | every call, bet, and steal | margins +5 to +15 points |
| Bayesian shrinkage (k=15) | live | opponent reads that converge in ~20 hands | three archetype exploits |
| Jam/fold algebra | offline tables, live lookup | the entire short-stack game | 0.088 bb/hand from Nash |
| CFR+ and best response | offline, measurement only | grades the tables against equilibrium | Kuhn to 4 decimals of exact Nash |

The pattern across all of it: sampled math where time is free, exact math
where time is scarce, and game-theoretic math to audit the result.
