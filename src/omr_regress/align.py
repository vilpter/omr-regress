"""Align two staves' measures, so that one missed or extra barline costs one measure
instead of shifting every measure after it (Needleman-Wunsch, unit gap cost)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from omr_regress.measures import StaffMeasure

Pair = tuple[int | None, int | None]


def _cost(a: StaffMeasure, b: StaffMeasure) -> float:
    """0 for equal measures, up to 1 for measures with nothing in common."""
    if a == b:
        return 0.0
    ca, cb = Counter(a.events), Counter(b.events)
    total = sum(ca.values()) + sum(cb.values())
    if total == 0:
        return 0.5  # both empty, different headers
    common = sum((ca & cb).values())
    return max(0.1, 1.0 - 2 * common / total)


def align(a: Sequence[StaffMeasure], b: Sequence[StaffMeasure]) -> list[Pair]:
    """Pairs of indices (i in a, j in b), None where a measure has no counterpart."""
    n, m = len(a), len(b)
    if n == m and all(x == y for x, y in zip(a, b)):
        return [(i, i) for i in range(n)]
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = float(i)
    for j in range(1, m + 1):
        cost[0][j] = float(j)
    for i in range(1, n + 1):
        row, prev = cost[i], cost[i - 1]
        for j in range(1, m + 1):
            row[j] = min(prev[j - 1] + _cost(a[i - 1], b[j - 1]), prev[j] + 1.0, row[j - 1] + 1.0)
    pairs: list[Pair] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + _cost(a[i - 1], b[j - 1]):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1.0:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    pairs.reverse()
    return pairs
