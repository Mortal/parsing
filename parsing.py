import re
from dataclasses import dataclass
from typing import Optional, Iterator, Iterable


@dataclass
class Position:
    index: int
    lineno: int
    column: int

    def advanced(self, buf: str, i: int, j: int) -> "Position":
        nls = buf.count("\n", i, j)
        k = j - i
        if not nls:
            return Position(self.index + k, self.lineno, self.column + k)
        nl = buf.rindex("\n", i, j)
        column = j - nl
        return Position(self.index + k, self.lineno + nl, column)


@dataclass
class Buffer:
    filename: str
    contents: str

    def __repr__(self) -> str:
        return "<Buffer %r>" % (self.filename,)


@dataclass
class Token:
    kind: str
    buffer: Buffer
    pos: Position
    length: int


@dataclass
class ParsingErr:
    message: str
    buffer: Buffer
    pos: Position
    length: int


class ParsingError(Exception):
    def __init__(self, err: ParsingErr) -> None:
        self.err = err
        super().__init__(err)

    def __str__(self) -> str:
        return self.err.message


@dataclass
class OptToken:
    kind: Optional[str]
    buffer: Buffer
    pos: Position
    length: int

    @property
    def blank(self) -> bool:
        return not not self.buffer.contents[self.pos.index + self.length].strip()

    @property
    def unmatch(self) -> bool:
        return self.kind is None

    def unwrap(self) -> Token:
        if self.kind is None:
            raise ParsingError(ParsingErr("unexpected data while lexing", self.buffer, self.pos, self.length))
        return Token(self.kind, self.buffer, self.pos, self.length)


def iter_opt_tokens(pattern: re.Pattern[str], filename: str, contents: str) -> Iterator[OptToken]:
    buffer = Buffer(filename, contents)
    pos = Position(0, 1, 0)
    for mo in re.finditer(pattern, contents):
        kind = mo.lastgroup
        assert kind is not None
        i = mo.start()
        if pos.index != i:
            yield OptToken(None, buffer, pos, i - pos.index)
            pos = pos.advanced(contents, i, pos.index)
        i = mo.end()
        if pos.index != i:
            yield OptToken(kind, buffer, pos, i - pos.index)
            pos = pos.advanced(contents, i, pos.index)
    i = len(contents)
    if pos.index != i:
        yield OptToken(None, buffer, pos, i - pos.index)
        pos = pos.advanced(contents, i, pos.index)


def unwrapped_non_blank(it: Iterable[OptToken]) -> Iterator[Token]:
    for t in it:
        if t.unmatch and t.blank:
            continue
        yield t.unwrap()


def iter_tokens(pattern: re.Pattern[str], filename: str, contents: str) -> Iterator[Token]:
    return unwrapped_non_blank(iter_opt_tokens(pattern, filename, contents))
