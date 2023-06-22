from typing import *

import re

from tools.common import Language, Match, Path


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
    pattern = re.sub(r'^\.{3}\s*\n|\n\s*\.{3}$', '', pattern).strip()
    pattern = re.sub(r'=\s*\.{3}$', f'= {metavar()}', pattern).strip()

    # Remove trivial deep expr for statement semantics
    if pattern.endswith(';') and pattern.count(';') == 1 and '\n' not in pattern:
        pattern = pattern.removesuffix(';')  # i.e. just match the expression

    return pattern


def run(patterns: Iterable[tuple[Language, str]], paths: Sequence[Path]) -> Iterable[Sequence[Match]]:
    import yaml

    from subprocess import CalledProcessError
    from tempfile import NamedTemporaryFile as TempFile, TemporaryDirectory as TempDir
    from operator import itemgetter

    from tools.common import Range, Point, select_files

    print(f'Filtering invalid semgrep patterns...')
    rules, invalid, languages = [], [], set()
    with TempDir() as empty:
        for id, (language, pattern) in enumerate(patterns):
            try:
                semgrep_scan([f'--lang={language.name}', f'--pattern={pattern}', empty], repro=False)
            except CalledProcessError as err:
                # https://semgrep.dev/docs/cli-reference/#exit-codes
                # Should use 4, but it uses 2 for some reason...
                if err.returncode != 2:
                    raise err
                rules.append(None)  # mark invalid, use placeholder
            else:
                rules.append(semgrep_rule(f'{id:04d}', language, pattern))
                languages.add(language)

    invalid = [i for i, r in enumerate(rules) if r is None]
    print(f'Dropped {len(invalid)} invalid rules for semgrep.')

    # FIX: not guaranteed to "reopen" according to docs
    with TempFile('w', suffix='.yaml') as config:
        valid = [r for r in rules if r is not None]
        yaml.safe_dump({'rules': valid}, config, sort_keys=False)
        config.flush()  # ensure it's written to disk

        print(f'Running semgrep with all patterns on all paths...')
        output = semgrep_scan([
            *(f'--include=*{ext}' for l in languages for ext in l.exts()),
            *paths
        ], config=config)

    for error in output['errors']:
        print(f"warning: semgrep error {error['message']}")

    # Check selected files agreement
    expected = set(select_files(languages, paths))
    scanned = set(Path(p) for p in output['paths']['scanned'])
    for path in scanned - expected:
        print(f'warning: semgrep unexpectedly scanned {path}')
    for path in expected - scanned:
        print(f'warning: semgrep unexpectedly skipped {path}')

    results = [[] for r in rules]
    for result in output['results']:
        if m := re.match(r'search-(\d+)', result['check_id']):
            id = int(m.group(1))  # extract rule index
            assert result['extra']['message'] == rules[id]['message']
            assert result['extra']['severity'] == rules[id]['severity']
            assert not result['extra']['is_ignored']

            path, start, end = itemgetter('path', 'start', 'end')(result)
            (sr, sc), (er, ec) = map(itemgetter('line', 'col'), (start, end))
            match = Match(Path(path), Range(Point(sr, sc), Point(er, ec)))
            results[id].append(match)
        else:
            print(f'warning: unexpected semgrep result {result}')

    yield from results


def semgrep_scan(args: list[str], *, config: Optional[TextIO] = None, repro=True) -> dict:
    import shutil
    import subprocess
    import json

    try:
        flags = [f'--config={config.name}'] if config else []
        flags.extend(semgrep_extra_flags())

        process = subprocess.run(['semgrep', 'scan', *flags, '--json', *args],
                                 capture_output=True, check=True, text=True)

    except subprocess.CalledProcessError as err:
        if repro:
            if config:
                shutil.copy2(config.name, (tmp := Path('/tmp/config.yaml')))
                print(f'Copied temporary config file to {tmp}')
                err.cmd[2] = f'--config={tmp}'  # easier to rerun
            print(f'error$ {subprocess.list2cmdline(err.cmd)}')
        raise err

    return json.loads(process.stdout)


def semgrep_rule(id: str, language: Language, pattern: str) -> dict:
    # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
    return {
        'id': f'search-{id}',
        'message': 'result',
        'severity': 'INFO',
        'languages': [language.name],
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
