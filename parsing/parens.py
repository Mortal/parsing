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
    def end(self) -> Position:
        return self.right.end

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)

    @property
    def index(self) -> int:
        return self.start.index

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


def match_parens(
    tokens: Iterable[Token], parens: dict[str, str]
) -> Iterator[Token | Parenthesized]:
    paren_stack: list[tuple[str, Token, list[Token | Parenthesized]]] = []
    for tok in tokens:
        text = tok.text

        if text in parens:
            paren_stack.append((parens[text], tok, []))
            continue

        if text in parens.values():
            if not paren_stack:
                raise tok.to_error("unmatched parenthesis")
            if paren_stack[-1][0] != text:
                raise tok.to_error(
                    "incorrectly matched parentheses: %s%s"
                    % (paren_stack[-1][1].text, text)
                )
            paren = Parenthesized(paren_stack[-1][1], paren_stack[-1][2], tok)
            paren_stack.pop()
            if paren_stack:
                paren_stack[-1][2].append(paren)
            else:
                yield paren
            continue

        if paren_stack:
            paren_stack[-1][2].append(tok)
            continue

        yield tok
