import re
from dataclasses import dataclass
from typing import Iterable, Iterator

import parsing
from parsing import (
    LineParser,
    MultiToken,
    Parenthesized,
    ParsingErr,
    ParsingError,
    Position,
    Token,
)

python_lexer = re.compile(
    r"""
(?P<name>[\w][\w\d]*)
|(?P<newline>\n)
|(?P<indent>^[ \t]+)
|(?P<number>[0-9]+)
|(?P<comment>\#.*)
|(?P<backslash>\\)
|(?P<semicolon>;)
|(?P<op>-=|//=|//|[:!]=|<<|>>|\*\*|[=+*/%|<>^]=?|->|-|[][(){},=:@.|%*/+^&~])
|(?P<string>
    [a-zA-Z]*"["]"(?:\\(?:.|\n)|[^\\"]|"(?:[^"]|"[^"]))*"["]"
    |'[']'(?:\\(?:.|\n)|[^\\']|'(?:[^']|'[^']))*'[']'
    |"(?:\\(?:.|\n)|[^\\"])*"
    |'(?:\\(?:.|\n)|[^\\'])*'
)
""",
    re.M | re.X,
)


def iter_python_tokens(filename: str, contents: str) -> Iterator[Token]:
    return parsing.iter_tokens(python_lexer, filename, contents)


def match_python_parens(tokens: Iterable[Token]) -> Iterator[Token | Parenthesized]:
    return parsing.match_parens(tokens, {"{": "}", "[": "]", "(": ")"})


@dataclass
class Line:
    tokens: list["Token | Parenthesized"]
    indent: Token | None
    colon: Token | None
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


@dataclass
class Block:
    indent: str
    tokens: list["Line | Block"]

    @property
    def start(self) -> Position:
        assert self.tokens
        return self.tokens[0].start

    @property
    def end(self) -> Position:
        assert self.tokens
        return self.tokens[-1].end

    @property
    def first_non_blank(self) -> Token | None:
        for t in self.tokens:
            b = t.first_non_blank
            if b is not None:
                return b
        return None


def flatten(tokens: Iterable[Token | Parenthesized | Line | Block]) -> Iterator[Token]:
    for tok in tokens:
        if isinstance(tok, Token):
            yield tok
        elif isinstance(tok, Parenthesized):
            yield tok.left
            yield from flatten(tok.tokens)
            yield tok.right
        elif isinstance(tok, Line):
            yield from flatten(tok.tokens)
        elif isinstance(tok, Block):
            yield from flatten(tok.tokens)


def identify_python_lines(
    tokens: Iterable[Token | Parenthesized],
) -> Iterator[Line]:
    line: list[Token | Parenthesized] = []
    got_indent: Token | None = None
    got_colon: Token | None = None
    got_backslash: Token | None = None
    first_non_blank: Token | None = None
    for tok in tokens:
        if isinstance(tok, Token):
            if tok.kind == "indent":
                if line:
                    # Tokenized as indent, but actually part of a continued line,
                    # so technically non-indent whitespace.
                    # Don't add non-indent whitespace to line.
                    continue
                got_indent = tok
            elif tok.kind == "newline":
                line.append(tok)
                if not got_backslash:
                    line_object = Line(
                        line[:],
                        indent=got_indent,
                        colon=got_colon,
                        newline=tok,
                        first_non_blank=first_non_blank,
                    )
                    del line[:]
                    yield line_object
                    # Reset state
                    got_indent = None
                    got_colon = None
                    first_non_blank = None
                    continue
                # Consume backslash and revert to non-backslash state
                got_backslash = None
                continue
            elif tok.kind == "comment":
                # Comments don't affect backslash or colon state
                line.append(tok)
                continue
            else:
                if first_non_blank is None:
                    first_non_blank = tok
        if isinstance(tok, Parenthesized) and first_non_blank is None:
            first_non_blank = tok.left
        # Got a real token, so discard any previous colon
        got_colon = None
        if got_backslash:
            raise got_backslash.to_error("expected newline after backslash")
        line.append(tok)
        if isinstance(tok, Token):
            if tok.kind == "backslash":
                got_backslash = tok
                continue
            if tok.text == ":":
                got_colon = tok
                continue
    if got_backslash:
        raise got_backslash.to_error("unexpected EOF after backslash")
    if line:
        line_object = Line(
            line[:],
            indent=got_indent,
            colon=got_colon,
            newline=None,
            first_non_blank=first_non_blank,
        )
        yield line_object


def identify_python_blocks(
    lines: Iterable[Line],
) -> Iterator[Line | Block]:
    indent_stack: list[Block] = []
    expect_indent: Token | None = None
    for line in lines:
        if line.first_non_blank is not None:
            current_indent = len(indent_stack[-1].indent) if indent_stack else 0
            indent_text = line.indent.text if line.indent is not None else ""
            if expect_indent is not None:
                if len(indent_text) <= current_indent:
                    # raise line.first_non_blank.to_error("expected indent")
                    raise expect_indent.to_error("expected indent")
                assert line.indent is not None
                indent_stack.append(Block(indent_text, []))
            else:
                if len(indent_text) > current_indent:
                    raise line.first_non_blank.to_error("unexpected indent")
                while indent_stack and len(indent_text) < len(indent_stack[-1].indent):
                    t = indent_stack.pop()
                    if indent_stack:
                        indent_stack[-1].tokens.append(t)
                    else:
                        yield t
                if len(indent_text) > (
                    len(indent_stack[-1].indent) if indent_stack else 0
                ):
                    raise line.first_non_blank.to_error("unexpected indent")
            expect_indent = line.colon
        if indent_stack:
            indent_stack[-1].tokens.append(line)
        else:
            yield line
    if expect_indent is not None:
        raise expect_indent.to_error("expected indent after colon at eof")
    while indent_stack:
        t = indent_stack.pop()
        if indent_stack:
            indent_stack[-1].tokens.append(t)
        else:
            yield t


def fixup_end_of_block(lines: list[Line | Block]) -> None:
    def scrape_end(lines: list[Line | Block], indent: str) -> list[Line | Block]:
        i = len(lines)
        while i > 0:
            c = lines[i - 1]
            if not isinstance(c, Line):
                break
            if c.first_non_blank is not None:
                break
            ind = c.indent
            if ind is not None and len(ind.text) >= len(indent):
                # Properly indented
                break
            i -= 1
        r = lines[i:]
        del lines[i:]
        return r

    def visit(lines: list[Line | Block], indent: str) -> None:
        for c in lines:
            if isinstance(c, Block):
                visit(c.tokens, c.indent)
        i = 0
        while i < len(lines):
            c = lines[i]
            if isinstance(c, Block):
                lines[i + 1 : i + 1] = scrape_end(c.tokens, c.indent)
            i += 1

    visit(lines, "")


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
    if (n.kind == "op" and n.text not in ("+", "-", "~")) or n.text in (
        "if",
        "while",
        "for",
        "elif",
        "else",
    ):
        return Binop(Operand([], p.skip(), []), [])
    return Binop(parse_python_operand(p), parse_python_operands(p))


def parse_python_operand(p: LineParser) -> Operand:
    return Operand(
        parse_python_prefixes(p), parse_python_atom(p), parse_python_trailers(p)
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
    if n := p.skip_token("lambda"):
        prefix = [p.skip()]
        while not prefix[-1].text == ":":
            prefix.append(p.skip())
        return prefix

    if n := p.skip_token("yield"):
        if m := p.skip_token("from"):
            # Skip "yield from"
            return [n, m]
        # Skip "yield"
        return [n]

    if n := p.skip_token(*PREFIX_UNOPS):
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
    if n := p.skip_token("."):
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
