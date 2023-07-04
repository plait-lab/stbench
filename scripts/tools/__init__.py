from typing import *

from tools import semgrep
from tools import stsearch

from tools.common import *


all: dict[str, Tool] = {
    'semgrep': semgrep,
    'stsearch': stsearch,
}
