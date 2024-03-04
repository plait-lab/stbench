from typing import Iterable, Any

from pathlib import Path

from peewee import SqliteDatabase, Model, chunked


db = SqliteDatabase(None)


class Base(Model):
    # Silence report type errors
    id: Any

    class Meta:
        database = db

    @classmethod
    def bulk_insert(cls, it: Iterable[tuple], fields=None):
        if fields is None:
            fields = cls._meta.sorted_field_names[1:]  # type: ignore

        # https://www.sqlite.org/limits.html#max_variable_number
        for chunk in chunked(it, 32766 // len(fields)):
            cls.insert_many(chunk, fields).execute()


def prepare(database: Path, truncate=False):
    # https://docs.peewee-orm.com/en/latest/peewee/database.html#recommended-settings
    db.init(database, pragmas={
        'journal_mode': 'wal',
        'cache_size': -1 * 64000,  # 64MB
        'foreign_keys': 1,
        'ignore_check_constraints': 0,
        'synchronous': 0,
    })

    models = [m for m in Base.__subclasses__()]
    db.create_tables(models)

    if truncate:
        for model in reversed(models):
            model.delete().execute()
