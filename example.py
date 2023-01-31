import argparse
import re
import traceback
from dataclasses import dataclass
from parsing import iter_tokens, ParsingError, Token
from typing import Iterator, Iterable


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
class Parenthesized:
    left: Token
    contents: list["Token | Parenthesized"]
    right: Token


def parse_python_step_one(tokens: Iterable[Token]) -> Iterator[Token | Parenthesized]:
    parens = {"{": "}", "[": "]", "(": ")"}
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


@dataclass
class Block:
    indent: str
    tokens: list["Token | Parenthesized | Block"]


def parse_python_step_two(tokens: Iterable[Token | Parenthesized]) -> Iterator[Token | Parenthesized | Block]:
    indent_stack: list[Block] = []
    got_colon = False
    expect_indent = False
    for tok in tokens:
        if isinstance(tok, Parenthesized):
            if indent_stack:
                indent_stack[-1].tokens.append(tok)
            else:
                yield tok
            continue

        text = tok.text

        if tok.kind == "newline":
            expect_indent = got_colon
            if indent_stack:
                indent_stack[-1].tokens.append(tok)
            else:
                yield tok
            continue

        if tok.kind == "indent":
            if expect_indent:
                current_indent = len(indent_stack[-1].indent) if indent_stack else 0
                if len(text) <= current_indent:
                    raise tok.to_error("expected indent")
                indent_stack.append(Block(text, [tok]))
            else:
                while indent_stack and len(text) < len(indent_stack[-1].indent):
                    t = indent_stack.pop()
                    if indent_stack:
                        indent_stack[-1].tokens.append(t)
                    else:
                        yield t
                if not indent_stack or len(text) > len(indent_stack[-1].indent):
                    raise tok.to_error("unexpected indent")
                indent_stack[-1].tokens.append(tok)
            continue

        if tok.pos.column == 0:
            while indent_stack:
                t = indent_stack.pop()
                if indent_stack:
                    indent_stack[-1].tokens.append(t)
                else:
                    yield t

        if text == ":":
            got_colon = True
        else:
            got_colon = False
        if indent_stack:
            indent_stack[-1].tokens.append(tok)
        else:
            yield tok


def main() -> None:
    args = parser.parse_args()
    with open(args.filename) as fp:
        contents = fp.read()
    try:
        list(parse_python_step_two(parse_python_step_one(iter_tokens(python_lexer, args.filename, contents))))
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
