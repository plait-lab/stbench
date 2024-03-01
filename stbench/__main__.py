#!/usr/bin/env python3

from typing import Iterable

import csv
import logging

from argparse import ArgumentParser
from itertools import accumulate
from pathlib import Path

from pygments import lex
from pygments.lexers import get_lexer_by_name

from .langs import find
from .tools import Query, semgrep, stsearch
from .stats import stats


class Args:
    queries: Path
    corpus: Path
    results: Path


def add_args(parser: ArgumentParser):
    parser.add_argument('--queries', required=True, type=Path)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--results', required=True, type=Path)


def main(args: Args):
    args.results.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(level=logging.INFO, handlers=[
        logging.FileHandler(args.results / 'trace.log', 'w'),
        logging.StreamHandler(),  # keep stderr
    ])

    logging.info(f'queries: {args.queries}')

    rules = list(semgrep.rules(args.queries))
    save(args.results / 'rules', ((s, r['id']) for s, r in rules))
    print(f'{len(rules)} semgrep rules')

    queries: dict[Query, Query] = {}
    for source, rule in rules:
        for pattern in semgrep.patterns(rule):
            sg = semgrep.canonical(pattern)
            st = stsearch.from_semgrep(sg)
            queries[sg] = st
    save(args.results / 'complete', queries)
    print(f'{len(queries)} unique queries')

    partial = {q: list(prefixes(q)) for q in queries}
    partials = set().union(*partial.values()).difference(queries)
    save(args.results / 'partials', sorted(partials))
    print(f'{len(partials)} partial queries')

    languages = {q.language for q in queries}
    print(f'languages: ' + ','.join(map(str, languages)))

    logging.info(f'corpus: {args.corpus}')

    projects: dict[Path, list[Path]] = {}
    with args.corpus.open() as file:
        for name in file:
            project = args.corpus.parent / name.rstrip()
            projects[project] = list(find(project, languages))
    save(args.results / 'projects', ((p,) for p in projects))
    print(f'{len(projects)} projects included')

    files = [f for fs in projects.values() for f in fs]
    print(f'{len(files)} files included')

    def fsize(p: Path): return p.stat().st_size
    print(stats('file size', files, fsize, 'B'))


def prefixes(query: Query) -> Iterable[Query]:
    '''Generate all (unambiguous) token prefixes for a given query.'''
    lexer = get_lexer_by_name(query.language.name)

    prefixes = accumulate(v for t, v in lex(query.syntax, lexer))
    queries = map(lambda p: query._replace(syntax=p), prefixes)

    # Use canonical repr to filter whitespace & ambiguous prefixes
    return (q for q in queries if semgrep.canonical(q) == q)


def save(path: Path, it: Iterable[tuple]):
    with path.with_suffix('.csv').open('w') as file:
        csv.writer(file).writerows(it)


if __name__ == '__main__':
    parser = ArgumentParser()
    add_args(parser)
    main(parser.parse_args())  # type: ignore
