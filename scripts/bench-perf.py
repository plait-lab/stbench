#!/usr/bin/env python3

from typing import *

from pathlib import Path
from dataclasses import dataclass, field

from base import Args, Arg, load_all


@dataclass
class CLI(Args):
    patterns: TextIO = field(metadata=Arg(mode='r'))
    paths: list[Path] = field(metadata=Arg(flags=['--paths']))
    metrics: TextIO = field(metadata=Arg(mode='w'))


def main(args: CLI):
    import subprocess
    from tools import Language, select_files

    files: dict[Language, Sequence[Path]] = {}

    args.metrics.write(','.join([
        'pattern',
        'file',
        'tree size',
        'tree depth',
        'query length',
        'hole count',
        'parse time',
        'search time',
    ]) + '\n')

    for i, item in enumerate(load_all(args.patterns)):
        language = item['language']
        pattern = item['pattern']['stsearch']

        if language not in files:
            files[language] = select_files([language], args.paths)

        for file in files[language]:
            process = subprocess.run(['stsearch', '--metrics', language.name, pattern, file],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                     text=True, check=True)

            args.metrics.write(f'{i+1},"{file}",')
            args.metrics.write(process.stderr)


if __name__ == '__main__':
    main(CLI.parser().parse_args())
