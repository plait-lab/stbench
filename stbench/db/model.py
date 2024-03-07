from typing import Self, Iterable, TypeAlias, Callable, Any

from itertools import product
from pathlib import Path

from peewee import ForeignKeyField, CharField, IntegerField
from playhouse.sqlite_ext import JSONField

from ..tools import Language, Query, Match
from . import Base


class Tool(Base):
    name: str = CharField(unique=True)  # type: ignore

    @classmethod
    def from_names(cls, *names: str) -> list[Self]:
        return list(cls.create(name=n) for n in names)


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

        return cls.create(data=data)

    def query(self, tool: Tool):
        return Query(Language(self.data['lang']), self.data[tool.name])

    @classmethod
    def queryc(cls, tool: Tool):
        return cls.data.extract_json(f'$.{tool.name}')  # type: ignore


class File(Base):
    path: str = CharField(unique=True)  # type: ignore

    @classmethod
    def from_proj(cls, project: list[Path]) -> dict[str, Self]:
        return {str(p): cls.create(path=p) for p in project}


class Run(Base):
    tool: Tool = ForeignKeyField(Tool)  # type: ignore
    spec: Spec = ForeignKeyField(Spec)  # type: ignore
    file: File = ForeignKeyField(File)  # type: ignore

    # Silence report type errors
    tool_id: Any
    spec_id: Any
    file_id: Any

    @classmethod
    def register(cls, tool: Tool, spec: Spec, file: File) -> Self:
        return cls.create(tool=tool, spec=spec, file=file)

    Runner: TypeAlias = Callable[[Query, str], Iterable[Match]]

    @classmethod
    def collect(cls, tool: Tool, spec: Spec, file: File, runner: Runner):
        run = cls.register(tool, spec, file)
        matches = runner(spec.query(tool), file.path)
        Result.bulk_insert((run, *r) for f, r in matches)
        return run

    @classmethod
    def batch(cls, tool: Tool, specs: list[Spec], fmodels: dict[str, File], runner: Runner):
        for spec, file in product(specs, fmodels.values()):
            cls.collect(tool, spec, file, runner)

    RunnerX: TypeAlias = Callable[[list[Query], Path, list[str]],
                                  Iterable[tuple[Query, Match]]]

    @classmethod
    def batchX(cls, tool: Tool, specs: list[Spec], root: Path, fmodels: dict[str, File], runner: RunnerX):
        qmodels = {spec.query(tool): spec for spec in specs}
        runs = {(q, p): cls.register(tool, s, f) for (q, s), (p, f)
                in product(qmodels.items(), fmodels.items())}

        matches = runner(list(qmodels), root, list(fmodels))
        Result.bulk_insert((runs[q, f], *r) for q, (f, r) in matches)


class Result(Base):
    run: Run = ForeignKeyField(Run, on_delete='CASCADE')  # type: ignore

    # range flattened
    sr, sc = IntegerField(), IntegerField()
    er, ec = IntegerField(), IntegerField()
