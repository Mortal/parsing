from dataclasses import dataclass
from typing import Sequence

from parsing import Token, IterParenthesized, Parenthesized, ParsingErr, ParsingError, Position
from parsing import LineParser, MultiToken


BINOPS = (
    ",",
    "**",
    "*",
    "@",
    "/",
    "//",
    "%",
    "+",
    "-",
    "<<",
    ">>",
    "&",
    "^",
    "|",
    "in",
    "is",
    "<",
    "<=",
    ">",
    ">=",
    "!=",
    "==",
    "and",
    "or",
    "if",
    "else",
    ":=",
)
PREFIX_UNOPS = ("await", "+", "-", "~", "not")


@dataclass
class Operand:
    prefixes: list[MultiToken]
    atom: Parenthesized | Token
    trailers: list[MultiToken]

    @property
    def start(self) -> Position:
        if self.prefixes:
            return self.prefixes[0][0].start
        return self.atom.start

    @property
    def end(self) -> Position:
        if self.trailers:
            return self.trailers[-1][-1].end
        return self.atom.end


@dataclass
class Binop:
    left: Operand
    operands: list[tuple[MultiToken, Operand]]

    @property
    def start(self) -> Position:
        return self.left.start

    @property
    def end(self) -> Position:
        if self.operands:
            return self.operands[-1][1].end
        return self.left.end


def parse_python_expression(p: LineParser) -> Binop:
    assert p.has_next
    n = p.next
    if (n.kind == "op" and n.text not in ("+", "-", "~")) or n.text in ("if", "while", "for", "elif", "else"):
        return Binop(Operand([], p.skip(), []), [])
    return Binop(parse_python_operand(p), parse_python_operands(p))


def parse_python_operand(p: LineParser) -> Operand:
    return Operand(
        parse_python_prefixes(p),
        parse_python_atom(p),
        parse_python_trailers(p)
    )


def parse_python_operands(p: LineParser) -> list[tuple[MultiToken, Operand]]:
    operands: list[tuple[MultiToken, Operand]] = []
    while (op := parse_python_operator(p)) is not None:
        if op[0].text == "," and not p.has_next:
            # Trailing comma
            break
        operands.append((op, parse_python_operand(p)))
    return operands


def parse_python_prefixes(p: LineParser) -> list[MultiToken]:
    prefixes: list[MultiToken] = []
    while (prefix := parse_python_prefix(p)) is not None:
        prefixes.append(prefix)
    return prefixes


def parse_python_prefix(p: LineParser) -> MultiToken | None:
    if (n := p.skip_token("lambda")):
        prefix = [p.skip()]
        while not prefix[-1].text == ":":
            prefix.append(p.skip())
        return prefix

    if (n := p.skip_token("yield")):
        if (m := p.skip_token("from")):
            # Skip "yield from"
            return [n, m]
        # Skip "yield"
        return [n]

    if (n := p.skip_token(*PREFIX_UNOPS)):
        # Skip single-token unary prefixed operators: "await", "not", +/-/~
        return [n]
    return None


def parse_python_atom(p: LineParser) -> Parenthesized | Token:
    return p.skip()


def parse_python_trailers(p: LineParser) -> list[MultiToken]:
    trailers: list[MultiToken] = []
    while (trailer := parse_python_trailer(p)) is not None:
        trailers.append(trailer)
    return trailers


def parse_python_trailer(p: LineParser) -> MultiToken | None:
    if not p.has_next:
        return None
    if isinstance(p.next, Parenthesized):
        # Function call or indexing
        return [p.skip()]
    if (n := p.skip_token(".")):
        # Attribute lookup
        return [n, p.skip()]
    return None


def parse_python_operator(p: LineParser) -> MultiToken | None:
    # See if we have a binary operator.
    # Note that this is very simplistic and allows invalid expressions like
    # "x if y", "x else y"
    r = p.skip_tokens("not", "in") or p.skip_tokens("is", "not")
    if r:
        return r
    m = p.skip_token(*BINOPS)
    if m:
        return [m]
    return None


def skip_python_expression(p: LineParser) -> tuple[Token, Token]:
    assert p.has_next
    start = p.next
    end = p.next

    while True:
        n = p.skip()
        end = n
        t = "" if isinstance(n, Parenthesized) else n.text
        if t == "lambda":
            # Skip "lambda ...:"
            while not p.skip_token(":"):
                p.skip()
            continue
        if t == "yield":
            if p.skip_token("from"):
                # Skip "yield from"
                continue
            # Skip "yield"
            continue
        if t in PREFIX_UNOPS:
            # Skip single-token unary prefixed operators: "await", "not", +/-/~
            continue
        # Presumably, n is some kind of atom that is not a prefix.
        # Skip any trailers, and look out for a binary operator.
        found_binop = False
        while p.has_next:
            if isinstance(p.next, Parenthesized):
                # Function call or indexing
                end = p.skip()
                continue
            if p.skip_token("."):
                # Attribute lookup
                end = p.skip()
                continue
            # See if we have a binary operator.
            # Note that this is very simplistic and allows invalid expressions like
            # "x if y", "x else y"
            if p.skip_tokens("not", "in") or p.skip_tokens("is", "not"):
                # Two-word binary operator.
                found_binop = True
                break
            if p.skip_token(*BINOPS):
                found_binop = True
                break

            # No binary operation - we're done!
            found_binop = False
            break

        if not found_binop:
            break

    if isinstance(start, Parenthesized):
        start = start.left
    if isinstance(end, Parenthesized):
        end = end.right
    return start, end
