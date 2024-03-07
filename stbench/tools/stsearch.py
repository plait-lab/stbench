from typing import Optional, Iterable, NamedTuple, TextIO

import csv
import logging
import re
import subprocess

from pathlib import Path
from io import StringIO

from . import Language, Query, Match
from .semgrep import METAVAR


def from_semgrep(query: Query) -> Query:
    '''Translate a Semgrep query to stsearch.'''
    language, pattern = query

    # stsearch doesn't use metavar names or support named ellipsis
    # https://semgrep.dev/docs/writing-rules/pattern-syntax/#ellipsis-metavariables

    def wildcard(kind: str): return '...' if kind == '...' else '$_'
    pattern = METAVAR.sub(lambda m: wildcard(m['kind']), pattern)

    # FIX: generalize to more languages
    pattern = re.sub(r',?(\s*\.{3}\s*),?', r'\1', pattern)
    pattern = re.sub(r'(?<!\.)\.\s*(\.{3}\s*\.)(?!\.)', r'\1', pattern)

    return query._replace(syntax=pattern)


class Runner:
    def __init__(self, metrics: Optional[TextIO] = None) -> None:
        self.log = metrics

    def __call__(self, query: Query, file: Path | str) -> Iterable[Match]:
        if self.log is not None:
            # prefix metrics with run info
            csv.writer(buffer := StringIO()).writerow((*query, file, ''))
            self.log.write(buffer.getvalue().rstrip())
            self.log.flush()

        yield from run(query, file, self.log)

    def metrics(self) -> Iterable['Metrics']:
        assert self.log is not None, 'metrics not recorded'
        assert self.log.readable(), 'metrics not readable'
        self.log.seek(0)

        for l, q, p, *vs in csv.reader(self.log):
            n, d, k, w, pt, st = map(int, vs)
            yield Metrics(
                Query(Language(l), q), Metrics.Seq(k, w),
                p, Metrics.Tree(n, d),
                Metrics.Time(pt, st),
            )


class Metrics(NamedTuple):
    class Seq(NamedTuple):
        length: int
        wcount: int
    query: Query
    seq: Seq

    class Tree(NamedTuple):
        size: int
        depth: int
    path: str
    tree: Tree

    class Time(NamedTuple):
        parse: int
        search: int
    time: Time


def run(query: Query, file: Path | str, metrics: Optional[TextIO] = None) -> Iterable[Match]:
    cmd = ['stsearch', query.language.name, query.syntax, file]
    if metrics:
        cmd.append('--metrics')

    logging.debug(f'$ {subprocess.list2cmdline(cmd)}')
    with subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE, stderr=metrics) as process:
        yield from map(Match.parse, process.stdout or ())

        if code := process.wait():
            logging.error(f'stsearch: exit {code}')
