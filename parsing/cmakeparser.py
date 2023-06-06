#!/usr/bin/env python3
import re
from dataclasses import dataclass
from typing import Iterable, Iterator, NamedTuple

import parsing
from parsing import IterParenthesized, Parenthesized, Position, Token


@dataclass
class Line:
    tokens: list["Token | Parenthesized"]
    indent: Token | None
    newline: Token | None
    first_non_blank: Token | None

    @property
    def start(self) -> Position:
        assert self.tokens
        return self.tokens[0].start

    @property
    def end(self) -> Position:
        assert self.tokens
        return self.tokens[-1].end


cmake_lexer = re.compile(
    r"""
(?P<unimplemented_brackets>\#?\[=*\[)
|(?P<comment>\#.*)
|(?P<quoted>"(?:[^\\"]|\\.)*")
|(?P<unquoted>(?:[^#(), \t\r\n]|\\.)(?:[^#$(), \t\r\n]|\\.|\$(?:\([^)]*\))?)*)
|(?P<special>[()])
|(?P<newline>\n)
|(?P<indent>^[ \t]+)
""",
    re.M | re.X,
)


def iter_cmake_tokens(filename: str, contents: str) -> Iterator[Token]:
    return parsing.iter_tokens(cmake_lexer, filename, contents)


def identify_cmake_lines(
    tokens: Iterable[Token | Parenthesized | IterParenthesized],
) -> Iterator[Line]:
    line: list[Token | Parenthesized] = []
    got_indent: Token | None = None
    first_non_blank: Token | None = None
    for tok in tokens:
        if isinstance(tok, IterParenthesized):
            tok = tok.collect()
        if isinstance(tok, Token):
            if tok.kind == "indent":
                assert not line
                assert not got_indent
                assert not first_non_blank
                got_indent = tok
            elif tok.kind == "newline":
                line.append(tok)
                line_object = Line(
                    line[:],
                    indent=got_indent,
                    newline=tok,
                    first_non_blank=first_non_blank,
                )
                del line[:]
                yield line_object
                # Reset state
                got_indent = None
                first_non_blank = None
                continue
            elif tok.kind == "comment":
                line.append(tok)
                continue
            else:
                if first_non_blank is None:
                    first_non_blank = tok
        if isinstance(tok, Parenthesized) and first_non_blank is None:
            first_non_blank = tok.left
        line.append(tok)
    if line:
        line_object = Line(
            line[:],
            indent=got_indent,
            newline=None,
            first_non_blank=first_non_blank,
        )
        yield line_object


class ArgGroup(NamedTuple):
    key: Token | None
    args: list[Token]


def get_grouped_args(it: Iterable[Token | Parenthesized]) -> dict[str, list[ArgGroup]]:
    current_group: list[Token] = []
    groups: dict[str, list[ArgGroup]] = {"": [ArgGroup(None, current_group)]}
    for a in it:
        assert not isinstance(a, Parenthesized)
        if a.text.strip() and a.text == a.text.upper() and not a.text.startswith('"'):
            current_group = []
            groups.setdefault(a.text, []).append(ArgGroup(a, current_group))
        else:
            current_group.append(a)
    return groups
