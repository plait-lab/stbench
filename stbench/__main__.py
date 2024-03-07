#!/usr/bin/env python3

from typing import Iterable

import logging

from argparse import ArgumentParser
from itertools import accumulate, product
from pathlib import Path

from pygments import lex
from pygments.lexers import get_lexer_by_name

from . import logger, Results, report

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
    results = Results(args.results)
    results.report('report')

    logging.basicConfig(level=logging.DEBUG, handlers=[
        console := logging.StreamHandler(),
        results.tracer('trace'),
    ])

    # disable detailed logging in the terminal
    console.setLevel(logging.INFO)

    rules = list(semgrep.rules(args.queries))
    queries: dict[Query, Query] = {}
    for source, rule in rules:
        for pattern in semgrep.patterns(rule):
            sg = semgrep.canonical(pattern)
            st = stsearch.from_semgrep(sg)
            queries[sg] = st
    languages = {q.language for q in queries}
    results.save('complete', queries)

    partial = {q: list(prefixes(q)) for q in queries}
    upartials = set().union(*partial.values()).difference(queries)
    results.save('partials', ((ps[0].language, *(p.syntax for p in reversed(ps)))
                              for ps in partial.values()))

    report(
        f'queries: {args.queries}',
        f'{len(rules):5} semgrep rules',
        f'{len(queries):5} unique queries',
        f'{len(upartials):5} partial queries',
        f'languages: ' + ','.join(map(str, languages)),
    )

    projects: dict[Path, list[Path]] = {}
    with args.corpus.open() as file:
        for name in file:
            project = args.corpus.parent / name.rstrip()
            projects[project] = list(find(project, languages))
    results.save('projects', ((p,) for p in projects))

    files = [f for fs in projects.values() for f in fs]
    results.save('files', ((f,) for f in files))

    report(
        f'corpus: {args.corpus}',
        f'{len(projects):5} unique projects',
        f'{len(files):5} relevant files',
    )

    logger.info(f'collecting matches!')
    prepare(args.results / 'matches.db', truncate=True)
    st, sg = Tool.from_names('stsearch', 'semgrep')

    complete = Spec.from_qs([sg, st], queries.items())
    sm2st = queries | {q: stsearch.from_semgrep(q) for q in upartials}
    upartials = Spec.from_qs([st], set((sm2st[q],) for q in upartials))

    strunner = stsearch.Runner((args.results / 'metrics.csv').open('w+'))
    smrunner = semgrep.Runner((args.results / 'config.yaml'),
                              (args.results / 'semgrep.err').open('w'))

    for project, files in projects.items():
        logger.info(f' > project: {project}')
        fmodels = File.from_proj(files)

        logger.info(f'  * complete - {st.name}')
        Run.batch(st, complete, fmodels, strunner)

        logger.info(f'  * complete - {sg.name}')
        Run.batchX(sg, complete, project, fmodels, smrunner)

        logger.info(f'  * partials - {st.name}')
        Run.batch(st, upartials, fmodels, strunner)

    logger.info(f'analyzing matches')

    epaths = set(map(Path, smrunner.epaths))
    for path in epaths:
        Run.delete().where(Run.file_id == File.get(path=path).id).execute()

    matches = {r: tuple(d) for l, *d, r in select.qdiff(st, sg)}
    results.save('matches', ((*l, *d) for l, d in matches.items()))

    matches = {l: d for l, d in matches.items() if any(d)}
    partial = {q: ps for q, ps in partial.items() if q in matches}
    upartials = set().union(*partial.values()).difference(queries)
    report(
        f'analysis prelude',
        f'dropped {len(epaths)} paths w/ errors',
        f'selected {len(matches)} queries w/ results',
        f'selected {len(upartials)} corresp. partial queries',
    )

    incl, both, excl = map(sum, zip(*matches.values()))
    report(mmatrix('stsearch', incl, both, excl, 'semgrep'))

    totals = {q: t for q, t in select.qtotals(st)}
    ptotals = {q: [totals[st] for sm, st in sorted(sm2st.items())
                   if q.syntax.startswith(sm.syntax)] for q in queries}
    results.save('progress', ((*q, *ts) for q, ts in ptotals.items()))

    logger.info(f'analyzing metrics')
    metrics = list(strunner.metrics())

    seqs = {m.query: m.seq for m in metrics}  # dedups
    report(stats('token length', seqs.values(), lambda s: s.length, 'tokens'))
    report(stats('wildcards', seqs.values(), lambda s: s.wcount, 'wildcards'))

    trees = {m.path: m.tree for m in metrics}  # dedups
    report(stats('file size', files, lambda p: p.stat().st_size, 'B'))
    report(stats('tree size', trees.values(), lambda t: t.size, 'nodes'))
    report(stats('tree depth', trees.values(), lambda t: t.depth, 'nodes'))

    runs = {(m.query, m.path): m.time for m in metrics}
    report(stats('parse time', runs.values(), lambda t: t.parse, 'µs'))
    report(stats('search time', runs.values(), lambda t: t.search, 'µs'))

    pruns = {(q, p): sum(runs[q, str(f)].search for f in fs if (q, str(f)) in runs)
             for q, (p, fs) in product(queries, projects.items())}
    report(stats('project search', pruns.values(), lambda t: t, 'µs'))

    no_excl = sum(1 for i, b, e in matches.values() if not e)
    fast = sum(1 for t in pruns.values() if t < (thres := 1e6))  # one second

    report(
        f'key results',
        f'{100 * no_excl / len(matches):.2f}% queries w/o excluded matches',
        f'{100 * fast / len(pruns):.2f}% projects ran in <{thres:.2E}µs',
    )


def prefixes(query: Query) -> Iterable[Query]:
    '''Generate all (unambiguous) token prefixes for a given query.'''
    lexer = get_lexer_by_name(query.language.name)

    prefixes = accumulate(v for t, v in lex(query.syntax, lexer))
    queries = map(lambda p: query._replace(syntax=p), prefixes)

    # Use canonical repr to filter whitespace & ambiguous prefixes
    return (q for q in queries if semgrep.canonical(q) == q)


if __name__ == '__main__':
    parser = ArgumentParser()
    add_args(parser)
    main(parser.parse_args())  # type: ignore
