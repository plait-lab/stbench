#!/usr/bin/env python3

from typing import *

import math

from pathlib import Path
from dataclasses import dataclass, field
from csv import DictReader

from base import Args, Arg


@dataclass
class CLI(Args):
    results: TextIO = field(metadata=Arg(mode='r'))


def main(args: CLI):
    metrics = DictReader(args.results)

    patterns, files, times = {}, {}, {}

    for row in metrics:
        pattern, file = int(row['pattern']), Path(row['file'])
        fsize = file.stat().st_size

        qsize = int(row['query length']), int(row['hole count'])
        dsize = fsize, int(row['tree size']), int(row['tree depth'])
        time = int(row['parse time']), int(row['search time'])

        assert patterns.setdefault(pattern, qsize) == qsize
        assert files.setdefault(file, dsize) == dsize

        assert (pattern, file) not in times
        times[(pattern, file)] = time

    print('# SOURCE STATS')
    for i, tag in enumerate(['FILE SIZE', 'TREE SIZE', 'TREE DEPTH']):
        print(tag, Stats({k: v[i] for k, v in files.items()}), sep='\n')

    print('# PATTERN STATS')
    for i, tag in enumerate(['LENGTH', 'HOLES']):
        print(tag, Stats({k: v[i] for k, v in patterns.items()}), sep='\n')

    print('# TIMING STATS')
    for i, tag in enumerate(['PARSING', 'SEARCHING']):
        print(tag, Stats({k: v[i] for k, v in times.items()}), sep='\n')


T = TypeVar('T')


@dataclass
class Stats(Generic[T]):
    data: Mapping[T, int]

    @property
    def count(self) -> int:
        return len(self.data)

    @property
    def mean(self) -> int:
        return sum(self.data.values()) / len(self.data)

    @property
    def sd(self) -> float:
        mean = self.mean
        return math.sqrt(sum((x - mean)**2 for x in self.data.values())
                         / max(len(self.data) - 1, 1))

    def pi(self, p: int) -> int:
        return sorted(self.data.values())[math.ceil(p * len(self.data)) - 1]

    @property
    def max(self) -> tuple[T, int]:
        return max(self.data.items(), key=lambda p: p[1])

    @property
    def min(self) -> tuple[T, int]:
        return min(self.data.items(), key=lambda p: p[1])

    def __str__(self) -> str:
        return '\n'.join([
            f'\t  n =\t{self.count}',
            f'\tmean:\t{self.mean:.2f}',
            f'\t  sd:\t{self.sd:.2f}',
            f'percentiles',
            f'\t25th:\t{self.pi(.25):.2f}',
            f'\t50th:\t{self.pi(.50):.2f}',
            f'\t75th:\t{self.pi(.75):.2f}',
            f'\t99th:\t{self.pi(.99):.2f}',
            f'key values',
            *(
                f'\t{name}:\t{value} | {key}'
                for name, (key, value) in [
                    ('max', self.max),
                    ('min', self.min),
                ]
            )
        ])


if __name__ == '__main__':
    main(CLI.parser().parse_args())
