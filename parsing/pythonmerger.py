#!/usr/bin/env python3
import difflib

from parsing import LineParser, Token, pythonparser
from parsing.merging import merging_main
from parsing.pythonparser import Block, Line, fixup_end_of_block


def identify_function_definitions(text: str) -> list[tuple[str, str]]:
    lexer_output = pythonparser.iter_python_tokens("identify_definitions", text)
    matched_parens = pythonparser.match_python_parens(lexer_output)
    lines = pythonparser.identify_python_lines(matched_parens)
    blocks = list(pythonparser.identify_python_blocks(lines))
    fixup_end_of_block(blocks)
    result: list[tuple[str, str]] = []

    def is_pre(b: Line | Block) -> bool:
        "Returns true if this is a line that goes with the following def."
        if isinstance(b, Block):
            return False
        parser = LineParser(b.tokens).skip_whitespace()
        if not parser.has_next:
            # Blank line
            return False
        t = parser.skip()
        if t.text == "@":
            # Decorator
            return True
        if t.kind == "comment" and b.indent is None:
            # Non-indented comment
            return True
        return False

    def is_post(b: Line | Block) -> bool:
        "Returns true if this is a line that goes with the preceding def."
        if isinstance(b, Block):
            # Indented block
            return True
        if b.indent is not None:
            # Indented line - should only happen with weirdly indented comments
            return True
        if b.first_non_blank is not None:
            # Non-indented line with code
            return False
        parser = LineParser(b.tokens).skip_whitespace()
        if not parser.has_next:
            # Blank line with no comment
            return True
        t = parser.skip()
        if t.kind == "comment":
            # Non-indented comment
            return True
        return False

    i = 0
    while i < len(blocks):
        j = i
        while i < len(blocks) and is_pre(blocks[i]):
            # Consume a decorator
            i += 1
        # Consume a regular Line or Block
        first_line = blocks[i]
        i += 1
        if isinstance(first_line, Line):
            while i < len(blocks) and is_post(blocks[i]):
                # Consume a comment or indented block
                i += 1
        full_text = text[blocks[j].start.index : blocks[i - 1].end.index]
        if isinstance(first_line, Line):
            parser = LineParser(first_line.tokens).skip_whitespace()
            if parser.skip_token("def"):
                name = parser.require_token()
                result.append((name.text, full_text))
                continue
        # Other line
        result.append(("", full_text))
    return result


def smart_merge(ancestor: str, current: str, other: str) -> tuple[str, str, str]:
    ancestor_names, ancestor_texts = zip(*identify_function_definitions(ancestor))
    ancestor_delete = [False] * len(ancestor_names)
    current_match = [-1] * len(ancestor_names)
    other_match = [-1] * len(ancestor_names)
    current_insert: list[list[tuple[str, str]]] = [[] for _ in ancestor_names]
    other_insert: list[list[tuple[str, str]]] = [[] for _ in ancestor_names]
    current_names, current_texts = zip(*identify_function_definitions(current))
    other_names, other_texts = zip(*identify_function_definitions(other))
    current_matcher = difflib.SequenceMatcher(
        a=ancestor_names, b=current_names, autojunk=False
    )
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
        for j in range(j1, j2):
            other_insert[i1].append((other_names[j], other_texts[j]))
    for name, text, delete, current_ix, other_ix, current_ins, other_ins in zip(
        ancestor_names,
        ancestor_texts,
        ancestor_delete,
        current_match,
        other_match,
        current_insert,
        other_insert,
    ):
        current_ins_names = {n for n, t in current_ins}
        other_ins_names = {n for n, t in other_ins}
        if current_ins_names & other_ins_names:
            # Both add - don't merge
            current_out.extend(t for n, t in current_ins)
            other_out.extend(t for n, t in other_ins)
        else:
            # Merge
            for n, t in current_ins + other_ins:
                ancestor_out.append(t)
                current_out.append(t)
                other_out.append(t)
        if not (name and delete):
            ancestor_out.append(text)
        if current_ix != -1:
            current_out.append(current_texts[current_ix])
        if other_ix != -1:
            other_out.append(other_texts[other_ix])

    return "".join(ancestor_out), "".join(current_out), "".join(other_out)


if __name__ == "__main__":
    merging_main(smart_merge)
