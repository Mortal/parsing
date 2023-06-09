import argparse
import traceback
from typing import Iterator

from miniscreen import MiniScreen, read_one_keystroke
from miniscreen.minifutures import (
    check_output,
    create_task,
    next_keystroke,
    run_coroutine,
)

from parsing import Parenthesized, ParsingError, Position, Token, pythonparser
from parsing.pythonparser import Block, Line

parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    with open(args.filename) as fp:
        contents = fp.read()
    try:
        tokens = pythonparser.iter_python_tokens(args.filename, contents)
        parens = pythonparser.match_python_parens(tokens)
        lines = pythonparser.identify_python_lines(parens)
        blocks = list(pythonparser.identify_python_blocks(lines))
    except ParsingError as e:
        traceback.print_exc()
        print(e.message_and_input_line())
        raise SystemExit(1)
    run_coroutine(async_main(list(blocks)))


async def async_main(tokens: list[Line | Block | Parenthesized | Token]) -> None:
    with MiniScreen() as ms:
        tokens = [
            t for t in tokens if not (isinstance(t, Line) and t.first_non_blank is None)
        ]
        navstack = [(tokens, 0)][:0]
        current = 0

        def stringify(
            token: Line | Block | Parenthesized | Token | str,
        ) -> Iterator[str]:
            p: Position | None = None
            stack = [token]
            while stack:
                s = stack.pop()
                if isinstance(s, Block):
                    stack.append("    ...")
                    continue
                if isinstance(s, Line):
                    stack += s.tokens[::-1]
                    continue
                if isinstance(s, Parenthesized):
                    stack.append(s.right)
                    stack += s.tokens[::-1]
                    stack.append(s.left)
                    continue
                if isinstance(s, str):
                    yield s
                    p = None
                    continue
                if p is not None and p.lineno == s.start.lineno:
                    n = s.start.column - p.column
                    if n:
                        yield " " * n
                yield s.text
                p = s.end

        def rerender() -> None:
            ms.set_window(
                [
                    ("\x1b[1m" if current == i else "")
                    + (
                        "    ..."
                        if isinstance(token, Block)
                        else "".join(stringify(token))
                        .lstrip()
                        .rstrip("\n")
                        .replace("\n", r"\n")[:90]
                    )
                    + "\x1b[0m"
                    for i, token in enumerate(tokens[:90])
                ]
            )

        screen_dirty = True
        while True:
            if screen_dirty:
                rerender()
                screen_dirty = False
            s = await next_keystroke()
            if s in ("CTRL-D", "CTRL-C"):
                break
            if s == "uparrow":
                current = max(0, current - 1)
            elif s == "downarrow":
                current = min(len(tokens) - 1, current + 1)
            elif s == "home":
                current = 0
            elif s == "end":
                current = len(tokens) - 1
            elif s == "return":
                current_line = tokens[current]
                if isinstance(current_line, Block):
                    navstack.append((tokens, current))
                    tokens = [
                        t
                        for t in current_line.tokens
                        if not (isinstance(t, Line) and t.first_non_blank is None)
                    ]
                    current = 0
                elif isinstance(current_line, Line):
                    navstack.append((tokens, current))
                    tokens = list(current_line.tokens)
                    current = 0
                elif isinstance(current_line, Parenthesized):
                    navstack.append((tokens, current))
                    tokens = [
                        current_line.left,
                        *current_line.tokens,
                        current_line.right,
                    ]
                    current = 0
            elif s in ("-", "backspace", "escape"):
                if navstack:
                    tokens, current = navstack.pop()
            else:
                raise Exception(s)
                continue
            screen_dirty = True


if __name__ == "__main__":
    main()
