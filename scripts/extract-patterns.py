#!/usr/bin/env python3

from typing import *

import re
import yaml

from argparse import ArgumentParser, FileType
from dataclasses import dataclass
from pathlib import Path

from base import *


@dataclass
class Args:
    out: TextIO
    mode: str
    rules: list[Path]
    languages: list[Language]


def add_args(parser: ArgumentParser):
    parser.add_argument('out', type=FileType('w'))
    parser.add_argument('mode', choices=['semgrep'])
    parser.add_argument('rules', nargs='+', metavar='rule', type=Path)
    parser.add_argument('--lang', '-l', action='append', type=Language,
                        dest='languages', required=True)


def main(args: Args):
    from collections import defaultdict

    assert args.mode == 'semgrep'

    out = defaultdict(lambda: defaultdict(list))

    print(f'Loaded {len(args.rules)} {args.mode} patterns.')
    for path in sorted(args.rules):
        with path.open() as f:
            config = yaml.safe_load(f)
            for rule in config['rules']:
                if re.search('rule (is|has been) deprecated', rule['message']):
                    print(f"{path}:{rule['id']}: "
                          f"deprecated")
                    continue

                languages = {Language(l) for l in rule['languages']
                             if Language.supports(l)}

                if languages.isdisjoint(args.languages):
                    print(f"{path}:{rule['id']}: "
                          f"{rule['languages']} not selected")
                    continue

                for (key, pattern) in pattern_items([rule['id']], args.languages, rule):
                    for language in languages.intersection(args.languages):
                        out[language, canonical(pattern)][path].append(key)

    print(f'Collected {len(out)} atomic patterns.')
    yaml.safe_dump_all(({
        'language': language,
        'pattern': {'semgrep': pattern, 'stsearch': to_st(pattern)},
        'source': [{'path': path, 'keys': keys} for path, keys in paths.items()],
    } for (language, pattern), paths in out.items()), args.out, sort_keys=False)


def to_st(pattern: str) -> str:
    # TODO: stsearch doesn't use metavar names or support named ellipsis
    # https://semgrep.dev/docs/writing-rules/pattern-syntax/#ellipsis-metavariables
    pattern = METAVAR.sub(
        lambda m: '...' if m['kind'] == '...' else '$_', pattern)

    # FIX: generalize to more languages
    pattern = re.sub(r',?(\s*\.{3}\s*),?', r'\1', pattern)
    pattern = re.sub(r'(?<!\.)\.\s*(\.{3}\s*\.)(?!\.)', r'\1', pattern)

    return pattern


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


def pattern_items(path: list[str], languages: list[str], operator: dict) -> Iterable['PatternItem']:
    # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
    match operator:
        case [*patterns]:
            for i, pattern in enumerate(patterns):
                yield from pattern_items(path + [f'{i}'], languages, pattern)

        case {'pattern': pattern} | {'pattern-not': pattern} \
                | {'pattern-inside': pattern} | {'pattern-not-inside': pattern}:
            yield PatternItem('.'.join(path), DEEP.sub('...', STRMATCH.sub('"..."', pattern)))
            patterns = [{'pattern': m.group('inner')}
                        for m in DEEP.finditer(pattern)]
            yield from pattern_items(path, languages, patterns)

        case {'metavariable-pattern': {'metavariable': _} as pattern}:
            if not (l := pattern.get('language')) or (Language.supports(l) and Language(l) in languages):
                yield from pattern_items(path + ['meta'], languages, pattern)

        case {'patterns': patterns} | {'pattern-either': patterns}:
            yield from pattern_items(path, languages, patterns)

        # See: https://semgrep.dev/docs/writing-rules/metavariable-analysis/
        case {'focus-metavariable': _} \
                | {'pattern-regex': _} | {'pattern-not-regex': _} \
                | {'metavariable-regex': {'metavariable': _, 'regex': _}} \
                | {'metavariable-comparison': {'metavariable': _, 'comparison': _}} \
                | {'metavariable-analysis': {'metavariable': _, 'analyzer': _}}:
            pass  # ignored

        # See: https://semgrep.dev/docs/writing-rules/data-flow/taint-mode/
        case {'pattern-sources': sources, 'pattern-sinks': sinks}:
            yield from pattern_items(path + ['sources'], languages, sources)
            yield from pattern_items(path + ['sinks'], languages, sinks)
            yield from pattern_items(path + ['propagators'], languages, operator.get('pattern-propagators'))
            yield from pattern_items(path + ['sanitizers'], languages, operator.get('pattern-sanitizers'))

        case None:  # optional operator
            pass

        case _:
            raise NotImplementedError('operator not identified')


class PatternItem(NamedTuple):
    key: str
    pattern: str


METAVAR = re.compile(r'(?P<name>\$(?P<kind>(\.{3})?)[A-Z0-9_]+)')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#typed-metavariables
TYPMETAVAR = re.compile(r'\(\s*(?P<metavar>\$[A-Z_]+)\s*:[^\(\)]+\)')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#string-matching
STRMATCH = re.compile(r'"=~\/([^/]|\\\/)*\/"')
# See: https://semgrep.dev/docs/writing-rules/pattern-syntax/#deep-expression-operator
DEEP = re.compile('<\.{3}(?P<inner>.*?)\.{3}>')


if __name__ == '__main__':
    parser = ArgumentParser()
    add_args(parser)

    main(parser.parse_args())
