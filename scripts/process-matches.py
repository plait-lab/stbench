#!/usr/bin/env python3

from typing import *

from dataclasses import dataclass, field

from base import Args, Arg, yaml


@dataclass
class CLI(Args):
    data: TextIO = field(metadata=Arg(mode='r'))


def main(args: CLI):
    total = 0
    extra = []
    miss = []

    for run in yaml.safe_load_all(args.data):
        results = run['results']

        stsearch = set(results['stsearch'])

        results['semgrep'] = list(fix_all(results['semgrep'], stsearch))
        semgrep = set(results['semgrep'])

        total += 1
        extra.append(len(stsearch - semgrep) / len(stsearch)
                     if stsearch else 0)
        miss.append(len(semgrep - stsearch) / len(semgrep)
                    if semgrep else 0)

    aggregate: dict[str, tuple[int | str, float | str]] = {
        'total': (total, 1),
    }

    for name, metric, pcts in [
        ('extra', 'precision', extra),
        ('miss', 'sensitivity', miss),
    ]:
        for label, count in [
            (f'no {name}', pcts.count(0)),
            (f'all {name}', pcts.count(1)),
        ]:
            aggregate[label] = (count, count / total)

        avg = sum(pcts) / total
        aggregate[f'avg {name}'] = ('', avg)
        aggregate[metric] = ('', 1 - avg)

    prec, sens = aggregate['precision'][1], aggregate['sensitivity'][1]
    aggregate['f1'] = ('', 2 * prec * sens / (prec + sens))

    for name, (count, pct) in aggregate.items():
        print(f'{name:12}| {count:>6} | {100 * pct:>10.4f}%')


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
