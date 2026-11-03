# The 60-minute build: operational plan

Two people, fixed roles, hard gates. The clock column is wall time from the
variant announcement. Rule zero: **a working bot submitted at minute 20 beats a
clever bot submitted at minute 55.** Every decision below serves that.

## Roles (do not swap mid-build)

| | Teammate A — Data & Strategy | Teammate B — Plumbing & Submission |
| --- | --- | --- |
| Owns | `tables/`, `bot/strategy.py`, `bot/strength.py`, push/fold, ICM thresholds | `bot/agent.py`, kit simulator runs, timing, version control, **every submission** |
| Never touches | `bot/agent.py` | `bot/strategy.py` |

B is the only person who submits, and announces each submission out loud with
the time. A never blocks a submission to finish "one more thing."

## Before the clock (arrive 30+ minutes early)

Both laptops, independently:

```sh
git clone <repo> && cd pokerbot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # no packages needed; eval7 optional
python -m unittest discover -s tests       # expect 37-38 OK
python -m sim.run --tables 50              # expect hero winning, 0 errors
tar -czf known-good-bot.tgz bot tables requirements.txt
```

Also: Codex/Astra logged in and answering, a visible countdown timer set to 60,
this file and the README open, phones away. Agree on who is A and who is B now.

## 0–5 — Read (both, in parallel, no code)

**A writes down the variant deltas** on paper, one line each:
deck (size, ranks), hole-card count, hand rankings (any reorder like
flush > full house?), betting structure (no-limit? antes? bounties?), payout
list, blind schedule, hand cap, chips. Circle every line that differs from
standard hold'em.

**B reads the kit**: the `Agent` interface (method names, what `state`
contains, how actions are encoded), the simulator CLI, the ICM calculator.
**The single most important question: are raise amounts a total street
contribution, a raise-to amount, or an increment?** Our engine uses total
street contribution; getting this wrong is the classic day-killer bug.
Second question: how does the kit report errors/timeouts in its sim output.

**Minute-5 gate (say it out loud):** which path are we on?
- **Path 1 — standard or near-standard** (deck/rankings unchanged): skip
  regeneration entirely; A moves to payout/blind verification.
- **Path 2 — data regen needed** (deck, rankings, or hole cards changed):
  A starts the generator immediately (see budget table below).
- **Path 3 — structure change** (pot-limit, bounties, weird payouts): data as
  needed, plus the contingency row at the bottom of this file.

## 5–15 — Adapt (parallel)

**A — data.** Generation budget, measured on this laptop at 20k samples:

| Case | Command | Expected time |
| --- | --- | --- |
| Standard deck/rules | nothing to do | 0 |
| New deck, standard-style ranking | `python -m tables.gen_equity --workers 6` (eval7 path) | ~10 s |
| Custom `rank` function | write `tables/variant.py` (DECK, HOLE_COUNT, rank, optional classify), then `python -m tables.gen_equity --variant tables.variant --samples 10000 --workers 6 --output tables/equity_variant.json` | ~1.2 s/class → ~3:25 for 169 classes |

For a custom-rank variant, **10,000 samples first, always**. Full-sample regen
happens in the 20–35 window while the floor is already submitted, and a
regenerated table only takes effect on **resubmission** (tables load at
import). After equity: `python -m tables.pushfold` (seconds), then point
`bot/tables.py` at the new files. Use `tables/shortdeck.py` as the template —
it was the dry-run variant.

**B — adapter.** Rewrite only `normalize_state` / `encode_action` in
`bot/agent.py`, mapping the kit's state to the dict contract listed in the
README ("Files and contracts" section). Checklist: hole/board card format,
stacks, seat, position, `to_call`, `min_raise`/`max_raise` semantics, legal
actions, hand number, payouts, blind values, effective stack. Wire the kit's
events into `tracker.observe` if the event shapes differ. Use Codex for this
mechanical mapping; do not let it near `strategy.py`.

**Both, when either finishes early:** A sanity-checks the payout list — find
the biggest gap between adjacent places (that's the bubble; `strategy.py`
derives it automatically from `payouts`, just confirm the list arrives in
order). B confirms the blind schedule reaches `state['blind_schedule']` or
hardcodes the announced one in the adapter.

## 15–20 — Smoke test, then SUBMIT (hard gate)

B runs 200 tables in the **kit's** simulator (cut to 50 if their sim is slow —
we need a sanity histogram, not precision). Pass criteria:

- zero errors, zero timeouts in the kit's output;
- finishing-position histogram not all 8th place;
- spot-check three logged hands: actions are legal and sane.

**Submit at minute 20 even if imperfect** (any legal, non-crashing bot beats a
missed T1). Record the platform's acceptance confirmation. Then freeze the
floor: `git add -A && git commit -m "T1 floor" && git tag day-t1 && git push --tags`
(or `tar -czf t1-floor.tgz bot tables` if the venue network is unreliable).

## 20–35 — Push/fold and ICM against the real structure

- A: if the first table used 10k samples, rerun at 20k now and verify the
  blind schedule matches our mode boundaries — if blinds rise gentler than
  doubling, the deep/middle/short transitions arrive later, which is fine
  (modes key on effective BB, not hand number); nothing to change unless the
  schedule is radically flatter.
- A: check push/fold depths against the real payout cliffs; the `strategy.py`
  cliff margin derives from `payouts` automatically.
- B: 1,000 kit tables. Compare average points to the floor run.
- **Submit at 35 only if points improved.** Otherwise the floor stays active —
  that is a fine outcome, say so out loud and move on.

## 35–50 — Tracker reads and sizing

- B: verify tracker counters actually move (print VPIP for one opponent after
  200 kit hands; if all stats sit at the prior, the event wiring is broken —
  fix or ship without reads, the bot degrades gracefully to priors).
- A: sizing only if the variant demands it (antes → open slightly larger;
  pot-limit → the clamp already handles it). No new features.
- B: 1,000 kit tables. **Submit at 50 only if points improved.**

## 50–60 — Freeze (no exceptions)

- No code changes, no "quick fixes," no regeneration.
- Re-run `python -m benchmarks.policy --load` once under load.
- B confirms on the platform **which submission is active** and reads the
  confirmation to A. Keep the known-good tarball/tag where one command
  restores it.
- Write down, for the between-tournament windows: observed field VPIP,
  anything that looked off in the logs, and the local average-points number
  for the active bot.

## Abort rules (either person can call these)

- **Any error or timeout in a kit run:** stop all strategy work; fix or revert
  to the last tag; this outranks everything (playbook: fix first).
- **A change didn't improve average points locally:** revert it, resubmit the
  previous version. Never debug a regression under the clock.
- **Minute 18 and the adapter still doesn't run:** strip it — hardcode the
  simplest state mapping that makes `decide` run on preflop-only info
  (`hole`, stacks, blinds, legal actions); postflop falls back to
  check/fold via the safety wrapper. Ugly and alive beats elegant and absent.
- **Hopelessly broken at 20:** submit the check-fold `fallback` wired directly
  into the Agent — it is legal, instant, and scores above crashing bots —
  then rebuild calmly for the minute-35 window.

## Contingency rows (from the playbook, with our file names)

| Twist | A does | B does |
| --- | --- | --- |
| Short deck / new rankings | `tables/variant.py` modeled on `tables/shortdeck.py`; regen at 10k | nothing extra |
| 3+ hole cards / Omaha-style | regen with `HOLE_COUNT`; rank must enforce combination rules; if classes explode, 5k samples | check hole-card array handling in adapter |
| Antes | nothing (pot math flows through `pot`/`to_call`) | confirm antes appear in `pot` |
| Bounties | loosen calls vs short-stack shoves: lower the short-mode call margin in `strategy.py` | confirm bounty events exist |
| Pot-limit / fixed-limit | nothing — clamp obeys `min_raise`/`max_raise` | make sure kit's max reaches `max_raise` |
| Winner-take-all payouts | ICM gate auto-degrades (one cliff at 1st); widen endgame shoves if time | nothing |
| Flat payouts | nothing — cliff logic and `_cap_fold` handle it; expect many fold-outs | nothing |

## Command crib

```sh
python -m unittest discover -s tests                 # 30 s sanity
python -m tables.gen_equity --workers 6              # standard regen, ~10 s
python -m tables.gen_equity --variant tables.variant --samples 10000 --workers 6 --output tables/equity_variant.json
python -m tables.pushfold                            # rebuild push/fold JSON
python -m sim.run --tables 200                       # our sim (kit sim is authoritative)
python -m benchmarks.policy --load                   # timing under load
git checkout known-good-v2 -- bot tables             # restore pre-event verified state
```
