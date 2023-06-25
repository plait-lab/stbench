#!/usr/bin/env python3

from typing import *

from itertools import chain, starmap, pairwise
from dataclasses import dataclass, field, make_dataclass

from base import Args, Arg, load_all, dump_all
from base import CustomTag, custom_tags, add_custom_tags


@dataclass
class CLI(Args):
    mode: str = field(metadata=Arg(choices=['merge', 'cat']))
    files: list[TextIO] = field(metadata=Arg(mode='r'))
    out: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    # Optimization: do not parse custom tags!
    add_custom_tags({name: dumb_tag(cls) for name, (cls, _parse)
                     in custom_tags.items()})

    streams = map(load_all, args.files)

    match args.mode:
        case 'merge':
            combined = starmap(merge, zip(*streams))
        case 'cat':
            combined = chain.from_iterable(streams)

    dump_all(combined, args.out)


def merge(*maps: dict[str]):
    result = {k: None for m in maps for k in m}

    for key in result:
        values = [m.pop(key) for m in maps if key in m]

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


def dumb_tag(cls: Type) -> CustomTag:
    Dummy = make_dataclass(f'Dummy{cls.__name__}', [('content', str)],
                           namespace={'__str__': lambda self: self.content})
    return (Dummy, Dummy)


if __name__ == '__main__':
    main(CLI.parser().parse_args())
