from typing import *


from tools.common import Language, Match, Path


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


def run(patterns: Iterable[tuple[Language, str]], paths: Sequence[Path]) -> Iterable[Sequence[Match]]:
    import subprocess
    from tools.common import select_files

    expanded = {}

    for i, (language, pattern) in enumerate(patterns):
        files = expanded.get(language)
        if files is None:
            files = expanded[language] = select_files([language], paths)

        print(f'Running stsearch with pattern #{i+1} on all paths...')

        results = []
        for file in files:
            try:
                process = subprocess.run(['stsearch', language.name, pattern, file],
                                         capture_output=True, check=True, text=True)
            except subprocess.CalledProcessError as err:
                print(f'error$ {subprocess.list2cmdline(err.cmd)}')
                continue

            results.extend(map(Match.parse, process.stdout.splitlines()))

        yield results
