#!/usr/bin/env python3

from typing import *

from argparse import ArgumentParser, FileType
from dataclasses import dataclass

from tools import Tool, Language, Path
from base import yaml


@dataclass
class Args:
    patterns: TextIO
    matches: TextIO
    paths: list[Path]


def add_args(parser: ArgumentParser):
    parser.add_argument('patterns', type=FileType('r'))
    parser.add_argument('matches', type=FileType('w'))
    parser.add_argument('--paths', nargs='+', type=Path, required=True)



def main(args: Args):
    from tools import runners

    items = list(yaml.safe_load_all(args.patterns))
    yaml.safe_dump_all(collect(runners, items, args.paths),
                       args.matches, sort_keys=False)


def collect(tools: dict[str, Tool], items: Sequence[dict], paths: Sequence[Path]) -> Iterable[dict]:
    def patterns_for(name: str) -> Iterable[tuple[str, str]]:
        return ((item['language'], item['pattern'][name]) for item in items)

    # We give all the patterns to the tool to allow for parsing optimization
    all_results = {name: tool(patterns_for(name), paths)
                   for name, tool in tools.items()}

    # However, we then aggregate the results per pattern for a direct comparison
    for item, *tool_results in zip(items, *all_results.values(), strict=True):
        pattern: dict[str, str] = item['pattern']
        language: Language = item['language']

        yield {
            'language': language,
            'pattern': pattern,
            'results': {name: results for name, results
                        in zip(all_results.keys(), tool_results, strict=True)},
        }


if __name__ == '__main__':
    parser = ArgumentParser()
    add_args(parser)

    main(parser.parse_args())
