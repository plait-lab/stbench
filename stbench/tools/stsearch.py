import re

from . import Query
from .semgrep import METAVAR


def from_semgrep(query: Query) -> Query:
    '''Translate a Semgrep query to stsearch.'''
    language, pattern = query

    # stsearch doesn't use metavar names or support named ellipsis
    # https://semgrep.dev/docs/writing-rules/pattern-syntax/#ellipsis-metavariables

    def wildcard(kind: str): return '...' if kind == '...' else '$_'
    pattern = METAVAR.sub(lambda m: wildcard(m['kind']), pattern)

    # FIX: generalize to more languages
    pattern = re.sub(r',?(\s*\.{3}\s*),?', r'\1', pattern)
    pattern = re.sub(r'(?<!\.)\.\s*(\.{3}\s*\.)(?!\.)', r'\1', pattern)

    return query._replace(syntax=pattern)
