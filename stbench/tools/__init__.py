from typing import NamedTuple

import re

from operator import itemgetter

from ..langs import Language


class Query(NamedTuple):
    language: Language
    syntax: str
