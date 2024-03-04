from typing import Iterable

import logging
import re
import subprocess

from pathlib import Path

from . import Query, Match
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


def run(query: Query, file: Path | str) -> Iterable[Match]:
    cmd = ['stsearch', query.language.name, query.syntax, file]
    logging.debug(f'$ {subprocess.list2cmdline(cmd)}')
    with subprocess.Popen(cmd, text=True, stdout=subprocess.PIPE) as process:
        yield from map(Match.parse, process.stdout or ())

        if code := process.wait():
            logging.error(f'stsearch: exit {code}')
