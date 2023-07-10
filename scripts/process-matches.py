#!/usr/bin/env python3

from typing import *

import csv

from pathlib import Path
from dataclasses import dataclass, field

from tools import db
from base import Args, Arg


@dataclass
class CLI(Args):
    experiment: str
    partial: Optional[str] = field(metadata=Arg(flags=['--partial']))
    mode: str = field(metadata=Arg(choices=['analyze', 'dump', 'mismatch']))
    matches: Path
    output: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    db.init(args.matches)

    with db.RESULTS.atomic():
        assert args.mode == 'analyze' or not args.partial
        experiment = db.Experiment.get(name=args.experiment)

        match args.mode:
            case 'analyze':
                if args.partial:
                    partial = db.Experiment.get(name=args.partial)
                    query = completions(experiment, partial)
                else:
                    query = analysis(experiment)
            case 'dump':
                query = dump(experiment)
            case 'mismatch':
                query = mismatches(experiment)
            case _:
                assert False

    output = csv.writer(args.output)

    output.writerow([c.name for c in query.selected_columns])  # header
    output.writerows(query.tuples())


def completions(complete: db.Experiment, partial: db.Experiment) -> db.Query:
    tool = db.Tool.get(name='stsearch')

    parts = (complete.queries | partial.queries).alias('parts')

    results = (
        db.Result.select(db.Run.query_id)
        .join(db.Run).join(db.Tool)
        .where(db.Run.tool == tool)
        .group_by(
            db.Run.query, db.Run.file,
            db.Result.sr, db.Result.sc,
            db.Result.er, db.Result.ec,
        )
        .alias('results')
    )

    return (
        complete.queries.select(
            db.Query.pattern,
            parts.c.pattern.alias('partial'),
            SUM(parts.c.id == results.c.query_id).alias('actual'),
            SUM(db.Query.id == results.c.query_id).alias('expected')
        )
        .join(parts, db.JOIN.FULL, on=(db.fn.INSTR(db.Query.pattern, parts.c.pattern) == 1))
        .join(results, db.JOIN.LEFT_OUTER, on=((db.Query.id == results.c.query_id) | (parts.c.id == results.c.query_id)))
        .group_by(db.Query.id, parts.c.id)
        .order_by(db.Query.id, db.fn.LENGTH(db.SQL('partial')))
    )


def analysis(experiment: db.Experiment) -> db.Query:
    results = (
        db.Result.select(
            db.Run.query_id,
            *(SUM(db.Run.tool == tool).alias(tool.name)
                for tool in experiment.tools),
        )
        .join(db.Run)
        .group_by(
            db.Run.query, db.Run.file,
            db.Result.sr, db.Result.sc,
            db.Result.er, db.Result.ec,
        )
        .alias('results')
    )

    return (
        experiment.queries.select(
            db.Query.pattern.alias('pattern'),
            SUM(results.c.stsearch == 0).alias('miss'),
            SUM(results.c.semgrep == 0).alias('extra'),
            SUM(results.c.semgrep > 0).alias('semgrep'),
            SUM(results.c.stsearch > 0).alias('stsearch'),
        )
        .join(results, db.JOIN.LEFT_OUTER,
              on=(db.Query.id == results.c.query_id))
        .group_by(db.Query)
    )


def dump(experiment: db.Experiment) -> db.Query:
    return (
        experiment.queries.select(
            db.Language.name.alias('language'), db.Query.pattern,
            db.Tool.name.alias('tool'),
            db.File.path,
            db.Result.sr, db.Result.sc,
            db.Result.er, db.Result.ec,
        )
        .join_from(db.Query, db.Language)
        .join_from(db.Query, db.Run, db.JOIN.LEFT_OUTER)
        .join_from(db.Run, db.Tool)
        .join_from(db.Run, db.File)
        .join_from(db.Run, db.Result, db.JOIN.LEFT_OUTER)
        .order_by(
            db.Query.id, db.Tool.name, db.File.path,
            db.Result.sr, db.Result.sc, db.Result.er, db.Result.ec,
        )
    )


def mismatches(experiment: db.Experiment):
    return (
        db.Query.select(
            *((SUM(db.Run.tool == tool) > 0).alias(tool.name)
                for tool in db.Tool.select()),
            # db.Language.name,
            db.Query.pattern,
            (db.File.path.concat(STR(':'))
                .concat(db.Result.sr).concat(STR(':')).concat(db.Result.sc).concat(STR('-'))
                .concat(db.Result.er).concat(STR(':')).concat(db.Result.ec)
             ).alias('match'),
        )
        .join_from(db.Query, db.Language)
        .join_from(db.Query, db.Run)
        .join_from(db.Run, db.Tool)
        .join_from(db.Run, db.File)
        .join_from(db.Run, db.Result)
        .group_by(
            db.Run.query,
            db.Run.file,
            db.Result.sr, db.Result.sc,
            db.Result.er, db.Result.ec,
        )
        .where(db.Query.pattern == '$H1(...)')
        .having(db.SQL('semgrep != stsearch'))
        .order_by(db.SQL('semgrep'), db.SQL('stsearch'))
    )


def SUM(e): return db.fn.IFNULL(db.fn.SUM(e), 0)
def STR(s: str): return db.SQL(f'"{s}"')


if __name__ == '__main__':
    main(CLI.parser().parse_args())
