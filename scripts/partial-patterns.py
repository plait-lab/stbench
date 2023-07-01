#!/usr/bin/env python3

from typing import *

from dataclasses import dataclass, field

import pygments
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Whitespace

from tools import Language, stsearch, semgrep
from base import Args, Arg, load_all, dump_all


@dataclass
class CLI(Args):
    complete: TextIO = field(metadata=Arg(mode='r'))
    partial: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    out = all_partials([(item['language'], item['pattern']['semgrep'])
                        for item in load_all(args.complete)])
    print(f'Computed {len(out)} partial patterns.')

    dump_all(({
        'language': language,
        'pattern': {'semgrep': pattern, 'stsearch': stsearch.from_semgrep(pattern)},
        'complete': complete,
    } for (language, pattern), complete in out.items()), args.partial)


def all_partials(patterns: Collection[tuple[Language, str]]) -> Mapping[tuple[Language, str], str]:
    from collections import defaultdict

    out = defaultdict(list)

    for language, complete in patterns:
        for partial in partials(language, complete):
            if (language, partial) not in patterns:
                out[(language, partial)].append(complete)

    return out


def partials(language: Language, complete: str) -> Iterable[str]:
    lexer = get_lexer_by_name(language.name)
    tokens = list(pygments.lex(complete, lexer))

    partial = ''
    for typ, val in tokens[:-1]:
        partial += val
        if semgrep.canonical(partial) == partial:
            yield partial


if __name__ == '__main__':
    main(CLI.parser().parse_args())
