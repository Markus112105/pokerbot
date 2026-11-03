"""Cold/warm 8-seat ICM and full postflop + ICM decision timing assertions.

Use --load to add two CPU workers, approximating other busy local processes.
Wall-clock maxima are printed separately; the OS can preempt any Python call.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import random
from time import perf_counter_ns, monotonic

from bot.agent import Agent
from bot.icm import equity, reset_cache


def load(seconds):
    deadline = monotonic() + seconds
    value = 1
    while monotonic() < deadline:
        value = (value * 48271) % 2147483647
    return value


def summary(values):
    return {'p99_ms': sorted(values)[int(len(values)*.99)-1]/1e6,
            'max_ms': max(values)/1e6}


def measure():
    rng = random.Random(82)
    payouts = (10,7,5,3,2,1,0,0)
    cold, warm, decision = [], [], []
    reset_cache()
    for _ in range(1000):
        stacks = tuple(rng.randrange(100,4000) for _ in range(8))
        start = perf_counter_ns()
        equity(stacks,payouts)
        cold.append(perf_counter_ns()-start)
        start = perf_counter_ns()
        equity(stacks,payouts)
        warm.append(perf_counter_ns()-start)
    agent = Agent()
    agent.reset()
    for i in range(10000):
        stacks = tuple(rng.randrange(1000,4000) for _ in range(8))
        state = dict(hole=('As','Ah'),board=('Ac','Kd','7h','2s'),
                     stacks=stacks, seat=0, active=tuple(range(8)),in_hand=(0,1),
                     street_bets=(0,)*8, total_contributions=(500,)*8,
                     pot=4000,to_call=0,current_bet=0,min_raise=20,
                     max_raise=stacks[0],legal_actions=('check','fold','raise'),
                     bb=20,sb=10,button=7,position='early',players_left_to_act=1,
                     hand_number=100,payouts=payouts,cap=200,
                     effective_stack=min(stacks[:2]),aggressor=None,street='turn')
        if i % 100 == 0:
            agent.reset()
        start = perf_counter_ns()
        agent.act(state)
        decision.append(perf_counter_ns()-start)
        assert agent.errors == 0
    result = {'icm_cold':summary(cold),'icm_cached':summary(warm),
              'postflop_with_icm':summary(decision)}
    print(json.dumps(result,indent=2))
    assert result['icm_cold']['p99_ms'] < .1, 'Cold ICM p99 exceeds 0.1 ms'
    assert result['icm_cached']['p99_ms'] < .1
    assert result['postflop_with_icm']['p99_ms'] < .5
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--load',action='store_true')
    args = parser.parse_args()
    if args.load:
        with ProcessPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(load,5) for _ in range(2)]
            measure()
    else:
        measure()
