#!/usr/bin/env python3

from typing import *

import re

from pathlib import Path
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor

from base import Args, Arg, load_all


@dataclass
class CLI(Args):
    experiment: str
    matches: Path
    patterns: TextIO = field(metadata=Arg(mode='r'))
    paths: list[Path] = field(metadata=Arg(flags=['--paths']))
    tools: Optional[str] = field(metadata=Arg(flags=['--tools']))


def main(args: CLI):
    from tools import all as tools, db, select_files
    from tools.stsearch import from_semgrep as to_st

    if args.tools:
        tools = {name: tools[name] for name in tools
                 if re.fullmatch(args.tools, name)}
        print(f"Selected tools: {', '.join(tools)}")

    db.init(args.matches)
    with db.transact():
        experiment = db.Experiment.create(name=args.experiment)

        language = None
        languages = set()
        for item in load_all(args.patterns):
            if not language or language.name != item['language']:
                language, _ = db.Language.get_or_create(name=item['language'])
            languages.add(item['language'])

            pattern = item['pattern']['semgrep']
            assert to_st(pattern) == item['pattern']['stsearch']

            query, _ = db.Query.get_or_create(language=language,
                                              pattern=pattern)
            experiment.queries.add(query)

        for path in select_files(languages, args.paths):
            file, _ = db.File.get_or_create(path=path)
            experiment.files.add(file)

        for tool in tools.values():
            experiment.tools.add(tool.register())

    with ThreadPoolExecutor() as tp:
        all(tp.map(lambda tool: tool.run(args.experiment, args.paths),  tools.values()))


if __name__ == '__main__':
    main(CLI.parser().parse_args())
