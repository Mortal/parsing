import argparse
import traceback
from typing import Iterator, Iterable

from parsing import ParsingError, Token, Position
from parsing.pythonparser.tokens import iter_python_tokens
from parsing.pythonparser.parens import match_python_parens
from parsing.pythonparser.lines import (
    identify_python_lines,
    identify_python_blocks,
    flatten,
    Line,
    Block,
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


def main() -> None:
    args = parser.parse_args()
    exitcode = 0
    for filename in args.filename:
        try:
            with open(filename, "rb") as fp:
                lexer_output = iter_python_tokens(filename, fp.read().decode())
                matched_parens = match_python_parens(lexer_output)
                identified_lines = identify_python_lines(matched_parens)
                identified_blocks = identify_python_blocks(identified_lines)
                if not args.no_output:
                    identified_blocks = dump_identified_blocks(identified_blocks)
                tokens = flatten(identified_blocks)
                tokens = check_contiguous_tokens(tokens)
                list(tokens)
        except ParsingError as e:
            traceback.print_exc()
            print(e.err.message_and_input_line())
            exitcode = 1
        except UnicodeDecodeError as e:
            traceback.print_exc()
            print("%s: UnicodeDecodeError: %s" % (filename, e))
            exitcode = 1
        except KeyboardInterrupt:
            exitcode = 1
            break
    if exitcode:
        raise SystemExit(exitcode)


if __name__ == "__main__":
    main()
