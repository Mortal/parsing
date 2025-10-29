import argparse
import ast
import os
import re
import subprocess
import traceback
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Iterator, NoReturn, Literal

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

    def get_word(self, index: int) -> str:
        return self.firstline.get_word(index)

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
                raise paths[0].tokens[0].to_error("Unexpected path")
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
class RTrack:
    inner: ParsedBlock

    @property
    def items(self) -> list[RItem]:
        return [
            RItem(line.ensure_block()) for line in self.inner.getitems().get("ITEM", [])
        ]


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
    projectlist: list[ProjectLinks] = []
    if os.path.isfile(args.filename):
        projectlist.append(process(args.filename))
    for dirpath, dirs, files in os.walk(args.filename):
        for filename in files:
            if filename.lower().endswith(".rpp"):
                project = process(os.path.join(dirpath, filename))
                projectlist.append(project)
    projects: dict[PurePath, list[ProjectLinks]] = {}
    for project in projectlist:
        record_path = PurePath(project.project_path).parent / PurePath(project.record_path)
        projects.setdefault(record_path, []).append(project)
    uses: dict[PurePath, list[str]] = {}
    owner: dict[PurePath, PurePath] = {}
    outsideuses: dict[PurePath, list[PurePath]] = {}
    for record_path in projects:
        for dirpath, dirs, files in os.walk(record_path):
            dirs.sort()
            files.sort()
            for filename in files:
                filepath = record_path / dirpath / filename
                uses.setdefault(filepath, [])
                ex = owner.setdefault(filepath, record_path)
                if ex != record_path:
                    raise Exception(f"overlapping media dirs: {ex} {record_path} {filepath}")
        for project in projects[record_path]:
            project_dir = PurePath(project.project_path).parent
            for item in project.media_items:
                itempath = project_dir / PurePath(item)
                uses.setdefault(itempath, []).append(project.project_path)
                if record_path not in itempath.parents:
                    outsideuses.setdefault(record_path, []).append(itempath)
    record_path_edges: dict[PurePath, set[PurePath]] = {}
    for record_path, itempaths in outsideuses.items():
        record_path_edges[record_path] = set(owner[itempath] for itempath in itempaths)
        print(record_path, "->", *sorted(record_path_edges[record_path]))
    sizes: dict[PurePath, int] = {}
    record_path_sizes: dict[PurePath, int] = {record_path: 0 for record_path in projects}
    outside_record_path: list[tuple[PurePath, int]] = []
    for path in uses:
        try:
            sizes[path] = os.path.getsize(path)
            if path in owner:
                record_path_sizes[owner[path]] += sizes[path]
            else:
                outside_record_path.append((path, sizes[path]))
        except FileNotFoundError:
            sizes[path] = -1
    sizeinuse = 0
    sizenotinuse = 0
    for path in uses:
        if uses[path]:
            sizeinuse += sizes[path]
        else:
            sizenotinuse += sizes[path]
        print("\t".join(map(str, (len(uses[path]), sizes[path], path))))
    statbroken = 0
    brokennames: set[str] = set()
    for record_path in sorted(projects, key=lambda p: record_path_sizes[p]):
        print("===========", f"{record_path_sizes[record_path] / 2**30:.2f} GB -", record_path)
        for project in projects[record_path]:
            project_dir = PurePath(project.project_path).parent
            broken: list[str] = []
            totsize = 0.0
            for item in project.media_items:
                itempath = project_dir / PurePath(item)
                itemsize = sizes[itempath]
                if itemsize == -1:
                    broken.append(item)
                    brokennames.add(os.path.basename(item))
                else:
                    totsize += itemsize / len(uses[itempath])
            if broken:
                statbroken += 1
                print("BROKEN", round(totsize), project.project_path, *broken)
            else:
                print(round(totsize), project.project_path)
    print("===========", "Outside")
    for path, size in outside_record_path:
        print(size, path, *uses[path])

    print(f"{statbroken} broken projects, {sizeinuse/2**30:.2f} GB used media, {sizenotinuse/2**30:.2f} GB unused media")

    if brokennames:
        findargs = ["find", args.filename]
        for i, nam in enumerate(sorted(brokennames)):
            if i:
                findargs.append("-or")
            findargs += ["-name", nam]
        subprocess.call(findargs)


@dataclass(frozen=True)
class ProjectLinks:
    project_path: str
    record_path: str
    media_items: list[str]


def process(filename: str) -> ProjectLinks:
    seen: set[str] = set()
    with open(filename) as fp:
        try:
            project = parse_reaper_project(fp.read(), filename)
            record_path = project.record_path
            # media = PurePath(record_path)
            media_items: list[str] = []
            for track in project.tracks:
                for item in track.items:
                    for source in item.sources:
                        pathstr = source.path
                        if pathstr is None:
                            continue
                        if pathstr not in seen:
                            # assert media in PurePath(pathstr).parents, (filename, media, pathstr)
                            seen.add(pathstr)
                            media_items.append(pathstr)
        except ParsingError as e:
            traceback.print_exc()
            print(e.message_and_input_line())
            raise SystemExit(1)
    return ProjectLinks(filename, record_path, media_items)


if __name__ == "__main__":
    main()
