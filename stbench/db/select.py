from typing import Iterable, Optional

from peewee import Select, Column, Expression, fn

from .model import Tool, Query, Spec, Run, Result


def qtotals(tool: Tool) -> Iterable[tuple[Query, int]]:
    matches: Select = umatches().where(Run.tool_id == tool.id)  # type: ignore

    return ((s.query(tool), s.count) for s in (
        Spec.select(Spec, count(matches.c.count))
        .left_outer_join(matches, on=(Spec.id == matches.c.spec_id))
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
