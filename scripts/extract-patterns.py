#!/usr/bin/env python3

from typing import *

import re
import yaml

from dataclasses import dataclass, field

from tools import semgrep, stsearch, Language, Path
from base import Args, Arg, dump_all


@dataclass
class CLI(Args):
    out: TextIO = field(metadata=Arg(mode='w'))
    mode: str = field(metadata=Arg(choices=['semgrep']))
    languages: list[Language] = field(metadata=Arg(flags=['--lang', '-l'], action='append'))
    rules: list[Path]


def main(args: CLI):
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
                        canon = semgrep.canonical(pattern)
                        out[language, canon][path].append(key)

    print(f'Collected {len(out)} atomic patterns.')
    dump_all(({
        'language': language,
        'pattern': {'semgrep': pattern, 'stsearch': stsearch.from_semgrep(pattern)},
        'source': [{'path': path, 'keys': keys} for path, keys in paths.items()],
    } for (language, pattern), paths in out.items()), args.out)


def pattern_items(path: list[str], languages: list[str], operator: dict) -> Iterable['PatternItem']:
    # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
    match operator:
        case [*patterns]:
            for i, pattern in enumerate(patterns):
                yield from pattern_items(path + [f'{i}'], languages, pattern)

        case {'pattern': pattern} | {'pattern-not': pattern} \
                | {'pattern-inside': pattern} | {'pattern-not-inside': pattern}:
            yield PatternItem('.'.join(path), semgrep.DEEP.sub('...', semgrep.STRMATCH.sub('"..."', pattern)))
            patterns = [{'pattern': m.group('inner')}
                        for m in semgrep.DEEP.finditer(pattern)]
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


if __name__ == '__main__':
    main(CLI.parser().parse_args())
