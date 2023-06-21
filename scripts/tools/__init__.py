from typing import *

from tools import semgrep
from tools import stsearch

from tools.common import *


runners: dict[str, Tool] = {
    'semgrep': semgrep.run,
    'stsearch': stsearch.run,
}
