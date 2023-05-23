#!/usr/bin/env python3

from typing import *
import os
import subprocess
import shutil
import json
import yaml

from argparse import ArgumentParser, FileType
from dataclasses import dataclass

from pathlib import Path

from base import *


@dataclass
class Args:
    patterns: TextIO
    matches: TextIO
    paths: list[Path]


def add_args(parser: ArgumentParser):
    parser.add_argument("patterns", type=FileType("r"))
    parser.add_argument("matches", type=FileType("w"))
    parser.add_argument("--paths", nargs="+", type=Path, required=True)


def main(args: Args):
    assert args.paths

    tools = {
        # "semgrep": semgrep,
        "stsearch": stsearch,
    }

    items = list(yaml.safe_load_all(args.patterns))
    yaml.safe_dump_all(collect(tools, items, args.paths), args.matches, sort_keys=False)


def collect(
    tools: dict[str, "Tool"], items: Iterable[dict], paths: Sequence[Path]
) -> Iterable[dict]:
    def patterns_for(name: str):
        yield from ((item["language"], item["pattern"][name]) for item in items)

    # We give all the patterns to the tool to allow for parsing optimization
    all_results = {
        name: tool(patterns_for(name), paths) for name, tool in tools.items()
    }

    # However, we then aggregate the results per pattern for a direct comparison
    for item, *tool_results in zip(items, *all_results.values(), strict=True):
        pattern: dict[str, str] = item["pattern"]
        language: Language = item["language"]

        yield {
            "language": language,
            "pattern": pattern,
            "results": {
                name: results
                for name, results in zip(all_results.keys(), tool_results, strict=True)
            },
        }


Tool: TypeAlias = Callable[
    [Iterable[tuple[Language, str]], Sequence[Path]], Iterable[Sequence[Match]]
]


def get_recursive_paths(paths):
    result = []
    for path in paths:
        if os.path.isfile(path):
            result.append(path)
        elif os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                result.extend([Path(root, file) for file in files])
        else:
            print(f"Invalid path: {path}")
    return result


def stsearch(
    patterns: Iterable[tuple[Language, str]], paths: Sequence[Path]
) -> Iterable[Sequence[Match]]:
    for i, (language, pattern) in enumerate(patterns):
        print(f"Running stsearch with pattern #{i+1} on all paths...")

        results = []

        print(
            f"Parsing {len([p for p in get_recursive_paths(paths) if p.suffix in language.exts()])} files"
        )
        for path in get_recursive_paths(paths):
            if path.suffix in language.exts():
                try:
                    process = subprocess.run(
                        ["stsearch", language.name, pattern, path],
                        capture_output=True,
                        check=True,
                        text=True,
                    )
                except subprocess.CalledProcessError as err:
                    print(f"error$ {subprocess.list2cmdline(err.cmd)}")
                    continue

                results.extend(map(Match.parse, process.stdout.splitlines()))

        yield results


def semgrep(
    patterns: Iterable[tuple[Language, str]], paths: Sequence[Path]
) -> Iterable[Sequence[Match]]:
    from tempfile import NamedTemporaryFile as TempFile
    from operator import itemgetter

    rules = [
        semgrep_rule(str(id), language, pattern)
        for id, (language, pattern) in enumerate(patterns)
    ]

    # FIX: not guaranteed to "reopen" according to docs
    with TempFile("w", suffix=".yaml") as config:
        yaml.safe_dump({"rules": rules}, config, sort_keys=False)
        config.flush()  # ensure it's written to disk

        try:
            print(f"Running semgrep with all patterns on all paths...")
            process = subprocess.run(
                [
                    "semgrep",
                    "scan",
                    f"--config={config.name}",
                    f"--include=*.js",
                    f"--include=*.cjs",
                    f"--include=*.mjs",
                    *semgrep_extra_flags(),
                    "--json",
                    *paths,
                ],
                capture_output=True,
                check=True,
                text=True,
            )
        except subprocess.CalledProcessError as err:
            print(f"error$ {subprocess.list2cmdline(err.cmd)}")
            shutil.copy2(config, (tmp := Path("/tmp/config.yaml")))
            print(f"Copied temporary config file to {tmp}")
            return

    output = json.loads(process.stdout)
    assert not output["errors"], "rule severity is info"
    # assert set(paths) == set(map(Path, output["paths"]["scanned"]))
    # assert not output["paths"]["skipped"]

    results = [[] for r in rules]
    for result in output["results"]:
        id = int(result["check_id"])
        assert not result["extra"]["is_ignored"]
        assert result["extra"]["message"] == rules[id]["message"]
        assert result["extra"]["severity"] == rules[id]["severity"]

        path, start, end = itemgetter("path", "start", "end")(result)
        (sr, sc), (er, ec) = map(itemgetter("line", "col"), (start, end))
        match = Match(Path(path), Range(Point(sr, sc), Point(er, ec)))
        results[id].append(match)

    yield from results


def semgrep_rule(id: str, language: Language, pattern: str) -> dict:
    # See: https://semgrep.dev/docs/writing-rules/rule-syntax/
    return {
        "id": id,
        "message": "result",
        "severity": "INFO",
        "languages": [language.name],
        "pattern": pattern,
        "options": {
            # Disable known unsupported features
            # See: https://semgrep.dev/docs/writing-rules/rule-syntax/#options
            "ac_matching": False,
            "constant_propagation": False,
            # See: https://github.com/returntocorp/semgrep/blob/develop/interfaces/Config_semgrep.atd
            "vardef_assign": False,
            "attr_expr": False,
            "arrow_is_function": False,
            "let_is_var": False,
            "go_deeper_expr": False,
            "go_deeper_stmt": False,
            "implicit_deep_exprstmt": False,
            "implicit_ellipsis": False,
        },
    }


def semgrep_extra_flags() -> list[str]:
    # See: https://semgrep.dev/docs/cli-reference/#semgrep-scan-options
    return [
        # Try to optimize performance
        "--metrics=off",
        "--no-git-ignore",
        "--disable-version-check",
        "--no-rewrite-rule-ids",
        # Disable silencing matches
        "--disable-nosem",
        # Include all info in output
        "--verbose",
    ]


if __name__ == "__main__":
    parser = ArgumentParser()
    add_args(parser)

    main(parser.parse_args())
