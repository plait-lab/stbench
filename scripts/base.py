from typing import *

import yaml
import gzip

from pathlib import Path
from argparse import ArgumentParser, FileType
from dataclasses import dataclass, fields, MISSING

from tools import Language


class Arg(TypedDict, total=False):
    flags: list[str]
    choices: list
    action: str
    mode: str


@dataclass
class Args:
    @classmethod
    def add_args(cls, parser: ArgumentParser):
        for field in fields(cls):
            arg = Arg(**field.metadata)
            args, kwargs = [], {}

            if 'flags' in arg:
                kwargs['dest'] = field.name
                kwargs['required'] = True
                args = arg['flags']
            else:
                args = [field.name]

            if field.default is not MISSING:
                kwargs['default'] = field.default
            assert field.default_factory is MISSING

            if 'choices' in arg:
                kwargs['choices'] = arg['choices']

            if (T := field.type) is not str:
                if get_origin(T) is Union:
                    match get_args(T):
                        case (T, NT) if NT is type(None):
                            del kwargs['required']
                        case _:
                            assert False
                elif get_origin(T) is list:
                    kwargs['nargs'] = '+'
                    T, = get_args(T)
                if issubclass(T, IO):
                    T = InputFile(arg['mode'])
                kwargs['type'] = T

            if 'action' in arg:
                kwargs['action'] = arg['action']
                if arg['action'] == 'append':
                    del kwargs['nargs']
                else:
                    assert False

            parser.add_argument(*args, **kwargs)

    @classmethod
    def parser(cls) -> ArgumentParser:
        cls.add_args(parser := ArgumentParser())
        return parser


class InputFile(FileType):
    def __call__(self, string: str) -> IO[Any]:
        if not string.endswith('.gz'):
            return super().__call__(string)
        mode = self._mode if self._mode.endswith('b') else f'{self._mode}t'
        f = gzip.open(string, mode, 1, self._encoding, self._errors)
        return f


Loader, Dumper = yaml.CSafeLoader, yaml.CSafeDumper


def load_all(f): return yaml.load_all(f, Loader)
def dump_all(l, f): return yaml.dump_all(l, f, Dumper, sort_keys=False)


T = TypeVar('T')
CustomTag: TypeAlias = tuple[T, Callable[[str], T]]

custom_tags: dict[str, CustomTag] = {
    'lang': (Language, Language),
    'path': (type(Path()), Path),
}


def add_custom_tags(custom: dict[str, CustomTag]):
    def add_custom_tag(cls: Type[T], tag: str, parse: Callable[[str], T]) -> Type[T]:
        Loader.add_constructor(tag, lambda self, node:
                               parse(self.construct_scalar(node)))
        Dumper.add_representer(cls, lambda self, data:
                               self.represent_scalar(tag, str(data), style="'"))

    for tag, (cls, parse) in custom.items():
        add_custom_tag(cls, f'!{tag}', parse)


def add_pretty_representers():
    def str_representer(self: yaml.Dumper, data: str) -> yaml.ScalarNode:
        return self.represent_scalar('tag:yaml.org,2002:str', data,
                                     style=('|' if '\n' in data else None))

    Dumper.add_representer(str, str_representer)


Dumper.ignore_aliases = lambda dumper, data: True
add_custom_tags(custom_tags)
add_pretty_representers()
