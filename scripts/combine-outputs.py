#!/usr/bin/env python3

from typing import *

from itertools import chain, starmap, pairwise

from dataclasses import dataclass, field

from base import Args, Arg, yaml


@dataclass
class CLI(Args):
    mode: str = field(metadata=Arg(choices=['merge', 'cat']))
    files: list[TextIO] = field(metadata=Arg(mode='r'))
    out: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    streams = map(yaml.safe_load_all, args.files)

    match args.mode:
        case 'merge':
            combined = starmap(merge, zip(*streams))
        case 'cat':
            combined = chain.from_iterable(streams)

    yaml.safe_dump_all(combined, args.out)


def merge(*maps: dict[str]):
    result = {k: None for m in maps for k in m}

    for key in result:
        values = [m[key] for m in maps if key in m]

        if len(values) == 1:
            value, = values
        elif all(isinstance(v, dict) for v in values):
            value = merge(*values)
        elif all(isinstance(v, list) for v in values):
            value = [x for l in values for x in l]
        elif all(l == r for l, r in pairwise(values)):
            value = values[0]
        else:
            assert False, f'Could not merge key:{key} with values:{values}'

        result[key] = value

    return result


if __name__ == '__main__':
    main(CLI.parser().parse_args())
