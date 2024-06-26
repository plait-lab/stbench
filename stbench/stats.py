from typing import Iterable, TypeVar, Collection, Callable

from statistics import mean, median, stdev, quantiles


T = TypeVar('T')


tail_pi = 99


def stats(name: str, data: Iterable[float], units: str) -> str:
    vs = list(data)  # materialize values
    return '\n- '.join([
        name,
        f'n =\t{len(vs)}',
        f'med\t{median(vs)} {units}',
        f'mean\t{mean(vs):.2f}±{stdev(vs):.2f} {units}',
        f'{tail_pi}pi\t{quantiles(vs, n=100)[tail_pi - 1]:.2f} {units}',
        f'max\t{max(vs)} {units}',
    ])


def mmatrix(lhs: str, incl: int, both: int, excl: int, rhs: str) -> str:
    left, total, right = incl + both, incl + both - excl, both + excl
    incl_r, excl_r = 100 * incl / left, 100 * excl / right

    return '\n- '.join([
        f'matching matrix',
        f'{lhs}\t{left} total, {incl} ({incl_r:.2f}%) included',
        f'{rhs}\t{right} total, {excl} ({excl_r:.2f}%) excluded',
        f'joint\t{both} both, {total} overall'
    ])
