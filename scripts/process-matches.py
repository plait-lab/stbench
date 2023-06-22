#!/usr/bin/env python3

from typing import *

import re

from csv import DictWriter
from dataclasses import dataclass, field

from base import Args, Arg, yaml


@dataclass
class CLI(Args):
    data: TextIO = field(metadata=Arg(mode='r'))
    results: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    agg = DictWriter(args.results, ['pattern', 'miss', 'extra', 'semgrep', 'stsearch'])
    agg.writeheader()

    for run in yaml.safe_load_all(args.data):
        results = run['results']

        stsearch = set(results['stsearch'])

        results['semgrep'] = list(fix_all(results['semgrep'], stsearch))
        semgrep = set(results['semgrep'])

        agg.writerow(dict(
            pattern=run['pattern']['semgrep'],
            miss=len(semgrep - stsearch),
            extra=len(stsearch - semgrep),
            semgrep=len(semgrep),
            stsearch=len(stsearch),
        ))


def fix_all(results: Iterable[Match], reference: set[Match]) -> Iterable[Match]:
    for result in results:
        yield fix(result, reference)


def fix(result: Match, reference: set[Match]) -> Match:
    prefix, suffix = re.compile(r'(\(\s*)*'), re.compile(r'(\}?\`)?(\s*\))*')
    if result not in reference:
        for candidate in sorted(
            (c for c in reference if c.contains(result)),
            key=lambda c: c.range.adjusted(c.range.start).end
        ):
            start, context = candidate.range.start, candidate.text()
            span = result.range.adjusted(start).span(context)

            if prefix.fullmatch(context, 0, span.start) \
                    and suffix.fullmatch(context, span.stop):
                # print('EXTENDING MATCH')
                # print('FROM:', repr(context[span]))
                # print('  TO:', repr(context))
                return candidate
    return result


if __name__ == '__main__':
    main(CLI.parser().parse_args())
