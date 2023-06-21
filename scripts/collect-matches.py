#!/usr/bin/env python3

from typing import *

import re

from dataclasses import dataclass, field

from tools import Tool, Language, Path
from base import Args, Arg, yaml


@dataclass
class CLI(Args):
    patterns: TextIO = field(metadata=Arg(mode='r'))
    matches: TextIO = field(metadata=Arg(mode='w'))
    paths: list[Path] = field(metadata=Arg(flags=['--paths']))
    tools: Optional[str] = field(metadata=Arg(flags=['--tools']))


def main(args: CLI):
    from tools import runners

    if args.tools:
        runners = {name: runners[name] for name in runners
                   if re.fullmatch(args.tools, name)}
        print(f"Selected tools: {', '.join(runners)}")

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
    main(CLI.parser().parse_args())
