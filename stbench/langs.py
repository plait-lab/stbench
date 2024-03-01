from typing import ClassVar, Iterable

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Language:
    name: str

    # TODO: support more languages
    SUPPORTS: ClassVar[list[str]] = [
        'javascript',
    ]

    ALIAS: ClassVar[dict[str, str]] = {
        'js': 'javascript',
    }

    EXTS: ClassVar[dict[str, list[str]]] = {
        'javascript': ['.js'],
    }

    def __init__(self, name: str) -> None:
        assert self.supports(name)
        object.__setattr__(self, 'name', self._canonical(name))

    @classmethod
    def supports(cls, name: str) -> bool:
        return cls._canonical(name) in cls.SUPPORTS

    @classmethod
    def _canonical(cls, name: str) -> str:
        return cls.ALIAS.get(name, name)

    def exts(self) -> list[str]:
        return self.EXTS[self.name]

    def __str__(self) -> str:
        return self.name


def find(path: Path, languages: set[Language]) -> Iterable[Path]:
    assert path.exists(), 'invalid selection path'
    exts = {ext for lang in languages for ext in lang.exts()}
    for p in path.glob('**/*'):
        if p.is_file() and p.suffix in exts:
            yield p
