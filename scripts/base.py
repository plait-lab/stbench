from typing import *

import yaml
import gzip

from argparse import ArgumentParser, FileType
from dataclasses import dataclass, fields, MISSING

from tools import Language, Match, Path


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


def add_custom_tags():
    T = TypeVar('T')

    custom = [
        # type, tag, parser
        (Language, '!lang', Language),
        (Match, '!match', Match.parse),
        (type(Path()), '!path', Path),
    ]

    def add_custom_tag(cls: Type[T], tag: str, parse: Callable[[str], T]) -> Type[T]:
        def constructor(self: yaml.Loader, node: yaml.Node) -> cls:
            return parse(self.construct_scalar(node))

        def representer(self: yaml.Dumper, data: cls) -> yaml.ScalarNode:
            return self.represent_scalar(tag, str(data), style="'")

        Loader.add_constructor(tag, constructor)
        Dumper.add_representer(cls, representer)

    no_alias = []
    for cls, *args in custom:
        add_custom_tag(cls, *args)
        no_alias.append(cls)

    def ignore_aliases(dumper: yaml.Dumper, data: Any):
        return any(isinstance(data, cls) for cls in no_alias) \
            or ignore_aliases_old(dumper, data)

    ignore_aliases_old = Dumper.ignore_aliases
    Dumper.ignore_aliases = ignore_aliases


def add_pretty_representers():
    def str_representer(self: yaml.Dumper, data: str) -> yaml.ScalarNode:
        return self.represent_scalar('tag:yaml.org,2002:str', data,
                                     style=('|' if '\n' in data else None))

    Dumper.add_representer(str, str_representer)


add_custom_tags()
add_pretty_representers()
