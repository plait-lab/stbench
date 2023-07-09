from typing import *

import re

from pathlib import Path
from dataclasses import dataclass

from tools import db


@dataclass(frozen=True)
class Language:
    name: str

    # TODO: support more languages
    SUPPORT: ClassVar[list[str]] = [
        'javascript'
    ]

    ALIAS: ClassVar[dict[str, str]] = {
        'js': 'javascript',
    }

    EXTS: ClassVar[dict[str, list[str]]] = {
        'javascript': ['.js']
    }

    def __init__(self, name: str) -> None:
        assert self.supports(name)
        object.__setattr__(self, 'name', self._canonical(name))

    @classmethod
    def supports(cls, name: str) -> bool:
        return cls._canonical(name) in cls.SUPPORT

    @classmethod
    def _canonical(cls, name: str) -> str:
        return cls.ALIAS.get(name, name)

    def exts(self) -> list[str]:
        return self.EXTS[self.name]

    def __str__(self) -> str:
        return self.name


class Match(NamedTuple):
    path: Path
    range: 'Range'

    EXTRACT = re.compile(r'(.*):(\d+):(\d+)-(\d+):(\d+)')

    @classmethod
    def parse(cls, s: str) -> Self:
        from operator import itemgetter

        match = cls.EXTRACT.fullmatch(s)
        path, *offsets = itemgetter(*range(1, 6))(match)
        sr, sc, er, ec = map(int, offsets)
        return cls(Path(path), Range(Point(sr, sc), Point(er, ec)))

    def text(self) -> str:
        with self.path.open('br') as f:
            contents = f.read()
        span = self.range.span(contents)
        return contents[span].decode()

    def contains(self, other: 'Match') -> bool:
        return self.path == other.path and self.range.contains(other.range)

    def __str__(self) -> str:
        path, ((sr, sc), (er, ec)) = self
        return f'{path}:{sr}:{sc}-{er}:{ec}'


class Range(NamedTuple):
    start: 'Point'
    end: 'Point'

    def span(self, contents: str | bytes) -> slice:
        from itertools import islice

        regex = r'^.*$' if isinstance(contents, str) else rb'^.*$'
        line: re.Pattern = re.compile(regex, re.MULTILINE)

        rows = slice(self.start.row - 1, self.end.row)
        lines = *islice(line.finditer(contents), rows.start, rows.stop),

        return slice(lines[0].start() + self.start.column - 1,
                     lines[-1].start() + self.end.column - 1)

    def contains(self, other: 'Range') -> bool:
        return self.start <= other.start and other.end <= self.end

    def adjusted(self, start: 'Point') -> 'Range':
        return Range(self.start.diff(start), self.end.diff(start))


class Point(NamedTuple):
    row: int
    column: int

    def diff(self, other: 'Point') -> 'Point':
        assert other <= self
        return Point(self.row - other.row + 1,
                     self.column - other.column + 1
                     if self.row == other.row else self.column)


class Tool(Protocol):
    Match: TypeAlias = tuple[db.Run, int, int, int, int]

    def register(self) -> db.Tool:
        ...

    def run(self, experiment: str, roots: Sequence[Path]) -> Literal[True]:
        ...


def select_files(languages: Sequence[Language], paths: Iterable[Path]) -> Sequence[Path]:
    files = [p for p in all_files(paths)
             if any(p.suffix in l.exts() for l in languages)]
    print(f'common: Found {len(files)} files for: '
          + ', '.join(str(l) for l in languages))
    return files


def all_files(paths: Iterable[Path]) -> Sequence[Path]:
    import os

    result = []
    for path in paths:
        if path.is_file():
            result.append(path)
        elif path.is_dir():
            for root, _dirs, files in os.walk(path):
                result.extend(Path(root, file) for file in files)
        else:
            print(f'ERROR: common: Unknown path: {path}')
    return result
