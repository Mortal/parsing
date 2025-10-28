import argparse
import ast
import re
import traceback
from dataclasses import dataclass
from typing import Iterable, Iterator

import parsing
from parsing import Parenthesized, Position, Token, ParsingError

reaper_lexer = re.compile(
    r"""
(?P<op>[<>])
|(?P<word>[^\s<>"]+)
|(?P<string>"(?:\\.|[^"\\])*")
|(?P<newline>\r\n|\n)
|(?P<eof>\Z)
""",
    re.M | re.X,
)


def iter_reaper_tokens(filename: str, contents: str) -> Iterator[Token]:
    return parsing.iter_tokens(reaper_lexer, filename, contents)


def match_reaper_parens(tokens: Iterable[Token]) -> Iterator[Token | Parenthesized]:
    return parsing.match_parens(tokens, {"<": ">"})


@dataclass
class Block:
    left: Token
    firstline: "Line"
    tokens: list["Line | Block"]
    right: Token
    tail: list[Token]

    @property
    def start(self) -> Position:
        return self.left.start

    @property
    def end(self) -> Position:
        return self.right.end

    @property
    def kind(self) -> str:
        return self.firstline.kind


@dataclass
class Line:
    tokens: list[Token]

    @property
    def start(self) -> Position:
        assert self.tokens
        return self.tokens[0].start

    @property
    def end(self) -> Position:
        assert self.tokens
        return self.tokens[-1].end

    @property
    def kind(self) -> str:
        assert self.tokens
        tok = self.tokens[0]
        assert isinstance(tok, Token)
        if tok.kind != "word":
            raise self.tokens[0].to_error(f"expected word but got '{tok.kind}'")
        assert tok.kind == "word", self.tokens[0]
        return tok.text


def parse_reaper_project(s: str, filename: str = "-") -> Block:
    mainiterator = match_reaper_parens(iter_reaper_tokens(filename, s))
    try:
        mainparen = next(mainiterator)
    except StopIteration:
        raise Exception("empty input")
    if not isinstance(mainparen, Parenthesized):
        raise Exception("expected '<' at start of input")
    tail: list[Token] = []
    for extra in mainiterator:
        if isinstance(extra, Parenthesized):
            raise extra.to_error("unexpected data after last '>'")
        if extra.kind in ("newline", "eof"):
            tail.append(extra)
            continue
        raise extra.to_error(f"unexpected '{extra.kind}' after last '>'")

    def parse_block(parens: Parenthesized, tail: list[Token]) -> Block:
        buf: list[Token] = []
        firstline: Line | None = None
        tokens: list[Line | Block] = []
        for token in parens.tokens:
            if isinstance(token, Parenthesized):
                if buf:
                    if len(token.tokens) == 1 and isinstance(token.tokens[0], Token) and token.tokens[0].kind == "word":
                        buf += [token.left, token.tokens[0], token.right]
                        continue
                    raise token.to_error("Parenthesized not at start of line")
                tokens.append(parse_block(token, []))
                continue
            if not buf and tokens and isinstance(tokens[-1], Block) and token.kind == "newline":
                tokens[-1].tail.append(token)
                continue
            buf.append(token)
            if token.kind == "newline":
                line = Line(buf)
                buf = []
                if firstline is None:
                    firstline = line
                else:
                    tokens.append(line)
        assert not buf
        assert firstline is not None
        return Block(parens.left, firstline, tokens, parens.right, tail)

    return parse_block(mainparen, tail)


parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    filename: str = args.filename

    seen: set[str] = set()
    with open(filename) as fp:
        try:
            project = parse_reaper_project(fp.read(), filename)
            for line in project.tokens:
                if line.kind == "TRACK":
                    assert isinstance(line, Block)
                    for line in line.tokens:
                        if line.kind == "ITEM":
                            assert isinstance(line, Block)
                            for line in line.tokens:
                                if line.kind == "SOURCE":
                                    assert isinstance(line, Block)
                                    for line in line.tokens:
                                        if line.kind == "FILE":
                                            assert isinstance(line, Line)
                                            path = ast.literal_eval(line.tokens[1].text)
                                            if path not in seen:
                                                seen.add(path)
                                                print(path)
                                    continue
                            continue
                    continue
        except ParsingError as e:
            traceback.print_exc()
            print(e.message_and_input_line())
            raise SystemExit(1)


if __name__ == "__main__":
    main()
