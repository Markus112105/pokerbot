"""Exact independent-chip-model finish equities, including zero-stack ties.

Subset inclusion-exclusion aggregates all finishing orders in O(n * 2**n).
The bounded memo stores complete results; payouts need not sum to one.
"""
from functools import lru_cache
from math import comb


@lru_cache(maxsize=16)
def _layout(n):
    return tuple(tuple((i, mask | (1 << i)) for i in range(n)
                       if not mask & (1 << i)) for mask in range(1 << n))


@lru_cache(maxsize=8192)
def _equity(stacks, payouts):
    n = len(stacks)
    total = sum(stacks)
    if not total:
        return (sum(payouts) / n,) * n
    positive = tuple(i for i, s in enumerate(stacks) if s > 0)
    if len(positive) < n:
        live = _equity(tuple(stacks[i] for i in positive), payouts[:len(positive)])
        dead = sum(payouts[len(positive):]) / (n - len(positive))
        result = [dead] * n
        for i, value in zip(positive, live):
            result[i] = value
        return tuple(result)
    size = 1 << n
    sums = [0] * size
    coefficients = _coefficients(payouts)
    layout = _layout(n)
    result = [0.0] * n
    for mask in range(1, size):
        bit = mask & -mask
        sums[mask] = sums[mask ^ bit] + stacks[bit.bit_length() - 1]
        coefficient = coefficients[mask.bit_count() - 1]
        if not coefficient:
            continue
        factor = coefficient / sums[mask]
        for i, _ in layout[size - 1 - mask]:
            result[i] += factor * stacks[i]
    return tuple(result)


def equity(stacks, payouts):
    """Return each seat's points; pad missing prizes with zero, at most 8 seats."""
    stacks = tuple(stacks)
    payouts = tuple(payouts)
    if not 1 <= len(stacks) <= 8 or any(s < 0 for s in stacks):
        raise ValueError('Expected one to eight nonnegative stacks')
    if any(p < 0 for p in payouts):
        raise ValueError('Payouts must be nonnegative')
    return _equity(stacks, (payouts + (0,) * len(stacks))[:len(stacks)])


@lru_cache(maxsize=128)
def _coefficients(payouts):
    n = len(payouts)
    return tuple(sum((-1)**j * comb(q, j) * payouts[n - 1 - q + j]
                     for j in range(q + 1)) for q in range(n))


@lru_cache(maxsize=32768)
def hero_equity(stacks, payouts, hero):
    """Exact one-seat ICM via exponential races and inclusion-exclusion.

Each subset contributes a finite difference of rank prizes times the chance
hero wins that subset's exponential race. At eight seats there are 128 terms.
Used for large decisions to avoid calculating seven unneeded seat equities.
"""
    n = len(stacks)
    payouts = (payouts + (0,) * n)[:n]
    if not stacks[hero] or any(s == 0 for s in stacks):
        return equity(stacks, payouts)[hero]
    others = stacks[:hero] + stacks[hero + 1:]
    sums = [0] * (1 << len(others))
    coefficients = _coefficients(payouts)
    value = coefficients[0]
    own = stacks[hero]
    for mask in range(1, len(sums)):
        bit = mask & -mask
        sums[mask] = sums[mask ^ bit] + others[bit.bit_length() - 1]
        value += coefficients[mask.bit_count()] * own / (own + sums[mask])
    return value


def reset_cache():
    """Discard table-specific memo entries so old states do not burden GC."""
    _equity.cache_clear()
    hero_equity.cache_clear()
