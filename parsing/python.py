import argparse
import re
import traceback
from dataclasses import dataclass
from typing import Iterator, Iterable

from parsing.tokens import iter_tokens, ParsingError, Token, Position
from parsing.parens import Parenthesized, match_parens


python_lexer = re.compile(
    r"""
(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)
|(?P<newline>\n)
|(?P<blankline>^[ \t]+$)
|(?P<indent>^[ \t]+)
|(?P<number>[0-9]+)
|(?P<comment>\#.*)
|(?P<backslash>\\)
|(?P<op>!=|[<>]=?|->|-|[][(){},=:@.|%*/+^&])
|(?P<string>
    "["]"(?:\\(?:.|\n)|[^\\"]|"(?:[^"]|"[^"]))*"["]"
    |'[']'(?:\\(?:.|\n)|[^\\']|'(?:[^']|'[^']))*'[']'
    |"(?:\\(?:.|\n)|[^\\"])*"
    |'(?:\\(?:.|\n)|[^\\'])*'
)
""",
    re.M | re.X,
)


parser = argparse.ArgumentParser()
parser.add_argument("--no-output", "-n", action="store_true")
parser.add_argument("filename")


@dataclass
class Line:
    tokens: list["Token | Parenthesized"]


@dataclass
class Block:
    indent: str
    tokens: list["Line | Block"]


def flatten(tokens: Iterable[Token | Parenthesized | Line | Block]) -> Iterator[Token]:
    for tok in tokens:
        if isinstance(tok, Token):
            yield tok
        elif isinstance(tok, Parenthesized):
            yield tok.left
            yield from flatten(tok.contents)
            yield tok.right
        elif isinstance(tok, Line):
            yield from flatten(tok.tokens)
        elif isinstance(tok, Block):
            yield from flatten(tok.tokens)


def tok_or_left(tok: Token | Parenthesized) -> Token:
    if isinstance(tok, Token):
        return tok
    return tok.left


def identify_python_blocks(
    tokens: Iterable[Token | Parenthesized],
) -> Iterator[Line | Block]:
    indent_stack: list[Block] = []
    line: list[Token | Parenthesized] = []
    got_indent: Token | None = None
    got_colon: Token | None = None
    got_backslash: Token | None = None
    expect_indent: Token | None = None
    for tok in tokens:
        if got_indent is not None and isinstance(tok, Token) and tok.kind in ("newline", "comment", "backslash"):
            line.append(got_indent)
            got_indent = None
        if got_indent is not None:
            indent_text = got_indent.text
            if expect_indent is not None:
                current_indent = len(indent_stack[-1].indent) if indent_stack else 0
                if len(indent_text) <= current_indent:
                    raise expect_indent.to_error("expected indent after colon")
                indent_stack.append(Block(indent_text, []))
                expect_indent = None
            else:
                while indent_stack and len(indent_text) < len(indent_stack[-1].indent):
                    t = indent_stack.pop()
                    if indent_stack:
                        indent_stack[-1].tokens.append(t)
                    else:
                        yield t
                if not indent_stack or len(indent_text) > len(indent_stack[-1].indent):
                    raise tok_or_left(tok).to_error("unexpected indent")
            line.append(got_indent)
            got_indent = None

        if isinstance(tok, Parenthesized):
            if got_backslash is not None:
                raise tok.left.to_error("unexpected paren after backslash")
            if tok.left.pos.column == 0:
                while indent_stack:
                    t = indent_stack.pop()
                    if indent_stack:
                        indent_stack[-1].tokens.append(t)
                    else:
                        yield t
                if expect_indent is not None:
                    raise tok.left.to_error("expected indent after colon")
            got_colon = None
            line.append(tok)
            continue

        text = tok.text

        if tok.kind == "newline":
            if got_backslash is not None:
                line.append(got_backslash)
                got_backslash = None
                line.append(tok)
                continue
            expect_indent = got_colon
            if line:
                line_object = Line(line[:])
                del line[:]
                if indent_stack:
                    indent_stack[-1].tokens.append(line_object)
                    yield line_object
                else:
                    yield line_object
            continue

        if tok.kind == "indent":
            if line:
                line.append(tok)
                continue
            got_indent = tok
            continue

        if got_backslash is not None:
            raise tok.to_error("unexpected token after backslash")

        if tok.kind == "backslash":
            got_backslash = tok
            continue

        if tok.kind == "comment":
            line.append(tok)
            continue

        if tok.pos.column == 0:
            while indent_stack:
                t = indent_stack.pop()
                if indent_stack:
                    indent_stack[-1].tokens.append(t)
                else:
                    yield t
            if expect_indent is not None:
                raise tok.to_error("expected indent after colon")

        if text == ":":
            got_colon = tok
        else:
            got_colon = None
        line.append(tok)
    if expect_indent is not None:
        raise expect_indent.to_error("expected indent after colon at eof")
    if got_colon is not None:
        raise got_colon.to_error("expected indent after colon at eof with no eol")
    if line:
        line_object = Line(line[:])
        del line[:]
        if indent_stack:
            indent_stack[-1].tokens.append(line_object)
            yield line_object
        else:
            yield line_object
    while indent_stack:
        t = indent_stack.pop()
        if indent_stack:
            indent_stack[-1].tokens.append(t)
        else:
            yield t


def dump_identified_blocks(tokens: Iterable[Line | Block], indent: str = "") -> Iterator[Line | Block]:
    for o in tokens:
        pos = next(iter(flatten([o]))).pos
        print("%s%s at %s" % (indent, type(o).__name__, pos))
        if pos.lineno == 427:
            print(repr(o))
        if isinstance(o, Block):
            dump_identified_blocks(o.tokens, o.indent)
        yield o


def check_contiguous_tokens(tokens: Iterable[Token]) -> Iterator[Token]:
    p = Position(0, 1, 0)
    for o in tokens:
        if o.pos.index != p.index:
            raise o.to_error(f"Missing bit from {p} to {o.pos} in output")
        p = o.pos.advanced(o.text, 0, o.length)
        yield o


def main() -> None:
    args = parser.parse_args()
    with open(args.filename) as fp:
        contents = fp.read()
    try:
        lexer_output = iter_tokens(python_lexer, args.filename, contents)
        matched_parens = match_parens(lexer_output, {"{": "}", "[": "]", "(": ")"})
        identified_blocks = identify_python_blocks(matched_parens)
        if not args.no_output:
            identified_blocks = dump_identified_blocks(identified_blocks)
        tokens = flatten(identified_blocks)
        tokens = check_contiguous_tokens(tokens)
        list(tokens)
    except ParsingError as e:
        traceback.print_exc()
        lines = e.err.buffer.contents.splitlines()
        print('File "%s", line %s' % (e.err.buffer.filename, e.err.pos.lineno))
        print(lines[e.err.pos.lineno - 1])
        print(" " * e.err.pos.column + "^" + "~" * (e.err.length - 1))
        print(
            "%s:%s:%s: %s"
            % (e.err.buffer.filename, e.err.pos.lineno, e.err.pos.column + 1, e)
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
