from typing import *

from pathlib import Path

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


def run(experiment: db.Experiment, roots: Sequence[Path]) -> Iterable[tuple[db.Run, int, int, int, int]]:
    import subprocess

    from tools.common import Language, Match

    def parse(s: str): return Match.parse(s.rstrip('\n'))

    tool = register()
    for i, query in enumerate(experiment.queries):
        print(f'Running stsearch with pattern #{i+1} on all paths...')

        language = Language(query.language.name)
        pattern = from_semgrep(query.pattern)

        for file in experiment.files:
            if any(file.path.endswith(ext) for ext in language.exts()):
                process = subprocess.Popen(['stsearch', language.name, pattern, file.path],
                                           text=True, stdout=subprocess.PIPE)

                with db.RESULTS.atomic() as txn:
                    run, _ = db.Run.get_or_create(
                        tool=tool, query=query, file=file)

                    for _, ((sr, sc), (er, ec)) in map(parse, process.stdout):
                        yield (run, sr, sc, er, ec)

                if process.wait():
                    print(f'error$ {subprocess.list2cmdline(process.args)}')
                    continue
