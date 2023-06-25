#!/usr/bin/env python3

from typing import *

from dataclasses import dataclass, field

import pygments
from pygments.lexers import get_lexer_by_name
from pygments.token import Comment, Whitespace

from tools import stsearch
from base import Args, Arg, load_all, dump_all


@dataclass
class CLI(Args):
    complete: TextIO = field(metadata=Arg(mode='r'))
    partial: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    from collections import defaultdict

    out = defaultdict(list)

    for item in load_all(args.complete):
        language, complete = item['language'], item['pattern']['semgrep']

        lexer = get_lexer_by_name(language.name)
        tokens = list(pygments.lex(complete, lexer))

        partial = ''
        for typ, val in tokens:
            partial += val
            if typ not in Comment and typ not in Whitespace and val != '...':
                out[(language, partial)].append(complete)

    print(f"Computed {len(out)} partial patterns.")
    dump_all(({
        'language': language,
        'pattern': {'semgrep': pattern, 'stsearch': stsearch.from_semgrep(pattern)},
        'complete': complete,
    } for (language, pattern), complete in out.items()), args.partial)


if __name__ == '__main__':
    main(CLI.parser().parse_args())
