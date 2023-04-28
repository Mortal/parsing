from dataclasses import dataclass
from typing import Iterator, Iterable, Sequence

from parsing import Token, Position, Parenthesized


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
