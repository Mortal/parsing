import re
from dataclasses import dataclass
from typing import Optional, Iterator, Iterable


@dataclass
class Position:
    index: int
    lineno: int
    column: int

    def advanced(self, buf: str, i: int, j: int) -> "Position":
        assert self.index >= 0
        assert i < j, (i, j)
        nls = buf.count("\n", i, j)
        k = j - i
        assert k > 0
        if not nls:
            return Position(self.index + k, self.lineno, self.column + k)
        # print("Found %s newlines in %r" % (nls, buf[i:j]))
        nl = buf.rindex("\n", i, j)
        column = j - (nl + 1)
        return Position(self.index + k, self.lineno + nls, column)


@dataclass
class Buffer:
    filename: str
    contents: str

    def __repr__(self) -> str:
        return "<Buffer %r>" % (self.filename,)

    def get_line_from_position(self, pos: Position) -> str:
        line_start = pos.index - pos.column
        try:
            line_end: int | None = self.contents.index("\n", line_start)
        except ValueError:
            line_end = None
        return self.contents[line_start:line_end]


@dataclass
class ParsingErr:
    message: str
    buffer: Buffer
    pos: Position
    length: int

    def message_and_input_line(self) -> str:
        return "\n".join(
            [
                'File "%s", line %s' % (self.buffer.filename, self.pos.lineno),
                self.buffer.get_line_from_position(self.pos),
                " " * self.pos.column + "^" + "~" * (self.length - 1),
                "%s:%s:%s: %s"
                % (self.buffer.filename, self.pos.lineno, self.pos.column + 1, self.message),
            ]
        )


class ParsingError(Exception):
    def __init__(self, err: ParsingErr) -> None:
        self.err = err
        super().__init__(err)

    def __str__(self) -> str:
        return self.err.message


def strip_count_if_non_empty(text: str, pos: Position) -> tuple[Position, int]:
    u = text.lstrip()
    new_length = len(u.rstrip())
    if not new_length or new_length == len(text):
        return pos, len(text)
    new_pos = pos.advanced(text, 0, len(text) - len(u))
    return new_pos, new_length


@dataclass
class Token:
    kind: str
    buffer: Buffer
    pos: Position
    length: int

    @property
    def text(self) -> str:
        return self.buffer.contents[self.pos.index : self.pos.index + self.length]

    def to_err(self, message: str) -> ParsingErr:
        return ParsingErr(message, self.buffer, self.pos, self.length)

    def to_error(self, message: str) -> ParsingError:
        return ParsingError(self.to_err(message))

    def strip_if_non_empty(self) -> "Token":
        pos, length = strip_count_if_non_empty(self.text, self.pos)
        if (pos, length) == (self.pos, self.length):
            return self
        return Token(self.kind, self.buffer, pos, length)


@dataclass
class OptToken:
    kind: Optional[str]
    buffer: Buffer
    pos: Position
    length: int

    @property
    def text(self) -> str:
        return self.buffer.contents[self.pos.index : self.pos.index + self.length]

    @property
    def blank(self) -> bool:
        return not self.text.strip()

    @property
    def unmatch(self) -> bool:
        return self.kind is None

    def to_err(self, message: str) -> ParsingErr:
        return ParsingErr(message, self.buffer, self.pos, self.length)

    def to_error(self, message: str) -> ParsingError:
        return ParsingError(self.to_err(message))

    def strip_if_non_empty(self) -> "OptToken":
        pos, length = strip_count_if_non_empty(self.text, self.pos)
        if (pos, length) == (self.pos, self.length):
            return self
        return OptToken(self.kind, self.buffer, pos, length)

    def unwrap(self) -> Token:
        if self.kind is None:
            raise self.strip_if_non_empty().to_error("unexpected data while lexing")
        return Token(self.kind, self.buffer, self.pos, self.length)


def iter_opt_tokens(
    pattern: re.Pattern[str], filename: str, contents: str
) -> Iterator[OptToken]:
    buffer = Buffer(filename, contents)
    pos = Position(0, 1, 0)
    for mo in re.finditer(pattern, contents):
        kind = mo.lastgroup
        assert kind is not None
        i = mo.start()
        if pos.index != i:
            yield OptToken(None, buffer, pos, i - pos.index)
            pos = pos.advanced(contents, pos.index, i)
        i = mo.end()
        if pos.index != i:
            yield OptToken(kind, buffer, pos, i - pos.index)
            pos = pos.advanced(contents, pos.index, i)
    i = len(contents)
    if pos.index != i:
        yield OptToken(None, buffer, pos, i - pos.index)
        pos = pos.advanced(contents, pos.index, i)


def unwrapped_non_blank(it: Iterable[OptToken]) -> Iterator[Token]:
    for t in it:
        if t.unmatch and t.blank:
            continue
        yield t.unwrap()


def iter_tokens(
    pattern: re.Pattern[str], filename: str, contents: str
) -> Iterator[Token]:
    yield from unwrapped_non_blank(iter_opt_tokens(pattern, filename, contents))
