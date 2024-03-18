from typing import Self, Iterable, TypeAlias, Callable, Any

import logging

from itertools import product
from pathlib import Path

from peewee import ForeignKeyField, CharField, IntegerField
from playhouse.sqlite_ext import JSONField

from ..tools import Language, Query, Match
from . import Base, db


logger = logging.getLogger(__name__)


class Tool(Base):
    name: str = CharField(unique=True)  # type: ignore

    @classmethod
    def from_names(cls, *names: str) -> list[Self]:
        return [cls.ensure(name=n) for n in names]


class Spec(Base):
    data: dict = JSONField(unique=True)  # type: ignore

    @classmethod
    def from_qs(cls, tools: list[Tool], it: Iterable[Iterable[Query]]) -> list[Self]:
        return [cls.from_q(list(zip(tools, qs))) for qs in it]

    @classmethod
    def from_q(cls, queries: list[tuple[Tool, Query]]) -> Self:
        data = {t.name: q.syntax for t, q in queries}

        lang = queries[0][1].language
        assert all(lang == q.language for t, q in queries)
        data['lang'] = lang.name

        return cls.ensure(data=data)

    def query(self, tool: Tool):
        return Query(Language(self.data['lang']), self.data[tool.name])

    @classmethod
    def queryc(cls, tool: Tool):
        return cls.data.extract_json(f'$.{tool.name}')  # type: ignore


class File(Base):
    path: str = CharField(unique=True)  # type: ignore

    @classmethod
    def from_proj(cls, project: list[Path]) -> dict[str, Self]:
        return {str(p): cls.ensure(path=p) for p in project}


class Run(Base):
    tool: Tool = ForeignKeyField(Tool)  # type: ignore
    spec: Spec = ForeignKeyField(Spec)  # type: ignore
    file: File = ForeignKeyField(File)  # type: ignore

    class Meta:  # type: ignore
        indexes = (('tool', 'spec', 'file'), True),

    # Silence report type errors
    tool_id: Any
    spec_id: Any
    file_id: Any

    @classmethod
    def register(cls, tool: Tool, spec: Spec, file: File) -> Self:
        return cls.ensure(tool=tool, spec=spec, file=file)

    Runner: TypeAlias = Callable[[Query, str], Iterable[Match]]

    @classmethod
    @db.atomic()
    def collect(cls, tool: Tool, spec: Spec, file: File, runner: Runner):
        if (run := cls.register(tool, spec, file))._created:
            matches = runner(spec.query(tool), file.path)
            Result.bulk_insert((run, *r) for f, r in matches)
        else:
            logger.debug(f'cached - {tool.name} #{spec.id} {file.path}')

    @classmethod
    def batch(cls, tool: Tool, specs: list[Spec], fmodels: dict[str, File], runner: Runner):
        for spec, file in product(specs, fmodels.values()):
            cls.collect(tool, spec, file, runner)

    RunnerX: TypeAlias = Callable[[list[Query], Path, list[str]],
                                  Iterable[tuple[Query, Match]]]

    @classmethod
    @db.atomic()
    def batchX(cls, tool: Tool, specs: list[Spec], root: Path, fmodels: dict[str, File], runner: RunnerX):
        qmodels = {spec.query(tool): spec for spec in specs}
        runs = {(q, p): cls.register(tool, s, f) for (q, s), (p, f)
                in product(qmodels.items(), fmodels.items())}

        cached = [run.id for run in runs.values() if not run._created]
        if len(cached) != len(runs):
            if cached:  # clear cached results...
                Result.delete().where(Result.run_id.in_(cached)).execute()
                logger.warning(f'dropped - [{len(cached)}] {tool.name} runs')

            matches = runner(list(qmodels), root, list(fmodels))
            Result.bulk_insert((runs[q, f], *r) for q, (f, r) in matches)
        else:
            logger.debug(f'cached - {tool.name} [{len(specs)}] {root}')

    def __str__(self) -> str:
        return f''


class Result(Base):
    run: Run = ForeignKeyField(Run, on_delete='CASCADE')  # type: ignore

    # Silence report type errors
    run_id: Any

    # range flattened
    sr, sc = IntegerField(), IntegerField()
    er, ec = IntegerField(), IntegerField()
