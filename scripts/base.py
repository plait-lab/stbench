from typing import *

import yaml

from dataclasses import dataclass

from tools import Language, Match, Path




def add_custom_tags(Loader: yaml.Loader, Dumper: yaml.Dumper):
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
            return self.represent_scalar(tag, str(data))

        yaml.add_constructor(tag, constructor, Loader=Loader)
        yaml.add_representer(cls, representer, Dumper=Dumper)

    no_alias = []
    for cls, *args in custom:
        add_custom_tag(cls, *args)
        no_alias.append(cls)

    def ignore_aliases(dumper: yaml.Dumper, data: Any):
        return any(isinstance(data, cls) for cls in no_alias) \
            or ignore_aliases_old(dumper, data)

    ignore_aliases_old = Dumper.ignore_aliases
    Dumper.ignore_aliases = ignore_aliases


def add_pretty_representers(Dumper: yaml.Dumper):
    def str_representer(self: yaml.Dumper, data: str) -> yaml.ScalarNode:
        return self.represent_scalar('tag:yaml.org,2002:str', data,
                                     style=('|' if '\n' in data else None))

    yaml.add_representer(str, str_representer, Dumper=Dumper)


add_custom_tags(yaml.SafeLoader, yaml.SafeDumper)
add_pretty_representers(yaml.SafeDumper)
