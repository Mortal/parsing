from typing import Iterable, Iterator

import parsing
from parsing import Token, Parenthesized


def match_python_parens(tokens: Iterable[Token]) -> Iterator[Token | Parenthesized]:
    return parsing.match_parens(tokens, {"{": "}", "[": "]", "(": ")"})
