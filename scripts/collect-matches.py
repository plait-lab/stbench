#!/usr/bin/env python3

from typing import *

import re

from dataclasses import dataclass, field

from tools import Tool, Language, Path
from base import Args, Arg, load_all, dump_all


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

    patterns: list[TPattern] = [(item['language'], item['pattern'])
                                for item in load_all(args.patterns)]

    dump_all(({'language': lang, 'pattern': pattern, 'results': results} for (lang, pattern), results
              in zip(patterns, collect(runners, patterns, args.paths))), args.matches)


T = TypeVar('T')
PerTool: TypeAlias = Mapping[str, T]
TPattern: TypeAlias = tuple[Language, PerTool[str]]


def collect(tools: PerTool[Tool], patterns: Sequence[TPattern], paths: Collection[Path]) -> Iterable[PerTool[list[Match]]]:
    def patterns_for(name: str) -> Iterable[tuple[str, str]]:
        return ((language, tools[name]) for language, tools in patterns)

    # We give all the patterns to the tool to allow for parsing optimization
    all_results = {name: tool(patterns_for(name), paths)
                   for name, tool in tools.items()}

    # However, we then aggregate the results per pattern for a direct comparison
    for results in zip(*all_results.values(), strict=True):
        yield dict(zip(tools.keys(), results))


if __name__ == '__main__':
    main(CLI.parser().parse_args())
