import argparse
import ast
import binascii
import os
import re
import struct
import subprocess
import sys
import traceback
import typing
from dataclasses import dataclass
from typing import Any, Iterable, Iterator, NoReturn, Literal, Protocol

import parsing
from parsing import Parenthesized, Position, Token, ParsingError

reaper_lexer = re.compile(
    r"""
(?P<op>[<>])
|(?P<code>\|.*)
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

    def visit_tokens(self) -> Iterator[Token]:
        yield self.left
        yield from self.firstline.visit_tokens()
        for token in self.tokens:
            yield from token.visit_tokens()
        yield self.right
        yield from self.tail

    def __repr__(self) -> str:
        return f"<ParsedBlock '{self.firstline}'>"

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

    def __repr__(self) -> str:
        return f"<ParsedLine '{self}'>"

    def __str__(self) -> str:
        return " ".join(t.text.strip() for t in self.tokens).strip()

    def visit_tokens(self) -> Iterator[Token]:
        yield from self.tokens

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
        assert not buf, buf[0].start
        assert firstline is not None
        return ParsedBlock(parens.left, firstline, tokens, parens.right, tail)

    return RProject(parse_block(mainparen, tail))


class ReaperNode(Protocol):
    def visit_reaper(self) -> "Iterator[Token | ReaperNode]": ...


@dataclass(frozen=True)
class RSource:
    inner: ParsedBlock

    def visit_reaper(self) -> Iterator[Token | ReaperNode]:
        return self.inner.visit_tokens()

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

    def visit_reaper(self) -> Iterator[Token | ReaperNode]:
        yield self.inner.left
        yield from self.inner.firstline.visit_tokens()
        for line in self.inner.tokens:
            if line.kind == "SOURCE":
                yield RSource(line.ensure_block())
            else:
                yield from line.visit_tokens()
        yield self.inner.right
        yield from self.inner.tail

    @property
    def ypos(self) -> tuple[float, float, int] | None:
        "Cursed property indicating lane position"
        lines = self.inner.getitems().get("YPOS")
        if not lines:
            return None
        line_, = lines
        line = line_.ensure_line()
        return float(line.get_word(1)), float(line.get_word(2)), line.get_int(3)

    @property
    def mute(self) -> bool:
        return self.inner.getitems()["MUTE"][0].ensure_line().get_int(1) != 0

    @property
    def sources(self) -> list[RSource]:
        return [
            RSource(line.ensure_block())
            for line in self.inner.getitems().get("SOURCE", [])
        ]


@dataclass(frozen=True)
class RVst:
    inner: ParsedBlock

    def visit_reaper(self) -> Iterator[Token | ReaperNode]:
        return self.inner.visit_tokens()

    def is_reaverb(self) -> bool:
        return self.metadata[1] == "reaverb.vst.so"

    def as_reaverb(self) -> "RVstReaverb | None":
        if self.is_reaverb():
            return RVstReaverb(self)
        return None

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
class RVstReaverb:
    inner: RVst

    def visit_reaper(self) -> Iterator[Token | ReaperNode]:
        yield self.inner

    @property
    def path(self) -> str:
        vst_data = b"".join(self.inner.data)
        sz, = struct.unpack_from("<i", vst_data, 0x30)
        if 0x6c + 4 > 0x34 + sz:
            sys.stdout.flush()
            subprocess.run(("hexdump", "-C"), input=vst_data)
        assert 0x6c + 4 <= 0x34 + sz, hex(sz)
        sz2, = struct.unpack_from("<i", vst_data, 0x6c)
        assert sz2 > 4
        nul = vst_data.find(b"\0", 0x6c + 8, 0x6c + 4 + sz2)
        if nul == -1:
            nul = 0x6c + 4 + sz2
        assert nul >= 0x6c + 8
        return vst_data[0x6c + 8 : nul].decode()


@dataclass(frozen=True)
class RFxChain:
    inner: ParsedBlock | None

    def visit_reaper(self) -> Iterator[Token | ReaperNode]:
        if self.inner is None:
            return
        yield self.inner.left
        yield from self.inner.firstline.visit_tokens()
        for line in self.inner.tokens:
            if line.kind == "VST":
                yield RVst(line.ensure_block())
            else:
                yield from line.visit_tokens()
        yield self.inner.right
        yield from self.inner.tail

    @property
    def vsts(self) -> list[RVst]:
        if self.inner is None:
            return []
        return [
            RVst(line.ensure_block()) for line in self.inner.getitems().get("VST", [])
        ]


@dataclass(frozen=True, kw_only=True)
class ItemInfo:
    lane: int
    in_muted_lane: bool


@dataclass(frozen=True)
class RTrack:
    inner: ParsedBlock

    def visit_reaper(self) -> Iterator[Token | ReaperNode]:
        yield self.inner.left
        yield from self.inner.firstline.visit_tokens()
        for line in self.inner.tokens:
            if line.kind == "ITEM":
                yield RItem(line.ensure_block())
            elif line.kind == "FXCHAIN":
                yield RFxChain(line.ensure_block())
            else:
                yield from line.visit_tokens()
        yield self.inner.right
        yield from self.inner.tail

    @property
    def mutesolo(self) -> tuple[int, int, int]:
        item, = self.inner.getitems()["MUTESOLO"]
        line = item.ensure_line()
        return line.get_int(1), line.get_int(2), line.get_int(3)

    @property
    def mute(self) -> bool:
        return self.mutesolo[0] != 0

    @property
    def solo(self) -> bool:
        return self.mutesolo[1] != 0

    @property
    def uuid(self) -> str:
        w = self.inner.get_word(1)
        assert w.startswith("{") and w.endswith("}")
        return w[1:-1]

    @property
    def name(self) -> str:
        return self.inner.getitems().get("NAME", [])[0].ensure_line().get_word_or_str(1)

    @property
    def item_info(self) -> list[tuple[RItem, ItemInfo]]:
        lanes = self.itemlanes or 1
        lanesolo = (self.lanesolo or [1])[0]
        items: list[tuple[RItem, ItemInfo]] = []
        for line in self.inner.getitems().get("ITEM", []):
            item = RItem(line.ensure_block()) 
            ypos = item.ypos
            if ypos:
                ystart, yheight, _ = ypos
                lane = int((ystart + yheight / 2) * lanes)
            else:
                lane = 0
            in_muted_lane = not (lanesolo & (1 << lane))
            info = ItemInfo(lane=lane, in_muted_lane=in_muted_lane)
            items.append((item, info))
        return items

    @property
    def items(self) -> list[RItem]:
        return [
            RItem(line.ensure_block()) for line in self.inner.getitems().get("ITEM", [])
        ]

    @property
    def itemlanes(self) -> int | None:
        lines = self.inner.getitems().get("ITEMLANES")
        if not lines:
            return None
        line, = lines
        return line.ensure_line().get_int(1)

    @property
    def lanename(self) -> list[str] | None:
        lines = self.inner.getitems()["LANENAME"]
        n = self.itemlanes
        if not lines:
            assert n is None
            return None
        assert n is not None
        line, = lines
        line_ = line.ensure_line()
        return [line_.get_word_or_str(i) for i in range(1, n + 1)]

    @property
    def lanesolo(self) -> list[int] | None:
        "First entry is a bitset of which lanes are playing. Other entries unsure."
        lines = self.inner.getitems().get("LANESOLO")
        if not lines:
            return None
        line, = lines
        line_ = line.ensure_line()
        return [line_.get_int(i) for i in range(1, len(line_.tokens) - 1)]

    @property
    def isbus(self) -> tuple[int, int]:
        """(flag: 0/1/2, count: int) where flag=1 is folder,
        flag=2 is last in folder, count is the change in indentation
        (positive for flag=1, negative for flag=2)"""
        line, = self.inner.getitems()["ISBUS"]
        return line.ensure_line().get_int(1), line.ensure_line().get_int(2)

    @property
    def has_linkedlane(self) -> bool:
        return bool(self.inner.getitems().get("LINKEDLANE"))

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


@dataclass(frozen=True, kw_only=True)
class FolderInfo:
    in_muted_folder: bool
    is_folder: bool
    is_last_in_folder: bool
    indent: int


@dataclass(frozen=True)
class RProject:
    inner: ParsedBlock

    def visit_reaper(self) -> Iterator[Token | ReaperNode]:
        yield self.inner.left
        yield from self.inner.firstline.visit_tokens()
        for line in self.inner.tokens:
            if line.kind == "TRACK":
                yield RTrack(line.ensure_block())
            else:
                yield from line.visit_tokens()
        yield self.inner.right
        yield from self.inner.tail

    @property
    def tracks(self) -> list[RTrack]:
        return [t for t, _ in self.track_info]

    @property
    def track_info(self) -> list[tuple[RTrack, FolderInfo]]:
        tracks: list[tuple[RTrack, FolderInfo]] = []
        mutestack: list[bool] = []
        for line in self.inner.getitems().get("TRACK", []):
            track = RTrack(line.ensure_block())
            folderkind, foldercount = track.isbus
            info = FolderInfo(
                in_muted_folder=any(mutestack),
                is_folder=folderkind == 1,
                is_last_in_folder=folderkind == 2,
                indent=len(mutestack),
            )
            tracks.append((track, info))
            if foldercount > 0:
                mute = track.mute
                for _ in range(foldercount):
                    mutestack.append(mute)
            for _ in range(-foldercount):
                if not mutestack:
                    # Last track can "end the folder" even though it's not in a folder
                    continue
                mutestack.pop()
        return tracks

    @property
    def record_path(self) -> str:
        return self.inner.getitems().get("RECORD_PATH", [])[0].get_str(1)


parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    if os.path.isfile(args.filename):
        main_process(args.filename)
    else:
        for dirpath, dirs, files in os.walk(args.filename):
            dirs.sort()
            files.sort()
            for filename in files:
                path = os.path.join(dirpath, filename)
                ext = filename.lower()
                if ext.endswith(".rpp"):
                    main_process(path)


seen: set[bytes] = set()

def main_process(path: str) -> None:
    with open(path) as fp:
        contents = fp.read()
    try:
        project = parse_reaper_project(contents, str(path))
        print("record_path:", os.path.join(os.path.dirname(path), project.record_path))
        for track, info in project.track_info:
            trackinfo = [track.name]
            if info.is_folder:
                trackinfo.append("(folder)")
            elif info.is_last_in_folder:
                trackinfo.append("(last in folder)")
            mute = track.mute
            if mute:
                trackinfo.append("MUTE")
            elif info.in_muted_folder:
                trackinfo.append("MUTEFOLDER")
            if track.solo:
                trackinfo.append("SOLO")
            if track.has_linkedlane:
                trackinfo.append("COMP")
            elif track.itemlanes:
                trackinfo.append("LANES")
            print("- track:", track.uuid, *trackinfo)
            for vst in track.fxchain.vsts:
                print("-- vst:", vst.metadata)
                vst_reaverb = vst.as_reaverb()
                if vst_reaverb is not None:
                    print("---", vst_reaverb.path)
                if vst.metadata[1] == "libsitala.so":
                    print("---", "".join(d.decode() for d in vst.data[3:-1]))
            for item, info2 in track.item_info:
                iteminfo = ["MUTE"] if item.mute else ["MUTELANE"] if info2.in_muted_lane else []
                for source in item.sources:
                    print("-- item in lane", info2.lane, "source:", *iteminfo, source.path)
    except ParsingError as e:
        traceback.print_exc()
        print(e.message_and_input_line())
        raise SystemExit(1)


if __name__ == "__main__":
    main()
