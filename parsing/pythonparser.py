import re
from dataclasses import dataclass
from typing import Iterable, Iterator

import parsing
from parsing import Parenthesized, Position, Token

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
            assert line[-1] is got_backslash
            line.append(
                tok.to_errortoken_at_start("expected newline after backslash")
            )
            got_backslash = None
        line.append(tok)
        if isinstance(tok, Token):
            if tok.kind == "backslash":
                got_backslash = tok
                continue
            if tok.text == ":":
                got_colon = tok
                continue
    if got_backslash:
        assert line[-1] is got_backslash
        line.append(
            got_backslash.to_errortoken_at_end("unexpected EOF after backslash")
        )
        got_backslash = None
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
    line: Line | None = None
    for line in lines:
        if line.first_non_blank is not None:
            current_indent = len(indent_stack[-1].indent) if indent_stack else 0
            indent_text = line.indent.text if line.indent is not None else ""
            if expect_indent is not None:
                if len(indent_text) <= current_indent:
                    # Parse error: expected indent.
                    # Add error token and fall through to expect_indent=None case below.
                    errorline = Line(
                        tokens=[line.first_non_blank.to_errortoken_at_start("expected indent")],
                        indent=None,
                        colon=None,
                        newline=None,
                        first_non_blank=None,
                    )
                    if indent_stack:
                        indent_stack[-1].tokens.append(errorline)
                    else:
                        yield errorline
                    expect_indent = None
                else:
                    assert line.indent is not None
                    indent_stack.append(Block(indent_text, []))
            if expect_indent is None:
                if len(indent_text) > current_indent:
                    # Parse error: unexpected indent.
                    # Add new block with an error token.
                    errorline = Line(
                        tokens=[line.first_non_blank.to_errortoken_at_start("unexpected indent")],
                        indent=None,
                        colon=None,
                        newline=None,
                        first_non_blank=None,
                    )
                    indent_stack.append(Block(indent_text, [errorline]))
                while indent_stack and len(indent_text) < len(indent_stack[-1].indent):
                    t = indent_stack.pop()
                    if indent_stack:
                        indent_stack[-1].tokens.append(t)
                    else:
                        yield t
                if len(indent_text) > (
                    len(indent_stack[-1].indent) if indent_stack else 0
                ):
                    # Parse error: unexpected indent.
                    # Add new block with an error token.
                    errorline = Line(
                        tokens=[line.first_non_blank.to_errortoken_at_start("unexpected indent")],
                        indent=None,
                        colon=None,
                        newline=None,
                        first_non_blank=None,
                    )
                    indent_stack.append(Block(indent_text, [errorline]))
            expect_indent = line.colon
        if indent_stack:
            indent_stack[-1].tokens.append(line)
        else:
            yield line
    if expect_indent is not None:
        # Parse error: expected indent after colon at eof.
        assert line is not None
        assert line.tokens
        assert isinstance(line.tokens[-1], Token)
        errorline = Line(
            tokens=[line.tokens[-1].to_errortoken_at_end("expected indent after colon at eof")],
            indent=None,
            colon=None,
            newline=None,
            first_non_blank=None,
        )
        if indent_stack:
            indent_stack[-1].tokens.append(errorline)
        else:
            yield errorline
    while indent_stack:
        t = indent_stack.pop()
        if indent_stack:
            indent_stack[-1].tokens.append(t)
        else:
            yield t


def fixup_start_of_block(lines: list[Line | Block]) -> None:
    def visit(lines: list[Line | Block], indent: str) -> None:
        i = len(lines) - 1
        while i > 0:
            c = lines[i]
            if not isinstance(c, Block):
                i -= 1
                continue
            j = i
            while (
                j > 0
                and isinstance(lines[j - 1], Line)
                and lines[j - 1].first_non_blank is None
            ):
                j -= 1
            c.tokens[0:0] = lines[j:i]
            visit(c.tokens, c.indent)
            del lines[j:i]
            i = j - 1

    visit(lines, "")


def fixup_end_of_block(lines: list[Line | Block]) -> None:
    # When parsing Python code greedily, dedented comments become part of the
    # preceding block, as weirdly indented Python comments never cause
    # IndentationError. However, when analyzing Python code, it's nice to move
    # dedented comments at ends of blocks out of the block they were parsed in.
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
