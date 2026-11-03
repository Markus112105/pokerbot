# Offline pokerbot

Python 3.11 preparation repo for the rules in `no-limit-pokerbot-playbook.md`.
The competition kit remains authoritative for the actual variant and interface.
All bot, generator, benchmark, and simulator execution is offline.

## Run locally

```sh
python3.11 -m venv .venv
source .venv/bin/activate
pip install --no-index -r requirements.txt
python -m unittest discover -s tests -v
python -m sim.run --tables 1000 --output results/mixed.json
```

`pip install -r requirements.txt` also works. The requirements file intentionally
has no mandatory packages: the standard-library evaluator is a fully tested
primary path, so the repo runs with no downloads at all. eval7 is selected
automatically when importable, and both backends are now benchmark- and
simulation-tested in this venv (`uv pip install eval7 --python .venv/bin/python`;
the plain `pip` on this machine belongs to a different Python). If eval7 is
missing on the day, nothing needs to change.

Run one hero against seven copies of a baseline:

```sh
python -m sim.run --tables 1000 --lineup tight-passive
python -m sim.run --tables 1000 --lineup loose-aggressive --seed 42
python -m sim.run --tables 1000 --payouts 10,7,5,3,2,1,0,0
```

Other baseline names are `random`, `always-call`, `always-raise`, and
`naive-pushfold`. A comma-separated list of seven names specifies a mixed table.
Default `mixed` includes all six baselines and a second random player. Reported
baseline averages are per seat/table, so the duplicated random bot is normalized
correctly. Tied finishes share histogram counts. At the cap, fractional counts
are ICM finish probabilities, not invented realized finish positions.

## Files and contracts

| File | Responsibility |
| --- | --- |
| `bot/agent.py` | Normalize kit state, safety wrapper, legal clamp, encode action |
| `bot/tables.py` | Import-time data loading and variant seam |
| `bot/strength.py` | Preflop equity/percentiles and postflop features |
| `bot/icm.py` | Exact ICM; full field and fast single-seat queries |
| `bot/tracker.py` | Per-table Bayesian statistics and fold-size buckets |
| `bot/strategy.py` | Phase policy, opponent adjustments, large-risk ICM gate |
| `tables/` | Generators, JSON data, optional variant modules |
| `sim/` | Offline holdem engine, six baselines, CLI reports |
| `tests/`, `benchmarks/` | Correctness checks and timing assertions |

All agents implement `reset()`, `observe(event)`, and `act(state)`. Actions use
`{'type': 'fold'|'check'|'call'|'raise'}`; raises additionally have `amount`, the
**total street contribution**, including chips already committed that street.
Calls automatically pay the lesser of the amount owed and the remaining stack.
`max_raise` is an engine-provided total target, allowing pot-limit adapters to
restrict it further. A short all-in raise is legal only when the engine permits
raising; it does not automatically reopen betting.

`state` has hole cards, board, remaining stacks, active seats, nonfolded seats,
street bets, total contributions, pot, acting seat, blind amounts, legal actions,
min/max raise targets, call amount, effective stack, button, position, players
left to act, hand number, payouts, hand cap, and blind schedule. Cards use `As`,
`Td`, etc. The agent adds its tracker. Effective stack includes the amount needed
to match an opponent's already-committed all-in; it is not zero against an all-in.
Observation events contain no private opponent cards except revealed showdowns.

The RNG is seeded once at strategy import. No clock is consulted by `decide`.
The simulator's deck/seating and dummy RNGs use CLI seeds. Different wall-clock
timeouts can still change the subsequent run. `Agent()` has no local logging;
`Agent(local_testing=True)` warns through Python logging for calls over 0.5 ms.
The engine independently measures and enforces a 1 ms wall-clock cutoff.

## Regenerate equity and push/fold data

```sh
python -m tables.gen_equity --samples 20000 --workers 6
python -m tables.pushfold
```

The saved holdem table contains all 169 classes versus 1, 2, 4, and 7 random
opponents. Each class/field size receives 20,000 samples. Field sizes reuse the
same sampled seven-opponent deals; each estimate is unbiased but the four
estimates are correlated. Ties split equity. Metadata records sample count,
seed, backend, class count, and runtime. Generation time is machine-dependent.

For a variant, place a module in `tables/` exporting `DECK`, `HOLE_COUNT`, and
`rank(hole, board)` (larger ranks win). Optionally export `classify(hole)` for
starting classes. Functions must be top-level and importable by worker processes.

```sh
python -m tables.gen_equity --variant tables.shortdeck --samples 20000 \
  --workers 6 --output tables/equity_shortdeck.json
```

The supplied short-deck example uses ranks 6-A, flush above full house, and the
A-6-7-8-9 straight. A custom rank callback can enforce Omaha's exactly-two-hole,
exactly-three-board rule by maximizing over those combinations. The generator
accepts other hole counts, but still deals five board cards and eight players;
it rejects decks too small to do so. Suit-isomorphic classes are safe only for
suit-symmetric rules; supply a custom classifier otherwise. More hole cards can
create many more classes, so the five-minute budget is not guaranteed for every
variant. Measured on this laptop: standard hold'em (169 classes, eval7 or the
built-in ranker) regenerates in under 30 seconds, but a variant module with a
custom Python `rank` function runs roughly 8x slower per class — the 81-class
short deck took 3:16 at 20,000 samples. Day-of rule: for any custom-ranking
variant, generate the first table with `--samples 10000`, submit the T1 floor,
then regenerate at full samples in the background. Retain the metadata.

Switch the data/ranking configuration in `bot/tables.py` and regenerate push/fold
data with the new equity file. For changed postflop rules, set `FEATURE_EXTRACTOR`
to a variant module's callable returning the `bot.strength.Features` contract;
normalize categories to the policy's made-hand meaning. Holdem open-range heuristics and postflop feature
semantics require review for unusual variants, particularly wild cards, different
community-card counts, or Omaha. Regenerating random-card equities alone does not
make a holdem strategy correct for those games. The local simulator is standard
holdem; use the provided kit simulator for variant validation.

Push/fold JSON has explicit `(stack 2..15, players 1..7, position)` records and
per-hand minimum/maximum valid stack bounds. These are documented approximations
anchored to the playbook's ranges, tightened by a 0.90 multiplier, **not a solved
multiway Nash equilibrium**. Weak hands generally become shoves below a maximum
depth; interpreting a minimum as “shove whenever deeper” would invert the policy.
The method and source reference are in `tables/pushfold.py`; no charts are fetched.

## ICM and strategy assumptions

ICM uses exact exponential-race inclusion-exclusion, checked against exhaustive
finish-order enumeration. Zero stacks share remaining bottom places. Tournament
payouts are descending; the calculator also accepts arbitrary nonnegative vectors
for finish-probability queries. Caches reset between tables to avoid accumulating
irrelevant states and long garbage-collection scans.

The **decision scenario** remains an approximation: it compares chip-conserving
fold/win/lose outcomes against one likely caller, with a fold-equity estimate for
raises. Multiway side pots are settled exactly by the engine, but the strategy's
ICM gate does not enumerate every possible caller subset. Postflop win probabilities
are conservative made-hand heuristics; preflop equities are versus random cards,
not solved opponent ranges. These limitations matter more than sub-millisecond
arithmetic accuracy when comparing policies.

At hand 170, fold-out logic projects remaining forced blinds under a fixed
survivor set, transfers those chips to an opponent, and compares projected ICM
with current ICM. It can fire with flat payouts; it usually will not with strictly
graded payouts because folding blinds lowers equity. It does not assume future
opponent eliminations. Blind doubling every 25 hands, simultaneous bust ordering
by starting stack, and clockwise odd-chip assignment are local assumptions that
must be confirmed with the kit. Filler status is not used to redistribute points.

## Timing and failure checks

```sh
python -m benchmarks.strength
python -m benchmarks.policy
python -m benchmarks.policy --load
```

Strength evaluates 10,000 random postflop hands and asserts p99 below 0.3 ms.
Policy timing asserts cold/cached eight-seat ICM p99 below 0.1 ms and full
postflop-plus-ICM decision p99 below 0.5 ms. Maxima are printed too: an OS
preemption can exceed a hard wall-clock limit even when CPU work is short.

The engine enforces the 1 ms cutoff on wall time, replacing the overrunning
action with check-else-fold exactly as the kit would. Accounting separates the
two causes: a call whose **thread-CPU** time exceeded 1 ms is a `timeout`
(the bot was slow); a call over the wall cutoff with idle CPU is a `stall`
(the host descheduled the process mid-call). Both are reported with counts,
per-bot-name attribution, and the first ten diagnostic records carrying wall
and CPU times; a stall still costs the hand locally but is machine noise, not
evidence of a slow decision path. `sim.run` defers automatic garbage
collection to the gap between tables, so shared-process gen-2 GC pauses are
never billed to a timed call; packed timing arrays keep telemetry off the GC
heap. The real kit presumably isolates each bot; if allowed, calling
`gc.disable()` at import in the submitted agent gives the same protection.

Automated tests cover evaluator ranking and draws, table invariants, ICM reference
comparisons, Bayesian counters, reset behavior, phase boundaries, legal clamps,
exception fallback, no decision-time file opens/imports, first-hand and 2-8-seat
states, all-ins, side pots, reopening, cap payouts, chip conservation, output
reports, and submission size. The benchmark exercises the costly decision path.
Active-submission confirmation and the kit's actual timing/sandbox behavior remain
manual checks; local tests cannot establish them.

## The 60-minute adaptation checklist

| Minutes | Action and completion check |
| --- | --- |
| 0-5 | Both teammates read variant/interface. A records deck, rankings, hole cards, betting, payouts; B reads simulator and ICM APIs. |
| 5-15 | A regenerates data with a five-minute budget. B adapts `bot/agent.py` state/actions/events and checks the `bot/tables.py` seam. |
| 15-20 | Run 200 kit tables; require zero errors/timeouts and a plausible histogram. Submit the working T1 floor. |
| 20-35 | Confirm blind schedule, push/fold depths and payout cliffs. Run 1,000 kit tables; submit at minute 35 if points improve. |
| 35-50 | Validate tracker reads and sizing against the actual variant. Run 1,000 tables; submit at minute 50 only if points improve. |
| 50-60 | Freeze features. Benchmark under load, recheck legality/errors and active submission confirmation. |

A owns data/strategy and B owns adapter/simulation/submission throughout. Preserve
the last accepted package before each change. Example local snapshot:

```sh
python -m unittest discover -s tests
tar -czf known-good-bot.tgz bot tables requirements.txt
```

Keep the active platform submission confirmation alongside the local report.
Do not infer tournament acceptance from a successful local run.
