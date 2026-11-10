# Offline pokerbot

[![CI](https://github.com/Markus112105/pokerbot/actions/workflows/ci.yml/badge.svg)](https://github.com/Markus112105/pokerbot/actions/workflows/ci.yml)

A tournament poker bot that decides in microseconds, a game-theory solver that
measures exactly how far it strays from optimal, and an animated table to
watch it play. Python 3.11, standard library only, fully offline.

## The strategy in plain words

Most bots try to play brilliant poker. This one is built to simply never die.
Tournament poker scores you on where you finish at each table, not how many
chips you win, and weak fields play way too many hands and knock each other
out. So the bot folds almost everything early and lets the fireworks happen
around it, then switches gears as the blinds climb: it follows a
pre-calculated "shove or fold" chart for short stacks (math that's basically
solved), and before any big risk it asks "does this gamble improve my
expected finishing position?" instead of counting chips. Along the way it
takes cheap notes on each opponent: steal from the ones who always fold,
never bluff the ones who always call. The real difference is engineering:
under a one-millisecond decision limit where any crash or delay means an
automatic fold, all the heavy math happens ahead of time and the bot just
looks up answers, instantly, every single time. Tight-and-reliable beats
clever-and-crashing in a survival game.

The bot changes personality as the game ages. The mode is picked by how big
your stack is compared to the blinds, which the rising blinds shrink for
everyone:

- **Early game** (everyone deep, blinds tiny): extremely tight. Play only
  strong hands, bet them for value, never bluff, and never call a huge bet
  without a monster. Folding costs almost nothing here, and reckless
  opponents are busy eliminating each other. The goal is to not be at the
  crash site.
- **Mid game** (blinds climbing, stacks worth 15-30 big blinds): raise or
  fold, almost never just call. Open fewer but stronger hands, start stealing
  blinds from opponents the tracker has seen folding too often, and ditch
  marginal hands before they become expensive.
- **Late game** (short stacks, huge blinds): all-in or fold, straight from a
  precomputed chart, because short-stack poker is close to mathematically
  solved and bots that limp or blind away get punished mechanically here.
  Every big risk is priced in tournament points via ICM, and near the hand
  cap the bot even checks whether folding every remaining hand locks in a
  better payout than playing on.

This is deliberately **not** another GTO solver; plenty of those exist. A
game-theory-optimal bot plays "unbeatable" poker against perfect opponents;
this bot plays survival-first, exploitative poker against the flawed
opponents that actually show up. The repo does include a solver (`solver/`),
but its job is measurement, not play: it computes exactly how far the bot
strays from equilibrium (about 0.09 bb/hand in the push/fold game), so the
cost of playing exploitatively is a known, chosen number instead of a guess.

## How to run

Setup (installs nothing by design; the standard library is the tested path):

```sh
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then, from the repo root:

| Command | What it does |
| --- | --- |
| `python -m sim.watch` | record a fresh table and open the animated viewer |
| `python -m sim.run --tables 1000` | full simulation report: points, histogram, bust timing, p99 |
| `python -m sim.run --tables 1000 --lineup tight-passive` | hero vs seven copies of one baseline |
| `python -m unittest discover -s tests` | the whole test suite, ~2 s |
| `python -m benchmarks.strength` / `benchmarks.policy` | timing assertions on the hot paths |
| `python -m solver.run --game leduc --iterations 5000` | watch CFR+ converge to Nash |
| `python -m solver.pushfold_exploit` | exploitability of the push/fold tables |
| `python -m mit.benchmark --games 3` | play the MIT Pokerbots 2026 reference bots (setup below) |

eval7 is optional acceleration, auto-selected when importable
(`uv pip install eval7 --python .venv/bin/python`); the pure-Python evaluator
is proven equivalent by `tests/test_backends.py` and by a same-seed equity
regeneration that reproduced the committed table byte for byte. Baseline
names for `--lineup`: `random`, `always-call`, `always-raise`,
`tight-passive`, `loose-aggressive`, `naive-pushfold`, or seven
comma-separated names; the default `mixed` seats all six plus a second random.

## Results

Eight-seat sit-and-gos, 2,000 chips, blinds doubling every 25 hands, 200-hand
cap with ICM split, payouts 10/7/5/3/2/1/0/0. Over 1,000 tables per lineup
the bot beats every baseline with **zero errors and zero timeouts** across
roughly four million decisions (p99 decision time 0.13 ms on the slowest
path against the 1 ms budget):

| Lineup (hero + 7x) | Hero avg points | Baseline avg points |
| --- | --- | --- |
| mixed (all six) | **6.97** | best rival 5.79 |
| always-call | **7.70** | 2.90 |
| random | **7.40** | 2.94 |
| loose-aggressive | **7.40** | 2.94 |
| always-raise | **7.23** | 2.97 |
| naive-pushfold | **5.72** | 3.18 |
| tight-passive | **3.73** | 3.47 |

Full reports with histograms, bust timing by blind level, and standard errors
are in `results/`. Beating self-written baselines is the weakest kind of
evidence, which is why the next two sections exist.

## Solver: distance from Nash, measured

`solver/` is an exact CFR+ implementation (alternating updates, regret
matching+, linear averaging) with best-response exploitability, validated
against Kuhn poker's closed-form Nash value and the standard research
benchmarks (exploitability is in chips or bb per hand; zero means
unexploitable):

| Measurement | Result |
| --- | --- |
| Kuhn value, 200k iterations (exact: -1/18 = -0.05556) | -0.05558 |
| Kuhn exploitability | 0.00034 |
| Leduc hold'em value, 25k iterations (published ~ -0.0856) | -0.08580 |
| Leduc exploitability | 0.0083 |
| This repo's push/fold tables, mean over depths 2-15 bb | 0.088 bb/hand |

`python -m solver.pushfold_exploit` (after `python -m solver.matchups` builds
the card-removal-aware 169x169 equity matrix) solves the heads-up jam/fold
game to Nash at every depth (solver residual 0.000) and best-responds against
this repo's tables. Finding: the shove ranges are near-unexploitable, while
the deliberately tightened calling ranges leak ~0.2 bb/hand to a perfect
shover. That is the measured price of anti-field tightening, worth paying
only against fields that shove less than Nash.

## External benchmark: MIT Pokerbots 2026

`mit/player.py` adapts the strategy core to the MIT Pokerbots 2026 engine and
its variant: heads-up bankroll play (chip EV, so the ICM layer stays home),
three hole cards, a two-card flop, each player discards one card face-up onto
the shared board, six board cards by the river, 1,000 rounds at 1/2 blinds
with 400-chip stacks. The adapter reuses the equity table (best two-card
projection of the three-card hand), the evaluator, and a board-synergy
discard rule.

Results from `python -m mit.benchmark --games 3` (3 x 1,000 rounds each):

| Opponent (published by MIT) | Mean bb/hand | Matches won |
| --- | --- | --- |
| skeleton | +14.37 | 3/3 |
| reference-1 (toss smallest card) | +10.06 | 3/3 |
| reference-2 (good-cards betting) | +10.33 | 3/3 |
| reference-3 (Monte Carlo discard) | +9.80 | 3/3 |

MIT's reference READMEs report those bots beat the skeleton in 80-100% of
their games; this adapter beats the references themselves in every match,
worst single game +7.2 bb/hand. These are course reference bots, not
competition winners, so the claim is "clears the published baseline set by a
wide margin," not "world class". But the numbers are reproducible by anyone
against the same public opponents. Per-game data in
`results/mit_benchmark.json`.

Setup (their license is unspecified, so their code stays out of this repo in
the gitignored `vendor/`):

```sh
mkdir -p vendor && cd vendor
git clone https://github.com/mitpokerbots/engine-2026
git clone https://github.com/mitpokerbots/reference-1-2026
git clone https://github.com/mitpokerbots/reference-2-2026
git clone https://github.com/mitpokerbots/reference-3-2026
cd .. && uv pip install pkrbot --python .venv/bin/python
python -m mit.benchmark --games 3
```

## Watch it play

`python -m sim.watch` records a fresh table (random seed, printed for
reproducibility), starts a local server, and opens the animated table in the
browser: seats, hole cards, board, pot, per-action log, standings, playback
from 0.25x to 256x, and a cards toggle (all face up for analysis, or
hero-only with showdown reveals). Face-up cards are for the viewer only; bots
never see each other's hands, since engine states carry only the acting bot's
own cards. `python -m sim.record` writes replay JSON without serving; the
page's file picker loads any recording.

## Architecture

| Path | Responsibility |
| --- | --- |
| `bot/strategy.py` | phase policy, opponent adjustments, large-risk ICM gate |
| `bot/agent.py` | safety wrapper, legality clamp, interface adapter |
| `bot/strength.py` | preflop equity/percentile lookups, postflop features |
| `bot/icm.py` | exact ICM via inclusion-exclusion, memoized |
| `bot/tracker.py` | per-seat Bayesian opponent counters |
| `bot/tables.py` | import-time data loading, the variant seam |
| `tables/` | equity/push-fold generators and their JSON outputs |
| `sim/` | 8-max tournament engine, six baselines, reports, replays, watch |
| `solver/` | CFR+, Kuhn/Leduc, best response, jam/fold exploitability |
| `mit/` | MIT Pokerbots 2026 adapter and benchmark runner |
| `viewer/` | the animated replay page |
| `tests/`, `benchmarks/` | 47 tests and timing assertions |

Contracts in brief: agents implement `reset()`, `observe(event)`, `act(state)`;
raise amounts are **total street contributions**; all table loading happens at
import, never inside a decision; the strategy RNG is seeded once at import and
no decision consults a clock. The engine enforces the 1 ms budget on wall
time and separates true `timeouts` (thread-CPU over 1 ms) from `stalls` (OS
preemption with idle CPU), with GC deferred to gaps between tables so pauses
are never billed to a timed call.

## Regenerating data for a new variant

```sh
python -m tables.gen_equity --samples 20000 --workers 6
python -m tables.pushfold                    # rebuild push/fold from the equity file
python -m tables.gen_equity --variant tables.shortdeck --output tables/equity_shortdeck.json
python -m tables.pushfold --equity tables/equity_variant.json   # REQUIRED after a variant regen
```

A variant is a module in `tables/` exporting `DECK`, `HOLE_COUNT`, and
`rank(hole, board)` (larger wins), optionally `classify(hole)`;
`tables/shortdeck.py` is a worked example. Measured at 20,000 samples per
class: standard hold'em regenerates in 6.4 s with eval7 or 25.3 s pure
Python; a custom Python `rank` function costs ~2.4 s/class (the 81-class
short deck took 3:16). The generator writes atomically, and a running bot
only picks up new tables on restart since loading happens at import. The
push/fold tables are documented approximations anchored to published Nash
charts and tightened 10% for full-ring play, not a solved multiway
equilibrium; the solver section above quantifies what that costs heads-up.

Known modeling limits, in honesty: the ICM gate compares fold/win/lose
against one likely caller rather than every caller subset; postflop win
probabilities are conservative made-hand heuristics; preflop equities are
versus random cards, not solved ranges. These matter more than
sub-millisecond arithmetic when comparing policies.
