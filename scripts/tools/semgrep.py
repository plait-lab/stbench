from typing import *

import re

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from tools import db
from tools.common import Language


METAVAR = re.compile(r'(?P<name>\$(?P<kind>(\.{3})?)[A-Z0-9_]+)')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#typed-metavariables
TYPMETAVAR = re.compile(r'\(\s*(?P<metavar>\$[A-Z_]+)\s*:[^\(\)]+\)')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#string-matching
STRMATCH = re.compile(r'"=~\/([^/]|\\\/)*\/"')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#deep-expression-operator
DEEP = re.compile('<\.{3}(?P<inner>.*?)\.{3}>')


def canonical(pattern: str) -> str:
    # FIX: generalize to more languages
    pattern = pattern.strip()
    pattern = re.sub(r'[^\S\n\r]+', ' ', pattern)  # collapse whitespace
    pattern = re.sub(r'\n(\r?)\s*\n\r?', r'\n\1', pattern)  # and empty lines
    pattern = TYPMETAVAR.sub(lambda m: m['metavar'], pattern)

    def metavar(name=None, kind=''):
        metavars.append(name)
        return f'${kind}H{len(metavars)}'
    metavars = []

    pattern = METAVAR.sub(
        lambda m: metavar(m['name'], m['kind']), pattern)

    # Sometimes generated when extracting deep patterns
    redundant_ellipsis = re.compile(r'\.{3}\s*(,|\n)\s*\.{3}')
    while True:  # needed to replace overlapping matches
        (pattern, n) = redundant_ellipsis.subn('...', pattern)
        if not n:
            break

    # Remove most ambiguous unbounded ellipsis
    pattern = re.sub(r'=\s*\.{3}$', f'= {metavar()}', pattern).strip()
    pattern = re.sub(r'^\.{3}\s*(?!\.)|(?<!\.)\s*\.{3}$', '', pattern).strip()

    # Remove trivial deep expr for statement semantics
    if pattern.endswith(';') and pattern.count(';') == 1 and '\n' not in pattern:
        pattern = pattern.removesuffix(';')  # i.e. just match the expression

    return pattern


def register():
    tool, _ = db.Tool.get_or_create(name='semgrep')
    return tool


def run(experiment: str, roots: Sequence[Path]) -> Literal[True]:
    import yaml

    from tempfile import NamedTemporaryFile as TempFile, TemporaryDirectory as TempDir
    from operator import itemgetter

    with db.transact():
        experiment = db.Experiment.get(name=experiment)

        tool = register()
        queries = list(experiment.queries
                       .select(db.Query, db.Language)
                       .join_from(db.Query, db.Language))
        languages = set(Language(q.language.name) for q in queries)
        files = {f.path: f for f in experiment.files}

    print(f'semgrep: Filtering invalid patterns...')
    with TempDir() as empty:
        for language in languages:
            Path(empty, f'empty{language.exts()[0]}').touch()

        def validate(id: int, language: str, pattern: str) -> Optional[dict]:
            output = semgrep_scan([f'--lang={language}', f'--pattern={pattern}', empty],
                                  stderr=False, repro=False)
            if any('Pattern parse error' in err['message'] for err in output['errors']):
                return None  # mark invalid, use placeholder
            return semgrep_rule(f'{id:04d}', language, pattern)

        with ThreadPoolExecutor() as tp:
            rules = list(tp.map(lambda args: validate(*args),
                                ((i, q.language.name, q.pattern) for i, q in enumerate(queries))))

    invalid = [queries[i] for i, r in enumerate(rules) if r is None]
    print(f'semgrep: Dropped {len(invalid)} invalid rules for semgrep.')

    # FIX: not guaranteed to "reopen" according to docs
    with TempFile('w', suffix='.yaml') as config:
        valid = [r for r in rules if r is not None]
        yaml.safe_dump({'rules': valid}, config, sort_keys=False)
        config.flush()  # ensure it's written to disk

        includes = [f'--include=*{ext}' for l in languages for ext in l.exts()]

        def worker(root: Path):
            print(f'semgrep: Running with all patterns on root: {root}')

            # let semgrep discover the paths
            output = semgrep_scan([*includes, root], config=config)

            for error in output['errors']:
                print(f"WARNING: semgrep: unexpected error {error['message']}")

            # Check selected files agreement
            expected = set(p for p in files if p.startswith(str(root)))
            scanned = set(output['paths']['scanned'])
            for path in scanned - expected:
                print(f'WARNING: semgrep: unexpectedly scanned {path}')
            for path in expected - scanned:
                print(f'WARNING: semgrep: unexpectedly skipped {path}')

            with db.transact():
                runs = [{path: db.Run(tool=tool, query=query, file=files[path])
                        for path in scanned & expected}
                        for query in queries]
                db.Run.bulk_create((r for rs in runs for r in rs.values()),
                                   batch_size=1000)

                def transform(result: dict) -> Optional[tuple]:
                    if m := re.match(r'search-(\d+)', result['check_id']):
                        id = int(m.group(1))  # extract rule index
                        assert result['extra']['message'] == rules[id]['message']
                        assert result['extra']['severity'] == rules[id]['severity']
                        if result['extra']['is_ignored']:
                            print(f'WARNING: semgrep: unexpectedly ignored {result}')

                        path, start, end = itemgetter('path', 'start', 'end')(result)
                        (sr, sc), (er, ec) = map(itemgetter('line', 'col'), (start, end))

                        if path in expected:
                            return (runs[id][path], sr, sc, er, ec)
                    else:
                        print(f'WARNING: semgrep: unexpected result {result}')

                db.Result.bulk_insert(filter(None, map(transform, output.pop('results'))),
                                      ('run', 'sr', 'sc', 'er', 'ec'))

            print(f'semgrep: Finished all patterns on root: {root}')

        with ThreadPoolExecutor(4) as tp:
            return all(tp.map(worker, roots))


def semgrep_scan(args: list[str], *, config: Optional[TextIO] = None, stderr=True, repro=True) -> dict:
    import shutil
    import subprocess
    import json

    stderr = None if stderr else subprocess.DEVNULL

    try:
        flags = [f'--config={config.name}'] if config else []
        flags.extend(semgrep_extra_flags())

        output = subprocess.check_output(['semgrep', 'scan', *flags, '--json', *args],
                                         text=True, stderr=stderr)

    except subprocess.CalledProcessError as err:
        if repro:
            if config:
                shutil.copy2(config.name, (tmp := Path('/tmp/config.yaml')))
                print(f'semgrep: Copied temporary config file to {tmp}')
                err.cmd[2] = f'--config={tmp}'  # easier to rerun
            print(f'ERROR: semgrep: $ {subprocess.list2cmdline(err.cmd)}')
        output = err.output

    return json.loads(output)


def semgrep_rule(id: str, language: str, pattern: str) -> dict:
    # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
    return {
        'id': f'search-{id}',
        'message': 'result',
        'severity': 'INFO',
        'languages': [language],
        'pattern': pattern,
        'options': {
            # Disable known unsupported features
            # See: https://semgrep.dev/docs/writing-rules/rule-syntax/#options
            'ac_matching': False,
            'constant_propagation': False,
            # See: https://github.com/returntocorp/semgrep/blob/develop/interfaces/Config_semgrep.atd
            'vardef_assign': False,
            'attr_expr': False,
            'arrow_is_function': False,
            'let_is_var': False,
            'go_deeper_expr': False,
            'go_deeper_stmt': False,
            'implicit_deep_exprstmt': False,
            'implicit_ellipsis': False,
        },
    }


def semgrep_extra_flags() -> list[str]:
    # See: https://semgrep.dev/docs/cli-reference/#semgrep-scan-options
    return [
        # Try to optimize performance
        '--metrics=off',
        '--no-git-ignore',
        '--disable-version-check',
        # Prevent changing the id
        '--no-rewrite-rule-ids',
        # Disable silencing matches
        '--disable-nosem',
        # Include all info in output
        '--verbose',
        # Ensure reproducibility
        '--oss-only',
    ]


def ignored(path: Path) -> bool:
    DIRECTORIES = [
        'node_modules', 'build', 'dist', 'vendor',
        '.env', '.venv', '.tox', '.npm',
        'test', 'tests',
        '.semgrep', '.semgrep_logs'
    ]

    SUFFIXES = [
        '.min.js', '_test.go'
    ]

    return not any(d in path.parents for d in DIRECTORIES) \
        and not any(path.name.endswith(s) for s in SUFFIXES)
