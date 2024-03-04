from typing import Self, NamedTuple

import re

from operator import itemgetter

from ..langs import Language


class Query(NamedTuple):
    language: Language
    syntax: str


class Match(NamedTuple):
    path: str
    range: 'Range'

    RE = re.compile(r'(.*):(\d+):(\d+)-(\d+):(\d+)\n')

    @classmethod
    def parse(cls, line: str) -> Self:
        match = cls.RE.fullmatch(line)
        assert match, 'unexpected line formatting'
        path, *offsets = itemgetter(*range(1, 6))(match)  # type: ignore
        sr, sc, er, ec = map(int, offsets)
        return cls(path, Range(sr, sc, er, ec))

    def __str__(self) -> str:
        return f'{self.path}:{self.range}'


class Range(NamedTuple):
    sr: int
    sc: int
    er: int
    ec: int

    def __str__(self) -> str:
        return f'{self.sr}:{self.sc}-{self.er}:{self.ec}'
