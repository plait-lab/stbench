from typing import *

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from itertools import product

from tools import db


def from_semgrep(pattern: str) -> str:
    import re

    from tools.semgrep import METAVAR

    # TODO: stsearch doesn't use metavar names or support named ellipsis
    # https://semgrep.dev/docs/writing-rules/pattern-syntax/#ellipsis-metavariables
    pattern = METAVAR.sub(
        lambda m: '...' if m['kind'] == '...' else '$_', pattern)

    # FIX: generalize to more languages
    pattern = re.sub(r',?(\s*\.{3}\s*),?', r'\1', pattern)
    pattern = re.sub(r'(?<!\.)\.\s*(\.{3}\s*\.)(?!\.)', r'\1', pattern)

    return pattern


def register():
    tool, _ = db.Tool.get_or_create(name='stsearch')
    return tool


def run(experiment: str, roots: Sequence[Path]) -> Literal[True]:
    import subprocess

    from tools.common import Language, Match

    def parse(s: str): return Match.parse(s.rstrip('\n'))

    with db.transact():
        experiment = db.Experiment.get(name=experiment)

        tool = register()
        queries = list(experiment.queries.select(db.Query, db.Language)
                       .join_from(db.Query, db.Language))
        files = list(experiment.files)

    def worker(lang_query: tuple[db.Query, Language], file: db.File):
        language, query = lang_query
        pattern = from_semgrep(query.pattern)

        if any(file.path.endswith(ext) for ext in language.exts()):
            process = subprocess.Popen(['stsearch', language.name, pattern, file.path],
                                       text=True, stdout=subprocess.PIPE)

            with db.transact():
                run = db.Run.create(tool=tool, query=query, file=file)

                db.Result.bulk_insert(((run, sr, sc, er, ec) for _, ((sr, sc), (er, ec))
                                       in map(parse, process.stdout)),
                                      ('run', 'sr', 'sc', 'er', 'ec'))

            if process.wait():
                print(f'ERROR: stsearch: $ {subprocess.list2cmdline(process.args)}')

        return True

    print(f'stsearch: Running with each pattern on each path...')
    with ThreadPoolExecutor() as tp:
        completed = tp.map(lambda args: worker(*args),
                           product(((Language(q.language.name), q) for q in queries), files))

        for i, done in enumerate(completed, start=1):
            assert done
            if i % len(files) == 0:
                n = i // len(files)
                print(f'stsearch: Finshed pattern #{n} on all files...')

    return True
