from typing import *

from pathlib import Path
from datetime import datetime
from threading import BoundedSemaphore
from contextlib import contextmanager

from peewee import *


CONNECT = BoundedSemaphore()
RESULTS = DatabaseProxy()
through = []


class Model(Model):
    class Meta:
        database = RESULTS

    @classmethod
    def bulk_insert(cls, it: Iterable[tuple], fields=None, chunk_size=1000):
        for chunk in chunked(it, chunk_size):
            cls.insert_many(chunk, fields).execute()


class Tool(Model):
    name = CharField(unique=True)


class Language(Model):
    name = CharField(unique=True)


class Query(Model):
    language = ForeignKeyField(Language)
    pattern = CharField()

    class Meta:
        indexes = ((('language', 'pattern'), True),)


class File(Model):
    path = CharField(unique=True)


class Run(Model):
    tool = ForeignKeyField(Tool)
    query = ForeignKeyField(Query)
    file = ForeignKeyField(File)


class Result(Model):
    run = ForeignKeyField(Run)

    # flattened
    sr, sc = IntegerField(), IntegerField()
    er, ec = IntegerField(), IntegerField()


class Experiment(Model):
    name = CharField(unique=True)
    time = DateTimeField(default=datetime.now())
    queries = ManyToManyField(Query)
    files = ManyToManyField(File)
    tools = ManyToManyField(Tool)


through.extend([
    Experiment.queries,
    Experiment.files,
    Experiment.tools,
])


def init(db: Path | str):
    RESULTS.initialize(SqliteDatabase(db, returning_clause=True, pragmas={
        'foreign_keys': 1,
        'ignore_check_constraints': 0,
    }))

    RESULTS.connect()
    RESULTS.create_tables([m for m in Model.__subclasses__()])
    RESULTS.create_tables([f.through_model for f in through])


@contextmanager
def transact():
    # sqlite doesn't seem to support concurrent writers :/
    with CONNECT, RESULTS:
        yield
