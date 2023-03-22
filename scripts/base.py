from typing import *

import yaml
import re

from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class Language:
    name = str

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


def add_custom_tags(Loader: yaml.Loader, Dumper: yaml.Dumper):
    T = TypeVar('T')

    custom = [
        # type, tag, parser
        (Language, '!lang', Language),
        (Match, '!match', Match.parse),
        (type(Path()), '!path', Path),
    ]

    def add_custom_tag(cls: Type[T], tag: str, parse: Callable[[str], T]) -> Type[T]:
        def constructor(self: yaml.Loader, node: yaml.Node) -> cls:
            return parse(self.construct_scalar(node))

        def representer(self: yaml.Dumper, data: cls) -> yaml.ScalarNode:
            return self.represent_scalar(tag, str(data))

        yaml.add_constructor(tag, constructor, Loader=Loader)
        yaml.add_representer(cls, representer, Dumper=Dumper)

    no_alias = []
    for cls, *args in custom:
        add_custom_tag(cls, *args)
        no_alias.append(cls)

    def ignore_aliases(dumper: yaml.Dumper, data: Any):
        return any(isinstance(data, cls) for cls in no_alias) \
            or ignore_aliases_old(dumper, data)

    ignore_aliases_old = Dumper.ignore_aliases
    Dumper.ignore_aliases = ignore_aliases


def add_pretty_representers(Dumper: yaml.Dumper):
    def str_representer(self: yaml.Dumper, data: str) -> yaml.ScalarNode:
        return self.represent_scalar('tag:yaml.org,2002:str', data,
                                     style=('|' if '\n' in data else None))

    yaml.add_representer(str, str_representer, Dumper=Dumper)


add_custom_tags(yaml.SafeLoader, yaml.SafeDumper)
add_pretty_representers(yaml.SafeDumper)
