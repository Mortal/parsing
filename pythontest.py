import argparse
import traceback
from typing import Iterable, Iterator

from parsing import Parenthesized, ParsingError, Position, Token
from parsing.pythonparser import (
    Block,
    Line,
    identify_python_blocks,
    identify_python_lines,
    iter_python_tokens,
    match_python_parens,
)

parser = argparse.ArgumentParser()
parser.add_argument("--no-output", "-n", action="store_true")
parser.add_argument("filename", nargs="+")


def dump_identified_blocks(
    tokens: Iterable[Line | Block], indent: str = ""
) -> Iterator[Line | Block]:
    for o in tokens:
        print("%s%s at %s %s" % (indent, type(o).__name__, o.start, o.end))
        if isinstance(o, Block):
            dump_identified_blocks(o.tokens, o.indent)
        yield o


def check_contiguous_tokens(tokens: Iterable[Token]) -> Iterator[Token]:
    p = Position(0, 1, 0)
    for o in tokens:
        if o.start.index != p.index:
            missing = o.buffer.contents[p.index : o.start.index]
            if missing.strip():
                raise o.to_error(
                    f"Missing bit {missing!r} from {p} to {o.start} in output"
                )
        p = o.start.advanced(o.text, 0, o.length)
        yield o


def flatten(tokens: Iterable[Token | Parenthesized | Line | Block]) -> Iterator[Token]:
    for tok in tokens:
        if isinstance(tok, Token):
            yield tok
        elif isinstance(tok, Parenthesized):
            yield tok.left
            yield from flatten(tok.tokens)
            yield tok.right
        elif isinstance(tok, Line):
            yield from flatten(tok.tokens)
        elif isinstance(tok, Block):
            yield from flatten(tok.tokens)


def main() -> None:
    args = parser.parse_args()
    exitcode = 0
    for filename in args.filename:
        try:
            with open(filename, "rb") as fp:
                contents = fp.read()
            try:
                contents_str = contents.decode("utf-8")
            except UnicodeDecodeError:
                contents_str = contents.decode("latin1")
            lexer_output = iter_python_tokens(filename, contents_str)
            matched_parens = match_python_parens(lexer_output)
            identified_lines = identify_python_lines(matched_parens)
            identified_blocks = identify_python_blocks(identified_lines)
            if not args.no_output:
                identified_blocks = dump_identified_blocks(identified_blocks)
            tokens = flatten(identified_blocks)
            tokens = check_contiguous_tokens(tokens)
            for t in tokens:
                if t.kind.startswith("error: "):
                    print(t.to_error(t.kind).message_and_input_line())
        except ParsingError as e:
            print(
                traceback.format_exc() + "\n" + e.message_and_input_line(), flush=True
            )
            exitcode = 1
        except KeyboardInterrupt:
            exitcode = 1
            break
    if exitcode:
        raise SystemExit(exitcode)


if __name__ == "__main__":
    main()
