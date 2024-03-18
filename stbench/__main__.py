#!/usr/bin/env python3

from typing import Iterable

import logging

from argparse import ArgumentParser
from itertools import accumulate, product, groupby
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
    fresh: bool


def add_args(parser: ArgumentParser):
    parser.add_argument('--queries', required=True, type=Path)
    parser.add_argument('--corpus', required=True, type=Path)
    parser.add_argument('--results', required=True, type=Path)
    parser.add_argument('--fresh', action='store_true')


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
            queries[st] = sg
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
            projects[project] = sorted(find(project, languages))
    results.save('projects', ((p,) for p in projects))

    files = [f for fs in projects.values() for f in fs]
    results.save('files', ((f,) for f in files))

    report(
        f'corpus: {args.corpus}',
        f'{len(projects):5} unique projects',
        f'{len(files):5} relevant files',
    )

    logger.info(f'collecting matches!')
    prepare(args.results / 'matches.db', truncate=args.fresh)
    st, sg = Tool.from_names('stsearch', 'semgrep')

    complete = Spec.from_qs([st, sg], queries.items())
    upartials = Spec.from_qs([st], set((q,) for q in upartials))

    mode = 'w' if args.fresh else 'a'  # keep previous results
    strunner = stsearch.Runner((args.results / 'metrics.csv').open(mode+'+'))
    smrunner = semgrep.Runner((args.results / 'config.yaml'),
                              (args.results / 'semgrep.err').open(mode))

    for project, files in projects.items():
        logger.info(f' > project: {project}')
        fmodels = File.from_proj(files)

        logger.info(f'  * complete - {st.name}')
        Run.batch(st, complete, fmodels, strunner)

        logger.info(f'  * complete - {sg.name}')
        Run.batchX(sg, complete, project, fmodels, smrunner)

        logger.info(f'  * partials - {st.name}')
        Run.batch(st, upartials, fmodels, strunner)

    epaths = sorted(smrunner.epaths)
    metrics = list(strunner.metrics())

    report(f'# BENCHMARK')

    seqs = {m.query: m.seq for m in metrics if m.query in queries}
    report(stats('token length', (s.length for s in seqs.values()), 'tokens'))
    report(stats('wildcards', (s.wcount for s in seqs.values()), 'wildcards'))

    files = (f for fs in projects.values() for f in fs)
    report(stats('file size', (f.stat().st_size for f in files), 'B'))
    trees = {m.path: m.tree for m in metrics}
    report(stats('tree size', (t.size for t in trees.values()), 'nodes'))
    report(stats('tree depth', (t.depth for t in trees.values()), 'nodes'))

    report(f'# COMPLETE')

    matches = {l: d for l, *d, r in select.qdiff(st, sg, epaths) if any(d)}
    results.save('errpaths', ((p,) for p in epaths))
    results.save('matches', ((*l, *d) for l, d in matches.items()))
    report(
        f'analysis prelude',
        f'dropped {len(epaths)} paths w/ errors',
        f'selected {len(matches)} queries w/ results',
    )

    incl, both, excl = map(sum, zip(*matches.values()))
    report(mmatrix('stsearch', incl, both, excl, 'semgrep'))

    report(f'# PARTIAL')

    totals = {q: t for q, t in select.qtotals(st)}
    partial = {q: ps for q, ps in partial.items() if totals[q]}
    upartials = set().union(*partial.values()).difference(queries)
    report(
        f'analysis prelude',
        f'selected {len(partial)} queries w/ results',
        f'selected {len(upartials)} corresp. partial queries',
    )

    ptotals = {q: [totals[p] for p in ps] for q, ps in partial.items()}
    results.save('progress', ((*q, *ts) for q, ts in ptotals.items()))

    report(f'# PERFORMANCE')

    runs = {(m.query, m.path): m.time for m in metrics}
    report(stats('parse time', (t.parse for t in runs.values()), 'µs'))
    report(stats('search time', (t.search for t in runs.values()), 'µs'))

    pruns = {(q, p): sum(runs[q, str(f)].search for f in fs if (q, str(f)) in runs)
             for q, (p, fs) in product(queries, projects.items())}
    report(stats('project search', pruns.values(), 'µs'))

    no_excl = sum(1 for i, b, e in matches.values() if not e)
    fast = sum(1 for t in pruns.values() if t < (thres := 1e6))  # one second

    report(f'# OVERALL')

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

    return (next(qs) for q, qs in groupby(queries, key=Query.strip))


if __name__ == '__main__':
    parser = ArgumentParser()
    add_args(parser)
    main(parser.parse_args())  # type: ignore
