#!/usr/bin/env python3

from typing import *

from pathlib import Path
from dataclasses import dataclass, field

from tools import db
from base import Args, Arg


@dataclass
class CLI(Args):
    matches: Path
    skipped: TextIO = field(metadata=Arg(mode='r'))


def main(args: CLI):
    db.init(args.matches)

    with db.transact():
        for path in args.skipped.read().splitlines():
            db.File.get(path=path).delete_instance(recursive=True)

    print('done!')


if __name__ == '__main__':
    main(CLI.parser().parse_args())
