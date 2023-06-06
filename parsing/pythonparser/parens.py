from typing import Iterable, Iterator

import parsing
from parsing import Token, Parenthesized, IterParenthesized


def iter_match_python_parens(tokens: Iterable[Token]) -> Iterator[Token | IterParenthesized]:
    return parsing.iter_match_parens(tokens, {"{": "}", "[": "]", "(": ")"})


def match_python_parens(tokens: Iterable[Token]) -> Iterator[Token | Parenthesized]:
    return parsing.match_parens(tokens, {"{": "}", "[": "]", "(": ")"})
