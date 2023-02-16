import argparse
import re
import traceback
from dataclasses import dataclass
from typing import Iterator, Iterable

from .tokens import iter_tokens, ParsingError, Token
from .parens import Parenthesized


python_lexer = re.compile(
    r"""
(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)
|(?P<newline>\n)
|(?P<blankline>^[ \t]+$)
|(?P<indent>^[ \t]+)
|(?P<number>[0-9]+)
|(?P<comment>\#.*)
|(?P<op>!=|[<>]=?|->|[][(){},=:@.|%*/+-])
|(?P<string>
    "["]"(?:\\.|[^\\"]|"(?:[^"]|"[^"]))*"["]"
    |'[']'(?:\\.|[^\\']|'(?:[^']|'[^']))*'[']'
    |"(?:\\.|[^\\"])*"
    |'(?:\\.|[^\\'])*'
)
""",
    re.M | re.X,
)


parser = argparse.ArgumentParser()
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


def identify_python_blocks(
    tokens: Iterable[Token | Parenthesized],
) -> Iterator[Line | Block]:
    indent_stack: list[Block] = []
    line: list[Token | Parenthesized] = []
    got_colon: Token | None = None
    expect_indent: Token | None = None
    for tok in tokens:
        if isinstance(tok, Parenthesized):
            line.append(tok)
            continue

        text = tok.text

        if tok.kind == "newline":
            expect_indent = got_colon
            if line:
                line_object = Line(line[:])
                del line[:]
                if indent_stack:
                    indent_stack[-1].tokens.append(line_object)
                else:
                    yield line_object
            continue

        if tok.kind == "indent":
            if expect_indent is not None:
                current_indent = len(indent_stack[-1].indent) if indent_stack else 0
                if len(text) <= current_indent:
                    raise expect_indent.to_error("expected indent after colon")
                indent_stack.append(Block(text, []))
            else:
                while indent_stack and len(text) < len(indent_stack[-1].indent):
                    t = indent_stack.pop()
                    if indent_stack:
                        indent_stack[-1].tokens.append(t)
                    else:
                        yield t
                if not indent_stack or len(text) > len(indent_stack[-1].indent):
                    raise tok.to_error("unexpected indent")
            continue

        if tok.pos.column == 0:
            while indent_stack:
                t = indent_stack.pop()
                if indent_stack:
                    indent_stack[-1].tokens.append(t)
                else:
                    yield t

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
        else:
            yield line_object
    while indent_stack:
        t = indent_stack.pop()
        if indent_stack:
            indent_stack[-1].tokens.append(t)
        else:
            yield t


def dump_identified_blocks(tokens: Iterable[Line | Block], indent: str = "") -> None:
    for o in tokens:
        print("%s%s at %s" % (indent, type(o).__name__, next(iter(flatten([o]))).pos))
        if isinstance(o, Block):
            dump_identified_blocks(o.tokens, o.indent)


def main() -> None:
    args = parser.parse_args()
    with open(args.filename) as fp:
        contents = fp.read()
    try:
        lexer_output = iter_tokens(python_lexer, args.filename, contents)
        matched_parens = match_parens(lexer_output, {"{": "}", "[": "]", "(": ")"})
        identified_blocks = identify_python_blocks(matched_parens)
        dump_identified_blocks(identified_blocks)
    except ParsingError as e:
        traceback.print_exc()
        lines = e.err.buffer.contents.splitlines()
        print('File "%s", line %s' % (e.err.buffer.filename, e.err.pos.lineno))
        print(lines[e.err.pos.lineno - 1])
        print(" " * e.err.pos.column + "^" + "~" * (e.err.length - 1))
        print(
            "%s:%s:%s: %s"
            % (e.err.buffer.filename, e.err.pos.lineno, e.err.pos.column, e)
        )
        print(
            repr(not not e.err.buffer.contents[e.err.pos.index + e.err.length].strip())
        )


if __name__ == "__main__":
    main()
