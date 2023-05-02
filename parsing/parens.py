from dataclasses import dataclass
from typing import Iterator, Iterable

from .tokens import Token, Position
from .types import Position, Span, Buffer, ParsingErr, ParsingError


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
