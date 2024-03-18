from typing import Iterable

import csv
import logging

from pathlib import Path

from .tools import Query, semgrep


logger = logging.getLogger(__name__)
reporter = logger.getChild('report')


def report(*lines: str):
    return reporter.info('\n' + '\n- '.join(lines))


class Results:
    def __init__(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        self.path = path

    def new(self, name: str) -> Path:
        return self.path / name

    def save(self, name: str, it: Iterable[Iterable]):
        with self.new(name).with_suffix('.csv').open('w') as file:
            logger.info(f'saving: {file.name}')
            csv.writer(file).writerows(it)

    def tracer(self, name: str) -> logging.Handler:
        tracer = logging.FileHandler(self.new(name).with_suffix('.log'), 'w')
        tracer.addFilter(logging.Filter(logger.name))
        return tracer

    def report(self, name: str):
        results = logging.FileHandler(self.new(name).with_suffix('.log'), 'w')
        results.setFormatter(logging.Formatter('%(message)s'))
        reporter.addHandler(results)
