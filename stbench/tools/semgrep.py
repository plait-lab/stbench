from typing import Optional, Iterable, Sequence

import json
import logging
import re
import subprocess

from operator import itemgetter
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

from . import Language, Query, Match, Range


METAVAR = re.compile(r'(?P<name>\$(?P<kind>(\.{3})?)[A-Z0-9_]+)')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#typed-metavariables
TYPMETAVAR = re.compile(r'\(\s*(?P<metavar>\$[A-Z_]+)\s*:[^\(\)]+\)')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#string-matching
STRMATCH = re.compile(r'"=~\/([^/]|\\\/)*\/"')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#deep-expression-operator
DEEP = re.compile(r'<\.{3}(?P<inner>.*?)\.{3}>')


def rules(source: Path) -> Iterable[tuple[Path, dict]]:
    if source.is_file() and source.suffix == '.yaml':
        logging.debug(f'config: {source}')
        with source.open() as file:
            config: dict = yaml.safe_load(file)
            for rule in config['rules']:
                name = rule['id']
                if (msg := rule.get('message')) and re.search('rule (is|has been) deprecated', msg):
                    logging.warn(f'{name}: deprecated')
                    continue  # skip
                logging.debug(f'rule: {name}')
                yield source, rule
    elif source.is_dir():
        for entry in source.iterdir():
            yield from rules(entry)


def patterns(rule: dict, languages: Optional[set[Language]] = None) -> Iterable[Query]:
    '''Given a Semgrep config, rule, or operator, extract all (shallow) patterns.'''

    if (specified := rule.get('languages')):
        languages = {Language(l) for l in specified if Language.supports(l)}

    # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
    match rule:
        case {'rules': [*rules]}:
            for nested in rules:
                yield from patterns(nested, languages)

        case {'pattern': nested} | {'pattern-not': nested} \
                | {'pattern-inside': nested} | {'pattern-not-inside': nested}:
            for language in languages or ():
                yield Query(language, DEEP.sub('...', STRMATCH.sub('"..."', nested)))

            for m in DEEP.finditer(nested):
                yield from patterns({'pattern': m.group('inner')}, languages)

        case {'metavariable-pattern': {'metavariable': _} as nested}:
            if not (l := nested.get('language')) or (Language.supports(l) and (languages := {Language(l)})):
                yield from patterns(nested, languages)

        case {'patterns': rules} | {'pattern-either': rules}:
            for nested in rules:
                yield from patterns(nested, languages)

        # See: https://semgrep.dev/docs/writing-rules/metavariable-analysis/
        case {'focus-metavariable': _} \
                | {'pattern-regex': _} | {'pattern-not-regex': _} \
                | {'metavariable-regex': {'metavariable': _, 'regex': _}} \
                | {'metavariable-comparison': {'metavariable': _, 'comparison': _}} \
                | {'metavariable-analysis': {'metavariable': _, 'analyzer': _}}:
            pass  # ignored

        # See: https://semgrep.dev/docs/writing-rules/data-flow/taint-mode/
        case {'pattern-sources': sources, 'pattern-sinks': sinks}:
            for rules in (sources, sinks):
                for nested in rules:
                    yield from patterns(nested, languages)

            for opt in ('pattern-propagators', 'pattern-sanitizers'):
                if rules := rule.get(opt):
                    for nested in rules:
                        yield from patterns(nested, languages)

        case None:  # optional rule
            pass

        case _:
            raise NotImplementedError('rule not identified')


def canonical(query: Query) -> Query:
    '''Given a Semgrep pattern, normalize spacing/naming & remove ambiguity.'''
    language, pattern = query

    # FIX: generalize to more languages
    assert query.language.name == 'javascript'

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

    if query.syntax != pattern:
        logging.debug(f'canonical: {query.syntax!r} => {pattern!r}')

    return query._replace(syntax=pattern)


def run(queries: list[Query], project: Path | str, files: Sequence[Path | str]) -> Iterable[tuple[Query, Match]]:
    rules = [rule(str(i), q) for i, q in enumerate(queries)]
    languages = {q.language for q in queries}

    with NamedTemporaryFile('w', suffix='.yaml') as config:
        yaml.safe_dump({'rules': rules}, config, sort_keys=False)
        config.flush()

        cmd = ['semgrep', 'scan', project, f'--config={config.name}', *FLAGS]
        logging.debug(f'$ {subprocess.list2cmdline(cmd)}')

        try:
            output = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as err:
            logging.error(f'semgrep: {err}')
            output = err.output

        data = json.loads(output)

        for error in data.pop('errors'):
            logging.error(f'semgrep: unexpected error:' + error['message'])

        expected = set(map(str, files))
        for path in expected.difference(data.pop('paths')['scanned']):
            logging.warning(f'semgrep: unexpectedly skipped {path}')

        for result in data.pop('results'):
            i = int(result['check_id'])  # used id to track index
            path, start, end = itemgetter('path', 'start', 'end')(result)
            (sr, sc), (er, ec) = map(itemgetter('line', 'col'), (start, end))

            if path in expected:
                yield (queries[i], Match(path, Range(sr, sc, er, ec)))


def rule(id: str, query: Query) -> dict:
    includes = [f'*{ext}' for ext in query.language.exts()]
    return {
        # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
        'id': id,
        'message': 'result',
        'severity': 'INFO',
        'languages': [query.language.name],
        'pattern': query.syntax,
        'paths': {'include': includes},
        'options': OPTIONS.copy(),
    }


# Disable known unsupported features
OPTIONS = {
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
}


# See: https://semgrep.dev/docs/cli-reference/#semgrep-scan-options
FLAGS = [
    '--json',
    # Track queries through ids
    '--no-rewrite-rule-ids',
    # Everything must be reported
    '--disable-nosem',
    '--verbose',
    # For performance
    '--metrics=off',
    '--no-git-ignore',
    '--disable-version-check',
    # For reproducibility
    '--oss-only',
]
