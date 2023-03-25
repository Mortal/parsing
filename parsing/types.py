import re
from dataclasses import dataclass
from typing import Optional, Iterator, Iterable, Callable


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

    def advanced_span(self, buffer: str, i: int, j: int) -> "Span":
        return Span(self, self.advanced(buffer, i, j))

    def new_buffer(self) -> "Position":
        return Position(0, self.lineno, self.column)


@dataclass
class Span:
    start: Position
    end: Position


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
    span: Span
    length: int

    def message_and_input_line(self) -> str:
        return "\n".join(
            [
                'File "%s", line %s' % (self.buffer.filename, self.span.start.lineno),
                self.buffer.get_line_from_position(self.span.start),
                " " * self.span.start.column + "^" + "~" * (self.length - 1),
                "%s:%s:%s: %s"
                % (self.buffer.filename, self.span.start.lineno, self.span.start.column + 1, self.message),
            ]
        )


class ParsingError(Exception):
    def __init__(self, err: ParsingErr) -> None:
        self.err = err
        super().__init__(err)

    def __str__(self) -> str:
        return self.err.message
