#!/usr/bin/env python3

from typing import Iterable

import csv
import logging

from argparse import ArgumentParser
from itertools import accumulate, product
from pathlib import Path

from pygments import lex
from pygments.lexers import get_lexer_by_name

from .db import prepare, select
from .db.model import Tool, Spec, File, Run

from .langs import find
from .tools import Query, semgrep, stsearch
from .stats import stats, mmatrix


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
    save(args.results / 'partials',
         ((*q, *(p.syntax for p in ps)) for q, ps in partial.items()))

    partials = set().union(*partial.values()).difference(queries)
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

    logging.info(f'collecting matches!')
    prepare(args.results / 'matches.db', truncate=True)
    st, sg = Tool.from_names('stsearch', 'semgrep')

    complete = Spec.from_qs([sg, st], queries.items())
    sm2st = queries | {q: stsearch.from_semgrep(q) for q in partials}
    partials = Spec.from_qs([st], set((sm2st[q],) for q in partials))

    strunner = stsearch.Runner((args.results / 'metrics.csv').open('w+'))
    smrunner = semgrep.Runner((args.results / 'config.yaml'),
                              (args.results / 'semgrep.err').open('w'))

    for project, files in projects.items():
        logging.info(f' > project: {project}')
        fmodels = File.from_proj(files)

        logging.info(f'    * complete - {st.name}')
        Run.batch(st, complete, fmodels, strunner)

        logging.info(f'    * complete - {sg.name}')
        Run.batchX(sg, complete, project, fmodels, smrunner)

        logging.info(f'    * partials - {st.name}')
        Run.batch(st, partials, fmodels, strunner)

    logging.info(f'analyzing matches')

    epaths = set(map(Path, smrunner.epaths))
    print(f'dropping {len(epaths)} paths w/ errors')
    for path in epaths:
        Run.delete().where(Run.file_id == File.get(path=path).id).execute()

    matches = {r: tuple(d) for l, *d, r in select.qdiff(st, sg)}
    save(args.results / 'matches', ((*l, *d) for l, d in matches.items()))

    matches = {l: d for l, d in matches.items() if any(d)}
    print(f'selected {len(matches)} queries w/ results')

    incl, both, excl = map(sum, zip(*matches.values()))
    print(mmatrix('stsearch', incl, both, excl, 'semgrep'))
    no_excl = sum(1 for i, b, e in matches.values() if not e)
    print(f'{100 * no_excl / len(matches):.2f}% queries w/o excluded')

    totals = {q: t for q, t in select.qtotals(st)}
    ptotals = {q: [totals[st] for sm, st in sorted(sm2st.items())
                   if q.syntax.startswith(sm.syntax)] for q in queries}
    save(args.results / 'progress', ((*q, *ts) for q, ts in ptotals.items()))

    logging.info(f'analyzing metrics')
    metrics = list(strunner.metrics())

    seqs = {m.query: m.seq for m in metrics}  # dedups
    print(stats('token length', seqs.values(), lambda s: s.length, 'tokens'))
    print(stats('wildcards', seqs.values(), lambda s: s.wcount, 'wildcards'))

    trees = {m.path: m.tree for m in metrics}  # dedups
    print(stats('file size', files, lambda p: p.stat().st_size, 'B'))
    print(stats('tree size', trees.values(), lambda t: t.size, 'nodes'))
    print(stats('tree depth', trees.values(), lambda t: t.depth, 'nodes'))

    runs = {(m.query, m.path): m.time for m in metrics}
    print(stats('parse time', runs.values(), lambda t: t.parse, 'µs'))
    print(stats('search time', runs.values(), lambda t: t.search, 'µs'))

    pruns = {(q, p): sum(runs[q, str(f)].search for f in fs if (q, str(f)) in runs)
             for q, (p, fs) in product(queries, projects.items())}
    print(stats('project search', pruns.values(), lambda t: t, 'µs'))

    thres = 1e6  # one second
    fast = sum(1 for t in pruns.values() if t < thres)
    print(f'{100 * fast / len(pruns):.2f}% projects ran in <{thres:.2E}µs')


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
