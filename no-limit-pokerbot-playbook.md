# No Limit Pokerbot Playbook

As of 2026-11-03

The thesis: this is a survival tournament, not a solver contest. Game theory and Monte Carlo cannot run in 1 ms, so the bot plays precomputed, tight, ICM-aware poker that changes mode as the blinds climb, and lets the field eliminate itself.

---

## Rules reference (keep open during the event)

From the official rules (https://pokerbot.sequoiacap.com/rules.html), sections 3-5. These numbers are fixed; the variant and the payout table arrive at the start of the build phase.

| Rule | Value |
| --- | --- |
| Build phase | 60 minutes, Python, provided `Agent` interface |
| Starter kit | agent template, local simulator, ICM calculator, payout structure, blind schedule |
| AI tools during build | Astra and Codex allowed; no live gameplay decisions by AI |
| Submission cadence | one bot per 5 minutes; latest accepted bot is active |
| Sandbox | no network, no external APIs |
| Decision time limit | 1 ms; error or timeout = auto fold, or check if available |
| File size limit | 100 MB |
| State | resets at the start of each table; opponents anonymized |
| Table | 8 bots, 2,000 chips each, until one bot has all chips or 200 hands |
| Blinds | start 10/20, increase every 25 hands |
| Scoring | points by finishing position; ICM splits remaining points at the 200-hand cap |
| Tournaments | T1-T6, 10,000 tables each, 20 minutes apart, weights 1 through 6 |
| Filler bots | fill seats when the field is not divisible by 8; earn no points |
| Advancement | top 5 per regional advance ($5,000 each) plus up to 5 wildcards; finals pay $100K / $50K / $25K |

How the game changes as hands go by, assuming blinds double each level and the average stack stays near 2,000 (confirm against the kit's blind schedule on the day):

| Hands | Blinds | Average stack in BB | Bot mode |
| --- | --- | --- | --- |
| 1-25 | 10/20 | 100 | Deep: tight, value only, no bluffs |
| 26-50 | 20/40 | 50 | Deep |
| 51-75 | 40/80 | 25 | Middle: raise or fold |
| 76-100 | 80/160 | 12.5 | Short: push/fold begins |
| 101-125 | 160/320 | 6 | Short: shove-first, ICM cliffs dominate |
| 126-150 | 320/640 | 3 | Any-two-cards territory; most tables end here |
| 151-200 | 640/1280 and up | under 2 | Endgame or cap; ICM fold-out logic |

If the blinds rise more gently than doubling, every row shifts later but the order of modes is the same. The point is that the strategy is a function of hand number and stack, never a single fixed style.

---

## What the format rewards

This is a survival game scored by finishing position, not a chip-winning game. Every design choice below follows from that.

| Rule | What it means for the bot |
| --- | --- |
| 8-bot sit-and-gos, 10,000 per scored tournament | Variance washes out. A small, consistent edge compounds; gambling does not. |
| Points by finishing position, ICM at the 200-hand cap | Outlasting bots beats stacking chips. 2nd-4th every table is worth more than 1st or 8th. |
| 2,000 chips, blinds 10/20, up every 25 hands | Starts at 100 BB but hits push/fold depth (under 12 BB) within roughly 75-100 hands. Half the match is short-stack poker. |
| 1 ms per decision, else auto fold/check | No live simulation. Everything is lookup tables and arithmetic. |
| Variant secret until the build phase | Prepare variant-independent machinery; keep variant-specific pieces regenerable in minutes. |
| State resets per table, opponents anonymized | Reads only last 200 hands. Modeling must be cheap and fast to converge. |
| Six tournaments T1-T6, weighted 1x to 6x | T6 alone is worth 29% of the score. A safe T1 bot, then improve every 20 minutes. |
| Resubmit every 5 minutes, latest accepted bot is active | Never submit something untested as the active bot right before a tournament freezes. |

The hand-by-hand schedule in the rules reference above is the clock the bot runs on: deep for roughly the first 50 hands, raise-or-fold through hand 75, push/fold from about hand 76 onward.

---

## Pre-event prep (build and test this week)

Walk in with a tested skeleton and data files, so the 60 minutes is assembly, not authorship. Everything here is variant-independent or regenerable from a script.

- [ ] **Equity table generator.** A script that takes a deck definition and hand-ranking function and outputs equity for every starting-hand class vs 1, 2, 4, and 7 random opponents. Run it now for standard hold'em (169 classes) and save the result as a plain dict. Target: regenerate a new table in under 5 minutes if the variant changes the deck or rankings.
- [ ] **Push/fold table.** Shove and call ranges keyed on (effective stack in BB, players left to act, position). Build from published Nash push/fold charts, tightened about 10% for 8-handed play and loosened when the ICM pressure is on others. Store as a dict of hand class -> minimum stack to shove.
- [ ] **Fast postflop evaluator.** `eval7` (or `treys` as fallback) wrapped with a small feature extractor: made-hand category, flush draw flag, open-ended/gutshot straight draw flags, board paired, board monotone, number of overcards. Benchmark every path under 0.3 ms on a slow laptop.
- [ ] **Local 8-player SNG simulator.** Matches the real structure: 2,000 chips, 10/20 blinds up every 25 hands, 200-hand cap, ICM split at the cap, 8 seats, random seating. Output: average points per table and a finishing-position histogram over N tables.
- [ ] **Dummy opponent bots.** Random, always-call, always-raise, tight-passive, loose-aggressive, naive push/fold, and your own previous versions. Your bot must beat every one of them on average points before the event.
- [ ] **Safety wrapper.** Try/except around the whole decision, action-legality check against what the engine allows, hard fallback to check-else-fold, and a timing assert in tests. This file should not change on the day.
- [ ] **Per-table opponent tracker.** A tiny class per seat: hands dealt, voluntarily put chips in, preflop raises, folds to raise, times reached showdown. Resets with table state.
- [ ] **ICM helper.** Your own ICM-equity function, so you can compare against the kit's calculator and so the logic exists before you see their interface.
- [ ] **Interface adapter stub.** A single file that maps your bot's internal `decide(state) -> action` to whatever `Agent` interface they hand you. On the day you rewrite only this file.
- [ ] **Dry run.** Do a full 60-minute mock build with a made-up variant (for example, hold'em with a 36-card short deck) to find what is slow to adapt. Fix that before the event.
- [ ] **Tooling.** Codex account working, Python environment with `eval7` installed and import-tested, a timer script, and the code in a repo both teammates can pull.

---

## Bot architecture

Every decision runs top to bottom through the pipeline, pulling from tables loaded once at import; the safety wrapper catches anything that breaks and the clamp guarantees a legal action.

```
SAFETY WRAPPER: try/except, fallback = check else fold
+-------------------------------------------------+      LOADED ONCE AT IMPORT
|  1. Game state in                               |
|     hole cards, board, stacks, blinds, seat,    |
|     legal actions, hand number                  |
|              |                                  |
|              v                                  |
|  2. Mode select by effective stack (BB)         | <--  Push/fold table
|     over 30 deep, 15-30 middle,                 |      hand class -> min stack to shove,
|     under 15: push/fold table                   |      by position and players left to act
|              |                                  |
|              v                                  |
|  3. Hand strength                               | <--  Equity tables
|     preflop: equity table lookup                |      169 hand classes vs 1, 2, 4, 7 opponents
|     postflop: eval7 + draw and board flags      |      regenerated if the deck changes
|              |                                  |
|              v                                  |
|  4. Opponent adjust                             | <--  Opponent priors
|     per-seat VPIP, PFR, fold-to-raise           |      population defaults, k = 15 hands
|     shift bet, call and steal thresholds        |      tuned between tournaments
|              |                                  |
|              v                                  |
|  5. ICM check, big pots only                    | <--  Payout table + blind schedule
|     points if fold vs points if win or lose     |      cliff positions, BB by hand number
|     tighten near the payout cliff               |      from the starter kit
|              |                                  |
|              v                                  |
|  6. LEGALITY CLAMP, THEN RETURN                 |
|     min raise, max stack, legal action set      |
|     any error or timeout: check, else fold      |
+-------------------------------------------------+
```

Timing budget of the 1 ms: equity lookup under 0.01 ms, eval7 on a 7-card hand about 0.02 ms, feature flags under 0.05 ms, ICM recursion for 8 stacks under 0.1 ms with memoization. Total worst case well under 0.3 ms, leaving room for sandbox overhead.

Suggested files: `tables.py` (loads the dicts), `strength.py` (preflop and postflop), `tracker.py` (per-seat counters), `icm.py`, `strategy.py` (modes and thresholds), `agent.py` (interface adapter plus the safety wrapper). Only `agent.py` and `tables.py` should change on the day.

---

## Strategy by phase

The bot switches modes on effective stack in big blinds, not on hand number. Each mode is simple enough to run in microseconds.

### Deep (over 30 BB, roughly hands 1-50)

Play tight, value-heavy, and never bluff. Most student bots are loose and will bust each other; your job is to not be at the crash site.

- Open-raise 2.5x with the top ~12% from early position, ~18% middle, ~25% cutoff/button, ~35% small blind vs an unopened pot. Use the equity table vs the number of players behind to set the cutoff.
- Facing a raise: call only with hands that flop well (pairs, suited broadways, suited connectors) if the raise is under 4 BB. 3-bet premiums (QQ+, AK). Fold the rest.
- Postflop: bet 60% pot with top pair or better, check-call with medium strength, fold weak hands to any bet larger than 50% pot. No bluffs, no semi-bluffs until you have reads.
- Never call an all-in without a top ~5% hand or a very strong made hand. All-ins at 100 BB from student bots are overwhelmingly real.

### Middle (15-30 BB, roughly hands 51-75)

Raise or fold, almost never call. Shrink opens to 2.2x. Add a 3-bet-shove with premiums and strong aces over any open. Fold marginal hands out of position. Steal from the button and small blind when the blinds have been folding.

### Short (under 15 BB, roughly hand 76 onward)

Pure push/fold from the table, with the ICM layer applied on top. This is where most of your edge lives, because many bots blind out, limp, or shove junk.

- Shove ranges widen as players left to act shrink and as your stack shrinks. First-in from the button at 8 BB is roughly the top 45% of hands; from under the gun at 8 BB it is roughly the top 15%.
- Calling a shove requires more than the shover's range implies: use the equity table vs 1 opponent and require at least 5 points above the pot-odds breakeven, more near a points cliff.
- Under 5 BB, shove any hand with decent equity first-in; folding to the big blind costs too much.

### Endgame (3-4 bots left, or under 25 hands to the cap)

Read the stack map. Big stack: shove on every medium stack that cannot call without risking a points drop. Medium stack: fold to the big stack, shove on the short stacks. Short stack: pick the first hand above the shove threshold and go; waiting is losing.

### Heads-up (2 left)

Only matters if the point gap between 1st and 2nd is large. If it is, shove or fold with a wide range on the button, call shoves with any hand above 40% equity. If the gap is small, prefer a quiet fold-to-cap if you are ahead in chips.

---

## ICM layer

Every decision that risks more than 25% of your stack goes through an ICM check: compare your tournament equity (in points) if you fold against the equity-weighted average of winning and losing the pot. Chips are not points; losing 1,000 chips costs far more than winning 1,000 gains.

- **Points cliffs.** The payout table is announced at the start of the build phase. Find where the jump between adjacent positions is largest; that is the bubble. One or two players before that cliff, raise the equity required for any call by 10-15 points and shove only with hands near the top of the table.
- **Big stack leverage.** When you hold more than 1.5x the next stack and others are near a cliff, shove into medium stacks with the top ~50% of hands. They cannot call correctly; the ICM math forces them to fold.
- **Medium stack discipline.** With a short stack at the table, fold almost everything to the big stack. Let the short stack bust first.
- **Short stack urgency.** Below 7 BB, ICM says shove earlier than chip-EV, because the blinds will take the decision from you.
- **200-hand cap.** From hand 170 onward, compute your ICM share of the remaining points at the cap. If folding every remaining hand (losing only blinds) keeps you at or above that share, fold out. If you are far behind, loosen: a fold to the cap locks in a weak finish.
- **Filler bots.** Seats filled by copies of submitted bots earn no points but still play. Treat them like any opponent; the only effect is that busting one changes nothing about your points except via position.

Implementation: precompute nothing here; ICM for 8 stacks is a fast recursion (under 0.1 ms with memoization for small tables), and the kit ships a calculator. Call it only on large decisions to stay well under the 1 ms budget.

---

## Opponent modeling (per table, 200 hands max)

Keep five counters per seat and three rules. Anything fancier will not converge in 200 hands and risks the time limit.

| Counter | What it tells you | Usable after |
| --- | --- | --- |
| VPIP (voluntarily put chips in / hands dealt) | How loose they are | ~20 hands |
| PFR (preflop raises / hands dealt) | How aggressive they are | ~20 hands |
| Fold-to-raise (folds when facing a raise / times facing a raise) | Whether stealing works | ~10 raises faced |
| Shove count / hands dealt in short-stack play | Whether their shoves are wide | ~10 hands |
| Showdown hands seen (strength of hands they shoved or called with) | Calibrates the above | any |

Rules, applied with a prior so early reads are muted:

1. **Calling station (VPIP over 45%, fold-to-raise under 40%):** never bluff or steal; value-bet thinner (top pair is a bet on every street); shove on them only with hands that beat a wide calling range.
2. **Folder (fold-to-raise over 70%):** open and shove on them relentlessly from late position; min-raise when deep, shove when short. This is free points.
3. **Maniac (PFR over 35%):** tighten calls slightly but call their shoves with a wider range than the default table, since their range is wide. Trap with premiums instead of 3-betting.

Use a Bayesian-style blend: `estimate = (prior * k + observed * n) / (k + n)` with k around 15 hands, so the bot starts at the population default and drifts toward the real read. Default archetype for an unknown seat: slightly loose, slightly passive, which matches most student bots.

Between tournaments, you can tune the priors from the hand logs the organizers retain: if the field is foldier than expected, lower the prior for fold-to-raise and the bot will steal more from hand one.

---

## The 60-minute build

Submit a working bot by minute 20, then improve. The first tournament freezes at minute 60; a bot that works and folds a lot beats a bot that is clever and crashes.

1. **0-5: Read.** Both teammates read the variant announcement and the `Agent` interface. One writes down every rule difference from standard hold'em (deck, hand rankings, number of hole cards, betting structure, payouts). The other reads the starter kit's simulator and ICM calculator APIs.
2. **5-15: Adapt the data.** If hand rankings or the deck changed, run the equity generator for the new variant (budget: 5 minutes). Teammate A does this. Teammate B rewrites the interface adapter so `decide(state)` receives stack sizes, position, blinds, hand number, legal actions, and the opponent tracker.
3. **15-20: Smoke test and submit.** Run 200 tables in the kit's simulator. Confirm zero errors, zero timeouts, and a finishing-position histogram that is not all 8th place. Submit. This is your T1 floor.
4. **20-35: Push/fold and ICM.** Wire the push/fold table to the real blind schedule and payout table. Set the cliff positions from the payouts. Run 1,000 tables, check average points rose. Submit at minute 35.
5. **35-50: Opponent tracker and sizing.** Enable the three archetype rules. Tune bet sizing for the variant (bigger on wet boards, smaller on dry). Run 1,000 tables. Submit at minute 50 only if points rose; otherwise keep the minute-35 bot active.
6. **50-60: Freeze discipline.** No new features. Re-run the timing benchmark under load, re-run error checks, read through the decision function once for any path that could return an illegal action. Confirm which submission is active before minute 60.

Roles for a team of two: one owns data and strategy (tables, ICM, push/fold), the other owns plumbing and safety (interface, simulator runs, timing, submission). Do not swap mid-build.

Codex is allowed during the build; use it for the adapter rewrite and for generating test harness code, not for the strategy core you already tested at home.

---

## T1 to T6: the iteration loop

You get five 20-minute windows between tournaments, and the later ones are worth more. T4-T6 together are 71% of the final score. Spend the first windows learning about the field and the last windows locking in.

After each tournament, pull your finishing-position histogram and the hand logs, and diagnose:

| Symptom | Likely cause | Change |
| --- | --- | --- |
| Many 7th-8th finishes before hand 50 | Too loose deep, or calling all-ins | Tighten the deep-stack open ranges; raise the all-in call threshold |
| Many 4th-6th, few top-3 | Blinding out, push/fold too tight | Widen shove ranges in late position; lower the shove threshold at under 7 BB |
| Many 2nd-3rd, few 1st | Too passive heads-up and 3-handed | Widen the endgame shove range; add big-stack bullying |
| Timeouts or errors in the logs | A slow or crashing path | Fix first, before any strategy change |
| Points per table rose but position spread widened | More variance | Acceptable only if average rose; otherwise revert |

Window plan:

- **After T1 (weight 1):** fix anything broken. Read the field: average VPIP and fold-to-raise across opponents. Set the opponent priors to match. Submit.
- **After T2 (weight 2):** the biggest strategy change you are willing to make, tested on 1,000 local tables first.
- **After T3 (weight 3):** tune push/fold and ICM cliffs against the observed field. This is usually the highest-value window.
- **After T4 (weight 4):** small, tested improvements only. A/B against the previous bot locally; keep the winner.
- **After T5 (weight 5):** freeze unless something is broken. T6 is worth 6 of 21 weight units; a regression here is unrecoverable.

Always keep the last known-good bot's file saved under a version name. If a local run shows a regression, resubmit the known-good version rather than debug under the clock.

---

## Variant contingencies

The variant is secret, but the site's demos all show no-limit hold'em with blinds, so expect a hold'em-family twist rather than a different game. Prepare for these and you cover most of the space.

| Possible twist | What breaks | Fix on the day |
| --- | --- | --- |
| Short deck (36 cards, 6+) | Equities, hand rankings (flush beats full house, A-6-7-8-9 straight) | Regenerate the equity table with the new deck and ranking function; raise the value of suited and connected hands |
| Extra hole cards (3-card or Omaha-style) | Preflop classes, evaluator input | Generator must accept N hole cards; evaluator must pick best 5 from the combination rules; fall back to a looser deep-stack strategy if equities are not ready |
| Bounties on eliminations | Points logic | Add bounty value to the ICM check: calling a short stack's shove is worth more; loosen calls vs short stacks |
| Antes | Pot odds, steal value | Raise the open and shove frequencies; the pot is bigger before any action |
| Wild cards or a community-card change | Hand rankings, evaluator | Generator must accept a custom ranking function; worst case, play tighter and lean on push/fold |
| Non-standard payout structure (winner-take-all or flat) | Where the cliffs are | Winner-take-all: play for chips, ignore ICM. Flat: play ultra-tight for survival. The payout table decides this in the first 5 minutes |
| Different betting structure (pot-limit, fixed-limit) | Bet sizing, all-in logic | Clamp sizes to legal maximums; in limit games, value-bet more and never fold to a single bet with a draw |

The common thread: the equity generator must take the deck, hole-card count, and ranking function as parameters, and the decision function must only ever consult tables plus a handful of thresholds. If both hold, any twist is a data regeneration, not a rewrite.

---

## Failure checklist

Most bots in these events lose on engineering, not poker. Run this list before every submission.

- [ ] Decision returns in under 0.5 ms on the slowest path (a full postflop evaluation with ICM), measured on your laptop with other processes running.
- [ ] No imports or table loads happen inside the decision function; everything loads once at module import.
- [ ] No network calls, file writes, or logging to disk in the submitted bot (the sandbox has no network and logging can be slow).
- [ ] Every return value is a legal action for the current state: never raise below the minimum, never bet more than your stack, never check when a call is required.
- [ ] Any exception anywhere inside `decide` is caught and returns check-else-fold.
- [ ] The bot handles hand number 1 with no history, and seat counts from 2 to 8, without division by zero.
- [ ] State resets correctly at the start of each table; no stale reads from a previous table.
- [ ] All-in and side-pot situations do not crash the postflop logic.
- [ ] The submitted file is under 100 MB (equity tables as dicts are tiny; do not ship pickled models you do not need).
- [ ] The active submission is the one you intended; check the platform's confirmation before each tournament freeze.
- [ ] A copy of the last known-good bot is saved and resubmittable in under 2 minutes.

---

## Sources

- Official rules: https://pokerbot.sequoiacap.com/rules.html
- Event page: https://pokerbot.sequoiacap.com
