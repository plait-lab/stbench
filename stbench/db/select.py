from typing import Iterable, Optional

from peewee import Select, Column, Expression, fn

from .model import Tool, Query, Spec, Run, Result


def qdiff(left: Tool, right: Tool) -> Iterable[tuple[Query, int, int, int, Query]]:
    matches = umatches(
        fn.MAX(Run.tool_id == left.id).alias('left'),
        fn.MAX(Run.tool_id == right.id).alias('right'),
    )

    return ((s.query(left), s.left, s.both, s.right, s.query(right)) for s in (
        Spec.select(
            Spec,
            fn.SUM(matches.c.left & matches.c.right).alias('both'),
            fn.SUM(matches.c.left & ~matches.c.right).alias('left'),
            fn.SUM(~matches.c.left & matches.c.right).alias('right'),
        )
        .left_outer_join(matches, on=(Spec.id == matches.c.spec_id))
        .where(
            Spec.queryc(left).is_null(False) &
            Spec.queryc(right).is_null(False)
        )
        .group_by(Spec.id).order_by(Spec.id)
    ))


def qtotals(tool: Tool) -> Iterable[tuple[Query, int]]:
    matches: Select = umatches().where(Run.tool_id == tool.id)  # type: ignore

    return ((s.query(tool), s.count) for s in (
        Spec.select(Spec, count(matches.c.count))
        .left_outer_join(matches, on=(Spec.id == matches.c.spec_id))
        .where(Spec.queryc(tool).is_null(False))
        .group_by(Spec.id).order_by(Spec.id)
    ))


def umatches(*toolc: Column) -> Select:
    key = (
        Run.spec_id, Run.file_id,
        Result.sr, Result.sc, Result.er, Result.ec,
    )

    return (
        Result.select(*key, *toolc, count())
        .join(Run).group_by(*key)
    )


def count(e: Optional[Expression] = None) -> Expression:
    args = () if e is None else (e,)
    return fn.COUNT(*args).alias('count')
