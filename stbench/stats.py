from typing import Iterable, TypeVar, Collection, Callable

from statistics import mean, stdev, quantiles


T = TypeVar('T')


tail_pi = 99


def stats(name: str, data: Collection[T], proj: Callable[[T], float], units: str) -> str:
    vs = list(map(proj, data))
    return '\n- '.join([
        name,
        f'mean\t{mean(vs):.2f}±{stdev(vs):.2f} {units}',
        f'{tail_pi}pi\t{percentiles(vs)[tail_pi - 1]:.2f} {units}',
        f'max\t{max(vs)} {units}',
    ])


def percentiles(it: Iterable[float]) -> list[float]:
    return quantiles(it, n=100)
