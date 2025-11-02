import argparse
import ast
import binascii
import re
import traceback
import typing
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, NoReturn, Literal

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


@dataclass(frozen=True)
class ParsedBlock:
    left: Token
    firstline: "ParsedLine"
    tokens: list["ParsedLine | ParsedBlock"]
    right: Token
    tail: list[Token]

    def ensure_block(self) -> "ParsedBlock":
        return self

    def ensure_line(self) -> NoReturn:
        raise self.firstline.tokens[0].to_error("Expected line but found block")

    def get_str(self, index: int) -> str:
        return self.firstline.get_str(index)

    def get_int(self, index: int) -> int:
        return int(self.get_word(index))

    def get_word(self, index: int) -> str:
        return self.firstline.get_word(index)

    def get_word_or_str(self, index: int) -> str:
        return self.firstline.get_word_or_str(index)

    def has_word(self, text: str) -> bool:
        return self.firstline.has_word(text)

    @property
    def start(self) -> Position:
        return self.left.start

    @property
    def end(self) -> Position:
        return self.right.end

    @property
    def kind(self) -> str:
        return self.firstline.kind

    def getitems(self) -> dict[str, list["ParsedLine | ParsedBlock"]]:
        items: dict[str, list["ParsedLine | ParsedBlock"]] = {}
        for line in self.tokens:
            items.setdefault(line.kind, []).append(line)
        return items


@dataclass(frozen=True)
class ParsedLine:
    tokens: list[Token]

    def ensure_line(self) -> "ParsedLine":
        return self

    def ensure_block(self) -> NoReturn:
        raise self.tokens[0].to_error("Expected block but found line")

    def get_str(self, index: int) -> str:
        assert self.tokens
        tok = self.tokens[index]
        assert isinstance(tok, Token)
        if tok.kind != "string":
            raise self.tokens[index].to_error(f"expected string but got '{tok.kind}'")
        assert tok.kind == "string", self.tokens[index]
        return ast.literal_eval(tok.text)

    def get_word(self, index: int) -> str:
        assert self.tokens
        tok = self.tokens[index]
        assert isinstance(tok, Token)
        if tok.kind != "word":
            raise self.tokens[index].to_error(f"expected word but got '{tok.kind}'")
        assert tok.kind == "word", self.tokens[index]
        return tok.text

    def get_int(self, index: int) -> int:
        return int(self.get_word(index))

    def get_word_or_str(self, index: int) -> str:
        assert self.tokens
        tok = self.tokens[index]
        assert isinstance(tok, Token)
        if tok.kind == "word":
            return tok.text
        if tok.kind != "string":
            raise self.tokens[index].to_error(f"expected string but got '{tok.kind}'")
        assert tok.kind == "string", self.tokens[index]
        return ast.literal_eval(tok.text)

    def has_word(self, text: str) -> bool:
        return any(tok.kind == "word" and tok.text == text for tok in self.tokens)

    @property
    def text(self) -> str:
        return " ".join(t.text for t in self.tokens)

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


def parse_reaper_project(s: str, filename: str = "-") -> "RProject":
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

    def parse_block(parens: Parenthesized, tail: list[Token]) -> ParsedBlock:
        buf: list[Token] = []
        firstline: ParsedLine | None = None
        tokens: list[ParsedLine | ParsedBlock] = []
        for token in parens.tokens:
            if isinstance(token, Parenthesized):
                if buf:
                    if (
                        len(token.tokens) == 1
                        and isinstance(token.tokens[0], Token)
                        and token.tokens[0].kind == "word"
                    ):
                        buf += [token.left, token.tokens[0], token.right]
                        continue
                    raise token.to_error("Parenthesized not at start of line")
                tokens.append(parse_block(token, []))
                continue
            if (
                not buf
                and tokens
                and isinstance(tokens[-1], ParsedBlock)
                and token.kind == "newline"
            ):
                tokens[-1].tail.append(token)
                continue
            buf.append(token)
            if token.kind == "newline":
                line = ParsedLine(buf)
                buf = []
                if firstline is None:
                    firstline = line
                else:
                    tokens.append(line)
        assert not buf
        assert firstline is not None
        return ParsedBlock(parens.left, firstline, tokens, parens.right, tail)

    return RProject(parse_block(mainparen, tail))


@dataclass(frozen=True)
class RSource:
    inner: ParsedBlock

    @property
    def typetoken(self) -> Token:
        assert self.inner.firstline.tokens
        if len(self.inner.firstline.tokens) < 2:
            raise self.inner.firstline.tokens[0].to_error("No source type")
        typetoken = self.inner.firstline.tokens[1]
        if typetoken.kind != "word":
            raise typetoken.to_error("Expected source type word")
        typ = typetoken.text
        if typ not in ("WAVE", "FLAC", "MP3", "VIDEO", "CLICK", "MIDI"):
            raise typetoken.to_error("Unknown type")
        return typetoken

    @property
    def type(self) -> Literal["WAVE", "FLAC", "MP3", "VIDEO", "CLICK", "MIDI"]:
        return typing.cast(Any, self.typetoken.text)

    @property
    def path(self) -> str | None:
        paths = self.inner.getitems().get("FILE", [])
        tok = self.typetoken
        if tok.text in ("CLICK", "MIDI"):
            if paths:
                raise paths[0].ensure_line().tokens[0].to_error("Unexpected path")
            return None
        if not paths:
            raise tok.to_error("Expected FILE for this type of source")
        return paths[0].get_str(1)


@dataclass(frozen=True)
class RItem:
    inner: ParsedBlock

    @property
    def sources(self) -> list[RSource]:
        return [
            RSource(line.ensure_block())
            for line in self.inner.getitems().get("SOURCE", [])
        ]


@dataclass(frozen=True)
class RVst:
    inner: ParsedBlock

    @property
    def metadata(self) -> tuple[str, str, int, bytes]:
        name = self.inner.get_str(1)
        sopath = self.inner.get_word(2)
        n1 = self.inner.get_int(3)
        assert n1 == 0
        s1 = self.inner.get_str(4)
        assert s1 == ""
        n2 = self.inner.get_int(5)
        lt = self.inner.firstline.tokens[6]
        assert lt.text == "<"
        somedata = self.inner.get_word(7)
        gt = self.inner.firstline.tokens[8]
        assert gt.text == ">"
        s2 = self.inner.get_str(9)
        assert s2 == ""
        assert self.inner.firstline.tokens[10].kind == "newline"
        assert len(self.inner.firstline.tokens) == 11, [
            t.text for t in self.inner.firstline.tokens
        ]
        return name, sopath, n2, binascii.a2b_hex(somedata)

    @property
    def data(self) -> list[bytes]:
        d = []
        for line in self.inner.tokens:
            assert len(line.tokens) == 2
            assert line.tokens[1].kind == "newline"
            d.append(binascii.a2b_base64(line.ensure_line().tokens[0].text))
        return d


@dataclass(frozen=True)
class RFxChain:
    inner: ParsedBlock | None

    @property
    def vsts(self) -> list[RVst]:
        if self.inner is None:
            return []
        return [
            RVst(line.ensure_block()) for line in self.inner.getitems().get("VST", [])
        ]


@dataclass(frozen=True)
class RTrack:
    inner: ParsedBlock

    @property
    def uuid(self) -> str:
        w = self.inner.get_word(1)
        assert w.startswith("{") and w.endswith("}")
        return w[1:-1]

    @property
    def name(self) -> str:
        return self.inner.getitems().get("NAME", [])[0].ensure_line().get_word_or_str(1)

    @property
    def items(self) -> list[RItem]:
        return [
            RItem(line.ensure_block()) for line in self.inner.getitems().get("ITEM", [])
        ]

    @property
    def fxchain(self) -> RFxChain:
        chains = self.inner.getitems().get("FXCHAIN", [])
        if not chains:
            return RFxChain(None)
        if len(chains) > 1:
            raise (
                chains[1]
                .ensure_block()
                .firstline.tokens[0]
                .to_error("Track has more than one FXCHAIN")
            )
        return RFxChain(chains[0].ensure_block())


@dataclass(frozen=True)
class RProject:
    inner: ParsedBlock

    @property
    def tracks(self) -> list[RTrack]:
        return [
            RTrack(line.ensure_block())
            for line in self.inner.getitems().get("TRACK", [])
        ]

    @property
    def record_path(self) -> str:
        return self.inner.getitems().get("RECORD_PATH", [])[0].get_str(1)


parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    with open(args.filename) as fp:
        contents = fp.read()
    try:
        project = parse_reaper_project(contents, str(args.filename))
        print(project.record_path)
        for track in project.tracks:
            print("TRACK", track.uuid, track.name)
            for vst in track.fxchain.vsts:
                print(vst.metadata)
                if vst.metadata[1] == "reaverb.vst.so":
                    print(vst.data[2])
                if vst.metadata[1] == "libsitala.so":
                    print("".join(d.decode() for d in vst.data[3:-1]))
        print(
            [
                [[source.path for source in item.sources] for item in track.items]
                for track in project.tracks
            ]
        )
    except ParsingError as e:
        traceback.print_exc()
        print(e.message_and_input_line())
        raise SystemExit(1)


if __name__ == "__main__":
    main()
