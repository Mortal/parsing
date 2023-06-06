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
        line = self.buffer.get_line_from_position(self.span.start)
        pref = line[: self.span.start.column]
        pref_strip = pref.lstrip()
        pref_ws_count = len(pref) - len(pref_strip)
        indent = 4 * " "
        return "\n".join(
            [
                'File "%s", line %s' % (self.buffer.filename, self.span.start.lineno),
                indent + line[pref_ws_count:],
                indent + len(pref_strip) * " " + "^" + "~" * (self.length - 1),
                "%s:%s:%s: %s"
                % (
                    self.buffer.filename,
                    self.span.start.lineno,
                    self.span.start.column + 1,
                    self.message,
                ),
            ]
        )


class ParsingError(Exception):
    def __init__(self, err: ParsingErr) -> None:
        self.err = err
        super().__init__(err)

    def __str__(self) -> str:
        return self.err.message


def span_from_start_and_text(pos: Position, text: str) -> Span:
    return Span(pos, pos.advanced(text, 0, len(text)))


def strip_count_if_non_empty(text: str, span: Span) -> Span:
    u = text.lstrip()
    t = u.rstrip()
    if not t or len(t) == len(text):
        return span
    if len(text) == len(u):
        return span
    new_start = span.start.advanced(text, 0, len(text) - len(u))
    return span_from_start_and_text(new_start, t)


@dataclass
class Token:
    kind: str
    buffer: Buffer
    span: Span

    @property
    def start(self) -> Position:
        return self.span.start

    @property
    def end(self) -> Position:
        return self.span.end

    @property
    def index(self) -> int:
        return self.span.start.index

    @property
    def length(self) -> int:
        return self.span.end.index - self.span.start.index

    @property
    def text(self) -> str:
        return self.buffer.contents[self.index : self.index + self.length]

    def to_err(self, message: str) -> ParsingErr:
        return ParsingErr(message, self.buffer, self.span, self.length)

    def to_error(self, message: str) -> ParsingError:
        return ParsingError(self.to_err(message))

    def strip_if_non_empty(self) -> "Token":
        span = strip_count_if_non_empty(self.text, self.span)
        if span == self.span:
            return self
        return Token(self.kind, self.buffer, span)


@dataclass
class OptToken:
    kind: Optional[str]
    buffer: Buffer
    span: Span

    @property
    def start(self) -> Position:
        return self.span.start

    @property
    def end(self) -> Position:
        return self.span.end

    @property
    def index(self) -> int:
        return self.span.start.index

    @property
    def length(self) -> int:
        return self.span.end.index - self.span.start.index

    @property
    def text(self) -> str:
        return self.buffer.contents[self.index : self.index + self.length]

    @property
    def blank(self) -> bool:
        return not self.text.strip()

    @property
    def unmatch(self) -> bool:
        return self.kind is None

    def to_err(self, message: str) -> ParsingErr:
        return ParsingErr(message, self.buffer, self.span, self.length)

    def to_error(self, message: str) -> ParsingError:
        return ParsingError(self.to_err(message))

    def strip_if_non_empty(self) -> "OptToken":
        span = strip_count_if_non_empty(self.text, self.span)
        if span == self.span:
            return self
        return OptToken(self.kind, self.buffer, span)

    def unwrap(self) -> Token:
        if self.kind is None:
            raise self.strip_if_non_empty().to_error("unexpected data while lexing")
        return Token(self.kind, self.buffer, self.span)


class LinewiseTokenizer:
    def __init__(self, filename: str, pattern: re.Pattern[str]) -> None:
        self.filename = filename
        self.pattern = pattern
        self.fp = open(filename, "rb")
        self.encoding = "utf-8"
        self.pos = Position(0, 1, 0)

    def __enter__(self) -> "LinewiseTokenizer":
        self.fp.__enter__()
        return self

    def __exit__(self, ext, exv, exb) -> None:
        self.fp.__exit__(ext, exv, exb)

    def close(self) -> None:
        self.fp.close()

    def __iter__(self) -> "LinewiseTokenizer":
        return self

    def __next__(self) -> Iterator[OptToken]:
        line = self.fp.readline().decode(self.encoding)
        if not line:
            raise StopIteration
        res = iter_opt_tokens_impl(self.pattern, Buffer(self.filename, line), self.pos)
        self.pos = self.pos.advanced(line, 0, len(line))
        return res


def iter_opt_tokens_impl(
    pattern: re.Pattern[str], buffer: Buffer, pos: Position
) -> Iterator[OptToken]:
    contents = buffer.contents
    for mo in re.finditer(pattern, contents):
        kind = mo.lastgroup
        assert kind is not None
        i = mo.start()
        if pos.index != i:
            span = pos.advanced_span(contents, pos.index, i)
            yield OptToken(None, buffer, span)
            pos = span.end
        i = mo.end()
        span = pos.advanced_span(contents, pos.index, i)
        yield OptToken(kind, buffer, span)
        pos = span.end
    i = len(contents)
    if pos.index != i:
        span = pos.advanced_span(contents, pos.index, i)
        yield OptToken(None, buffer, span)
        pos = span.end


def unwrapped_non_blank(it: Iterable[OptToken]) -> Iterator[Token]:
    for t in it:
        if t.unmatch and t.blank:
            continue
        yield t.unwrap()


def iter_opt_tokens(
    pattern: re.Pattern[str],
    filename: str | None = None,
    contents: str | None = None,
    *,
    buffer: Buffer | None = None,
    pos: Position | None = None
) -> Iterator[OptToken]:
    if buffer is None:
        assert filename is not None
        assert contents is not None
        buffer = Buffer(filename, contents)
    if pos is None:
        pos = Position(0, 1, 0)
    return iter_opt_tokens_impl(pattern, buffer, pos)


def iter_tokens(
    pattern: re.Pattern[str],
    filename: str | None = None,
    contents: str | None = None,
    *,
    buffer: Buffer | None = None,
    pos: Position | None = None
) -> Iterator[Token]:
    if buffer is None:
        assert filename is not None
        assert contents is not None
        buffer = Buffer(filename, contents)
    if pos is None:
        pos = Position(0, 1, 0)
    return unwrapped_non_blank(iter_opt_tokens_impl(pattern, buffer, pos))


def iter_opt_tokens_change_encoding(
    pattern: re.Pattern[str], filename: str, line_bytes: Iterable[bytes]
) -> tuple[Iterator[OptToken], Callable[[str], None]]:

    encoding = "utf-8"

    def gen() -> Iterator[OptToken]:
        pos = Position(0, 1, 0)
        for b in line_bytes:
            line = b.decode(encoding)
            yield from iter_opt_tokens_impl(pattern, Buffer(filename, line), pos)
            pos = pos.advanced(line, 0, len(line)).new_buffer()

    def change_encoding(__e: str) -> None:
        nonlocal encoding
        encoding = __e

    return gen(), change_encoding


def iter_tokens_change_encoding(
    pattern: re.Pattern[str], filename: str, line_bytes: Iterable[bytes]
) -> tuple[Iterator[Token], Callable[[str], None]]:
    tokens, change_encoding = iter_opt_tokens_change_encoding(
        pattern, filename, line_bytes
    )
    return unwrapped_non_blank(tokens), change_encoding


@dataclass
class Parenthesized:
    left: Token
    tokens: list["Token | Parenthesized"]
    right: Token

    @property
    def kind(self) -> str:
        return "parenthesized"

    @property
    def start(self) -> Position:
        return self.left.start

    @property
    def index(self) -> int:
        return self.start.index

    @property
    def end(self) -> Position:
        return self.right.end

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)

    @property
    def length(self) -> int:
        return self.end.index - self.start.index

    @property
    def text(self) -> str | None:
        return None

    @property
    def buffer(self) -> Buffer:
        return self.left.buffer

    def to_err(self, message: str) -> ParsingErr:
        return ParsingErr(message, self.buffer, self.span, self.length)

    def to_error(self, message: str) -> ParsingError:
        return ParsingError(self.to_err(message))


@dataclass
class IterParenthesized:
    left: Token
    tokens: "Iterator[Token | IterParenthesized]"

    @property
    def kind(self) -> str:
        return "parenthesized"

    @property
    def start(self) -> Position:
        return self.left.start

    @property
    def index(self) -> int:
        return self.start.index

    def collect(self) -> Parenthesized:
        toks: list[Token | Parenthesized] = []
        try:
            t = next(self.tokens)
        except StopIteration:
            raise self.left.to_error("BUG: no tokens?")
        right: Token | Parenthesized = t.collect() if isinstance(t, IterParenthesized) else t
        for t in self.tokens:
            toks.append(right)
            right = t.collect() if isinstance(t, IterParenthesized) else t
        assert isinstance(right, Token)
        return Parenthesized(self.left, toks, right)

    @property
    def text(self) -> str | None:
        return None


def iter_match_parens(
    tokens: Iterable[Token], parens: dict[str, str], until: str | None = None
) -> Iterator[Token | IterParenthesized]:
    for tok in tokens:
        text = tok.text

        if text == until:
            yield tok
            break

        if text in parens:
            it = iter_match_parens(tokens, parens, parens[text])
            yield IterParenthesized(tok, it)
            # Exhaust 'it' before continuing in case the caller doesn't
            exhausted = True
            for t in it:
                exhausted = False
            continue

        if text in parens.values():
            if until:
                raise tok.to_error(
                    f"incorrectly matched parentheses: expected '{until}'"
                )
            raise tok.to_error("unexpected parenthesis")

        yield tok


def match_parens(
    tokens: Iterable[Token], parens: dict[str, str]
) -> Iterator[Token | Parenthesized]:
    return (
        t.collect() if isinstance(t, IterParenthesized) else t
        for t in iter_match_parens(tokens, parens)
    )
