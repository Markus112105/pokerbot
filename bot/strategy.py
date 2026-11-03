"""Offline phase policy. Equity versus random cards is a range proxy, not a solver.

Large bets compare three chip-conserving ICM scenarios against one covering
opponent. Multiway pots and unknown calling ranges make that an approximation.
No live enumeration, imports, clocks, I/O, or table loads occur in decide.
"""
import random
from bot import strength
from bot.icm import equity, hero_equity
from tables.pushfold import lookup

RNG = random.Random(731_917)


def mode(bb):
    return 'deep' if bb > 30 else 'middle' if bb >= 15 else 'short'


def _cap_fold(s):
    """Project forced blinds with fixed survivors and transfer chips to opponents.

Compare projected ICM with current ICM, not chip rank. This conservative test
rarely fires: folding generally loses equity. It cannot predict others busting.
"""
    if s['hand_number'] < 170:
        return False
    active, hero = s['active'], s['seat']
    stacks = [s['stacks'][i] for i in active]
    h = active.index(hero)
    current = equity(stacks, s['payouts'])[h]
    # Current hand's escrow goes to the largest rival when we abandon it.
    rival = max((i for i in range(len(stacks)) if i != h), key=stacks.__getitem__)
    stacks[rival] += s['pot']
    button = active.index(s['button'])
    schedule = s.get('blind_schedule', [(10 * 2**i, 20 * 2**i) for i in range(8)])
    for hand in range(s['hand_number'] + 1, s.get('cap', 200) + 1):
        button = (button + 1) % len(active)
        sb, bb = schedule[min((hand - 1) // 25, len(schedule) - 1)]
        sb_seat = button if len(active) == 2 else (button + 1) % len(active)
        bb_seat = (sb_seat + 1) % len(active)
        cost = min(stacks[h], sb if h == sb_seat else bb if h == bb_seat else 0)
        stacks[h] -= cost
        stacks[rival] += cost
    return equity(stacks, s['payouts'])[h] >= current - 1e-9


def _icm_allows(s, risk, win_probability, raising):
    hero, active = s['seat'], s['active']
    h = active.index(hero)
    rivals = [i for i in s['in_hand'] if i != hero]
    if not rivals:
        return True
    villain = s.get('aggressor')
    if villain not in rivals:
        villain = max(rivals, key=lambda i: s['stacks'][i])
    v = active.index(villain)
    base = [s['stacks'][i] for i in active]
    # Unmatched chips are returned; only the callable part is at risk.
    coverage = s['stacks'][villain] + s['street_bets'][villain] - s['street_bets'][hero]
    risk = max(0, min(risk, coverage))
    extra = max(0, risk + s['street_bets'][hero] - s['street_bets'][villain])
    extra = min(extra, base[v])
    folded = base.copy()
    folded[v] += s['pot']
    won = base.copy()
    won[h] += s['pot'] + extra
    won[v] -= extra
    lost = base.copy()
    lost[h] -= risk
    lost[v] += risk + s['pot']
    values = s['payouts'][:len(active)]
    fold_value = hero_equity(tuple(folded), tuple(values), h)
    called_value = win_probability * hero_equity(tuple(won), tuple(values), h) + (1 - win_probability) * hero_equity(tuple(lost), tuple(values), h)
    if raising:
        tracker = s.get('tracker')
        fold_prob = 1.0
        for i in rivals:
            fold_prob *= tracker.estimate(i, 'fold') if tracker else .5
        uncontested = base.copy()
        uncontested[h] += s['pot']
        called_value = fold_prob * hero_equity(tuple(uncontested), tuple(values), h) + (1 - fold_prob) * called_value
    return called_value >= fold_value


def decide(s):
    hero = s['seat']
    stack = s['stacks'][hero]
    to_call, pot = s['to_call'], s['pot']
    passive = {'type': 'check' if 'check' in s['legal_actions'] else 'fold'}
    if stack <= 0 or _cap_fold(s):
        return passive
    depth = s['effective_stack'] / s['bb']
    phase = mode(depth)
    preflop = not s['board']
    opponents = max(1, len(s['in_hand']) - 1)
    behind = max(1, min(7, s['players_left_to_act']))
    eq = strength.preflop(s['hole'], 1)
    percentile = strength.percentile(s['hole'], behind)
    tracker = s.get('tracker')
    villain = s.get('aggressor')
    rival_seats = [i for i in s['in_hand'] if i != hero]
    if villain not in rival_seats:
        villain = rival_seats[0] if rival_seats else hero
    fold_rate = tracker.estimate(villain, 'fold') if tracker else .5
    vpip = tracker.estimate(villain, 'vpip') if tracker else .32
    pfr = tracker.estimate(villain, 'pfr') if tracker else .15
    station, folder, maniac = vpip > .45 and fold_rate < .4, fold_rate > .7, pfr > .35
    raised = s['current_bet'] > s['bb'] if preflop else to_call > 0
    hand = strength.hand_class(s['hole'])
    premium = hand in ('AA', 'KK', 'QQ', 'AKs', 'AKo')
    action = passive
    win_probability = max(.05, eq - (.06 if raised and not maniac else .02))
    if preflop and tracker:
        # A quiet limp can still represent a premium range. Use observed hand
        # participation, never a dummy identity, to discount random-card equity.
        tight_limpers = sum('vpip' in tracker.seats[i].seen and tracker.estimate(i, 'vpip') < .30
                            for i in rival_seats)
        if tight_limpers:
            win_probability = max(.05, win_probability - .12 - .04 * (tight_limpers - 1))
    if preflop and phase == 'short':
        table = lookup(hand, max(2, min(15, depth)), behind, s['position'])
        if raised:
            odds = to_call / max(1, pot + to_call)
            margin = .03 if maniac else .05
            gaps = [a - b for a, b in zip(s['payouts'], s['payouts'][1:])]
            cliff = gaps.index(max(gaps)) + 1 if gaps else 1
            if cliff < len(s['active']) <= cliff + 2:
                margin += .10
            if len(s['active']) == 2:
                allowed = eq > .40 and eq > odds + margin
            else:
                allowed = (table['call'] or (maniac and percentile < .30)) and eq > odds + margin
            if allowed:
                action = {'type': 'call'}
        elif table['shove'] or (depth < 5 and eq > .43) or (depth < 7 and eq > .50) or (folder and s['position'] in ('late', 'sb') and not station):
            action = {'type': 'raise', 'amount': s['max_raise']}
        if not raised and not station and len(s['active']) >= 3:
            other_stacks = [s['stacks'][i] for i in s['active'] if i != hero]
            gaps = [a - b for a, b in zip(s['payouts'], s['payouts'][1:])]
            cliff = gaps.index(max(gaps)) + 1 if gaps else 1
            if (stack > 1.5 * max(other_stacks) and cliff < len(s['active']) <= cliff + 2
                    and percentile < .50):
                action = {'type': 'raise', 'amount': s['max_raise']}
    elif preflop:
        if not raised:
            cutoff = {'early': .12, 'middle': .18, 'late': .25, 'sb': .35, 'bb': .35}[s['position']]
            if len(s['active']) == 2:
                cutoff = .65
            if folder and s['position'] in ('late', 'sb'):
                cutoff = max(cutoff, .55)
            if percentile <= cutoff:
                multiple = 2 if folder else 2.5 if phase == 'deep' else 2.2
                action = {'type': 'raise', 'amount': int(multiple * s['bb'])}
        elif premium or (phase == 'middle' and hand in ('AQs', 'AQo', 'AJs', 'JJ', 'TT')):
            if maniac and phase == 'deep' and to_call < stack * .25:
                action = {'type': 'call'}
            else:
                action = {'type': 'raise', 'amount': s['max_raise'] if phase == 'middle' else max(s['min_raise'], 3 * s['current_bet'])}
        elif phase == 'deep' and s['current_bet'] < 4 * s['bb']:
            ranks = '23456789TJQKA'
            pair = len(hand) == 2
            suited = hand.endswith('s')
            playable = pair or (suited and (min(ranks.index(hand[0]), ranks.index(hand[1])) >= 8 or abs(ranks.index(hand[0]) - ranks.index(hand[1])) == 1))
            if playable:
                action = {'type': 'call'}
    else:
        f = strength.evaluate(s['hole'], s['board'])
        strong = not f.board_only and (f.category >= 2 or f.top_pair)
        # Made-hand estimates are intentionally conservative in multiway pots.
        win_probability = max(.05, min(.97, (.90 if f.category >= 4 else .78 if f.category >= 2 else .66 if f.top_pair else .43 if f.category else .22) - .07 * (opponents - 1)))
        if strong:
            if to_call >= stack * .8 and f.category < 2 and phase == 'deep':
                return passive
            if to_call and win_probability > to_call / max(1, pot + to_call) + .08:
                action = {'type': 'call'}
            elif not to_call:
                action = {'type': 'raise', 'amount': s['street_bets'][hero] + int(pot * RNG.uniform(.55, .75))}
        elif to_call <= pot * .5 and f.category >= 1 and not f.board_only and phase == 'deep':
            action = {'type': 'call'} if to_call else passive
        elif not to_call and phase != 'deep' and folder and not station:
            action = {'type': 'raise', 'amount': s['street_bets'][hero] + int(pot * RNG.uniform(.55, .75))}
    if action['type'] == 'raise':
        if 'raise' not in s['legal_actions']:
            action = {'type': 'call'} if 'call' in s['legal_actions'] else passive
        else:
            action['amount'] = min(s['max_raise'], max(min(s['min_raise'], s['max_raise']), action['amount']))
    risk = min(stack, to_call if action['type'] == 'call' else max(0, action.get('amount', 0) - s['street_bets'][hero]))
    if risk > .25 * stack and raised and len(s['active']) >= 3 and percentile > .05:
        # Preserve a medium stack while a much shorter stack faces elimination.
        others = [s['stacks'][i] for i in s['active'] if i != hero]
        if s['stacks'][villain] > 1.5 * stack and min(others) < stack * .35:
            return passive
    if risk > .25 * stack and not _icm_allows(s, risk, win_probability, action['type'] == 'raise'):
        return passive
    return action
