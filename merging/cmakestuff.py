#!/usr/bin/env python3
import difflib
import re
from dataclasses import dataclass
from typing import Iterator, NamedTuple, Iterable

import parsing
from parsing.merging import merging_main
from parsing import Token, Parenthesized, Position, IterParenthesized


@dataclass
class Line:
    tokens: list["Token | Parenthesized"]
    indent: Token | None
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


cmake_lexer = re.compile(
    r"""
(?P<unimplemented_brackets>\#?\[=*\[)
|(?P<comment>\#.*)
|(?P<quoted>"(?:[^\\"]|\\.)*")
|(?P<unquoted>(?:[^#(), \t\r\n]|\\.)(?:[^#$(), \t\r\n]|\\.|\$(?:\([^)]*\))?)*)
|(?P<special>[()])
|(?P<newline>\n)
|(?P<indent>^[ \t]+)
""",
    re.M | re.X,
)


def iter_cmake_tokens(filename: str, contents: str) -> Iterator[Token]:
    return parsing.iter_tokens(cmake_lexer, filename, contents)


def identify_cmake_lines(tokens: Iterable[Token | Parenthesized | IterParenthesized]) -> Iterator[Line]:
    line: list[Token | Parenthesized] = []
    got_indent: Token | None = None
    first_non_blank: Token | None = None
    for tok in tokens:
        if isinstance(tok, IterParenthesized):
            tok = tok.collect()
        if isinstance(tok, Token):
            if tok.kind == "indent":
                assert not line
                assert not got_indent
                assert not first_non_blank
                got_indent = tok
            elif tok.kind == "newline":
                line.append(tok)
                line_object = Line(
                    line[:],
                    indent=got_indent,
                    newline=tok,
                    first_non_blank=first_non_blank,
                )
                del line[:]
                yield line_object
                # Reset state
                got_indent = None
                first_non_blank = None
                continue
            elif tok.kind == "comment":
                line.append(tok)
                continue
            else:
                if first_non_blank is None:
                    first_non_blank = tok
        if isinstance(tok, Parenthesized) and first_non_blank is None:
            first_non_blank = tok.left
        line.append(tok)
    if line:
        line_object = Line(
            line[:],
            indent=got_indent,
            newline=None,
            first_non_blank=first_non_blank,
        )
        yield line_object


class ArgGroup(NamedTuple):
    key: Token | None
    args: list[Token]


def get_grouped_args(it: Iterable[Token | Parenthesized]) -> dict[str, list[ArgGroup]]:
    current_group: list[Token] = []
    groups: dict[str, list[ArgGroup]] = {"": [ArgGroup(None, current_group)]}
    for a in it:
        assert not isinstance(a, Parenthesized)
        if a.text.strip() and a.text == a.text.upper() and not a.text.startswith('"'):
            current_group = []
            groups.setdefault(a.text, []).append(ArgGroup(a, current_group))
        else:
            current_group.append(a)
    return groups


def parse_line_as_definition(line: Line) -> tuple[str, str, str] | None:
    tok = line.first_non_blank
    if tok and tok.kind == "unquoted":
        i = next(i for i, t in enumerate(line.tokens) if t is tok)
        if i + 1 < len(line.tokens):
            arg = line.tokens[i + 1]
            if isinstance(arg, Parenthesized):
                args = get_grouped_args(arg.tokens[1:-1])
                try:
                    k, v = next((k, v) for k in args for g in args[k] for v in g.args)
                except StopIteration:
                    pass
                else:
                    return (tok.text, k, v.text)
    return None


def identify_definitions(text: str) -> list[tuple[str, str]]:
    lexer_output = iter_cmake_tokens("identify_definitions", text)
    matched_parens = parsing.iter_match_parens(lexer_output, {"(": ")", "[": "]"})
    lines = identify_cmake_lines(matched_parens)
    result: list[tuple[str, str]] = []
    for line in lines:
        line_text = text[line.start.index : line.end.index]
        assert line.start.column == 0, line.start
        defn = parse_line_as_definition(line)
        if defn is None:
            result.append(("", line_text))
        else:
            result.append((defn[2], line_text))
    return result


def smart_merge(ancestor: str, current: str, other: str) -> tuple[str, str, str]:
    ancestor_names, ancestor_texts = zip(*identify_definitions(ancestor))
    n = len(ancestor_names)
    assert len(ancestor_texts) == n
    ancestor_delete = [False] * n
    current_match = [-1] * n
    other_match = [-1] * n
    current_insert: list[list[tuple[str, str]]] = [[] for _ in range(n + 1)]
    other_insert: list[list[tuple[str, str]]] = [[] for _ in range(n + 1)]
    current_names, current_texts = zip(*identify_definitions(current))
    other_names, other_texts = zip(*identify_definitions(other))
    current_matcher = difflib.SequenceMatcher(a=ancestor_names, b=current_names, autojunk=False)
    ancestor_out: list[str] = []
    current_out: list[str] = []
    other_out: list[str] = []
    for tag, i1, i2, j1, j2 in current_matcher.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                current_match[i1 + k] = j1 + k
            continue
        for i in range(i1, i2):
            ancestor_delete[i] = True
        # if j1 != j2:
        #     debug_text = f"# current: {tag} {i1} {i2} {j1} {j2}\n"
        #     ancestor_out.append(debug_text)
        #     current_out.append(debug_text)
        #     other_out.append(debug_text)
        for j in range(j1, j2):
            current_insert[i1].append((current_names[j], current_texts[j]))
    other_matcher = difflib.SequenceMatcher(a=ancestor_names, b=other_names)
    for tag, i1, i2, j1, j2 in other_matcher.get_opcodes():
        if tag == "equal":
            for k in range(j2 - j1):
                other_match[i1 + k] = j1 + k
            continue
        for i in range(i1, i2):
            ancestor_delete[i] = True
        # if j1 != j2:
        #     debug_text = f"# other: {tag} {i1} {i2} {j1} {j2}\n"
        #     ancestor_out.append(debug_text)
        #     current_out.append(debug_text)
        #     other_out.append(debug_text)
        for j in range(j1, j2):
            other_insert[i1].append((other_names[j], other_texts[j]))
    for name, text, delete, current_ix, other_ix, current_ins, other_ins in zip(
        [*ancestor_names, ""],
        [*ancestor_texts, ""],
        [*ancestor_delete, False],
        [*current_match, -1],
        [*other_match, -1],
        current_insert,
        other_insert,
    ):
        current_ins_names = {n for n, t in current_ins}
        other_ins_names = {n for n, t in other_ins}
        # if current_ins_names & other_ins_names:
        #     debug_text = f"# Both add - don't merge {current_ins_names=} {other_ins_names=}\n"
        #     ancestor_out.append(debug_text)
        #     current_out.append(debug_text)
        #     other_out.append(debug_text)
        if current_ins_names & other_ins_names:
            # Both add - don't merge
            current_out.extend(t for n, t in current_ins)
            other_out.extend(t for n, t in other_ins)
        else:
            # Merge
            # if current_ins or other_ins:
            #     debug_text = f"# Both add disjoint names - merge {current_ins_names=} {other_ins_names=}\n"
            #     ancestor_out.append(debug_text)
            #     current_out.append(debug_text)
            #     other_out.append(debug_text)
            for n, t in current_ins + other_ins:
                # debug_text = f"# Add {n}\n"
                # ancestor_out.append(debug_text)
                # current_out.append(debug_text)
                # other_out.append(debug_text)
                ancestor_out.append(t)
                current_out.append(t)
                other_out.append(t)
        # if current_ix != -1:
        #     debug_text = f"# Exist in current: {current_names[current_ix]}\n"
        #     ancestor_out.append(debug_text)
        #     current_out.append(debug_text)
        #     other_out.append(debug_text)
        # if other_ix != -1:
        #     debug_text = f"# Exist in other: {other_names[other_ix]}\n"
        #     ancestor_out.append(debug_text)
        #     current_out.append(debug_text)
        #     other_out.append(debug_text)
        if not (name and delete):
            # if name:
            #     debug_text = f"# Not deleted in ancestor: {name}\n"
            #     ancestor_out.append(debug_text)
            #     current_out.append(debug_text)
            #     other_out.append(debug_text)
            ancestor_out.append(text)
        if current_ix != -1:
            current_out.append(current_texts[current_ix])
        if other_ix != -1:
            other_out.append(other_texts[other_ix])

    return "".join(ancestor_out), "".join(current_out), "".join(other_out)


if __name__ == "__main__":
    merging_main(smart_merge)
