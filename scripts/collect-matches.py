#!/usr/bin/env python3

from typing import *

import subprocess
import json
import yaml

from argparse import ArgumentParser, FileType
from dataclasses import dataclass

from pathlib import Path

from base import *


@dataclass
class Args:
    patterns: TextIO
    matches: TextIO
    test: bool


def add_args(parser: ArgumentParser):
    parser.add_argument('patterns', type=FileType('r'))
    parser.add_argument('matches', type=FileType('w'))
    parser.add_argument('--test', action='store_true', required=True)


def main(args: Args):
    assert args.test

    items = yaml.safe_load_all(args.patterns)
    yaml.safe_dump_all(collect(items), args.matches, sort_keys=False)


def collect(items: Iterable[dict]) -> Iterable[dict]:
    skip = set()

    for item in items:
        pattern: dict[str, str] = item['pattern']
        language: Language = item['language']

        paths = []
        for location in item['sources']:
            source = Path(location['path'])
            if source in skip:
                continue

            tests = [test for test
                     in map(source.with_suffix, language.exts())
                     if test.exists()]

            if not tests:
                print(f'{source}'
                      f': no {language.exts()} file found')
                skip.add(source)
                continue

            paths.extend(tests)

        if paths:
            yield {
                'language': language,
                'pattern': pattern,
                'paths': paths,
                'results': {
                    'stsearch': list(stsearch(language, pattern['stsearch'], paths)),
                    'semgrep': list(semgrep(language, pattern['semgrep'], paths)),
                }
            }


def stsearch(language: Language, pattern: str, paths: list[Path]) -> Iterable[Range]:
    for path in paths:
        try:
            process = subprocess.run(['stsearch', language.name, pattern, path],
                                     capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as err:
            print(f"error$ {subprocess.list2cmdline(err.cmd)}")
            continue

        for line in process.stdout.splitlines():
            yield Match.parse(line)


def semgrep(language: Language, pattern: str, paths: list[Path]) -> Iterable[Range]:
    from tempfile import NamedTemporaryFile as TempFile
    from operator import itemgetter

    # FIX: not guaranteed to "reopen" according to docs
    with TempFile('w', suffix='.yaml') as config:
        rule = semgrep_rule(language, pattern)
        yaml.safe_dump({'rules': [rule]}, config, sort_keys=False)
        config.flush()  # ensure it's written to disk

        try:
            process = subprocess.run(['semgrep', 'scan', f'--config={config.name}', *semgrep_extra_flags(), '--json', *paths],
                                     capture_output=True, check=True, text=True)
        except subprocess.CalledProcessError as err:
            print(f"error$ {subprocess.list2cmdline(err.cmd)}")
            with (tmp := Path('/tmp/config.yaml')).open('w') as f:
                yaml.safe_dump({'rules': [rule]}, f, sort_keys=False)
                print(f'Saved temporary config file to {tmp}')
            return

        output = json.loads(process.stdout)
        assert not output['errors'], 'rule severity is info'
        assert set(paths) == set(map(Path, output['paths']['scanned']))
        assert not output['paths']['skipped']

        for result in output['results']:
            assert result['check_id'] == rule['id']
            assert not result['extra']['is_ignored']
            assert result['extra']['message'] == rule['message']
            assert result['extra']['severity'] == rule['severity']

            path, start, end = itemgetter('path', 'start', 'end')(result)
            (sr, sc), (er, ec) = map(itemgetter('line', 'col'), (start, end))
            yield Match(Path(path), Range(Point(sr, sc), Point(er, ec)))


def semgrep_rule(language: Language, pattern: str) -> dict:
    # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
    return {
        'id': 'search',
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
        '--no-rewrite-rule-ids',
        # Disable silencing matches
        '--disable-nosem',
        # Include all info in output
        '--verbose',
    ]


if __name__ == '__main__':
    parser = ArgumentParser()
    add_args(parser)

    main(parser.parse_args())
