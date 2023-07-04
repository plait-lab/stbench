#!/usr/bin/env python3

from typing import *

import re

from pathlib import Path
from csv import DictWriter
from dataclasses import dataclass, field

from tools import db
from base import Args, Arg


@dataclass
class CLI(Args):
    experiment: str
    matches: Path
    results: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    agg = DictWriter(args.results,
                     ('pattern', 'miss', 'extra', 'semgrep', 'stsearch'))

    db.init(args.matches)
    with db.RESULTS.atomic():
        experiment = db.Experiment.get(name=args.experiment)

        def SUM(e): return db.fn.IFNULL(db.fn.SUM(e), 0)

        results = (
            db.Result
            .select(
                db.Run.query_id,
                *(SUM(db.Run.tool == tool).alias(tool.name)
                  for tool in experiment.tools))
            .join(db.Run)
            .group_by(
                db.Run.query, db.Run.file,
                db.Result.sr, db.Result.sc,
                db.Result.er, db.Result.ec)
            .alias('results'))

        analysis = (
            experiment.queries
            .select(
                db.Query.pattern.alias('pattern'),
                SUM(results.c.stsearch == 0).alias('miss'),
                SUM(results.c.semgrep == 0).alias('extra'),
                SUM(results.c.semgrep > 0).alias('semgrep'),
                SUM(results.c.stsearch > 0).alias('stsearch'),
            )
            .join(results, db.JOIN.LEFT_OUTER,
                  on=(db.Query.id == results.c.query_id))
            .group_by(db.Query))

        agg.writeheader()
        agg.writerows(analysis.dicts())


def fix_all(results: Iterable[Match], reference: set[Match]) -> Iterable[Match]:
    for result in results:
        yield fix(result, reference)


def fix(result: Match, reference: set[Match]) -> Match:
    prefix, suffix = re.compile(r'(\(\s*)*'), re.compile(r'(\}?\`)?(\s*\))*')
    if result not in reference:
        for candidate in sorted(
            (c for c in reference if c.contains(result)),
            key=lambda c: c.range.adjusted(c.range.start).end
        ):
            start, context = candidate.range.start, candidate.text()
            span = result.range.adjusted(start).span(context)

            if prefix.fullmatch(context, 0, span.start) \
                    and suffix.fullmatch(context, span.stop):
                # print('EXTENDING MATCH')
                # print('FROM:', repr(context[span]))
                # print('  TO:', repr(context))
                return candidate
    return result


if __name__ == '__main__':
    main(CLI.parser().parse_args())
