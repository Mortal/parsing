import argparse
import traceback
from typing import Callable

from parsing import LineParser, pythonparser
from parsingvimplugin import pythongrammar


class SkipTest(Exception):
    pass


TESTS: list[Callable[[], None]] = []


@TESTS.append
def pythonmerge_comments() -> None:
    lexer_output = pythonparser.iter_python_tokens(
        "-", "    def visit(lines: Iterable[Line | Block]) -> tuple[int, int] | None:\n"
    )
    matched_parens = pythonparser.match_python_parens(lexer_output)
    p = LineParser(list(matched_parens))
    ops = []
    while p.has_next:
        ops.append(pythongrammar.parse_python_expression(p))


parser = argparse.ArgumentParser()
parser.add_argument("--fail-fast", action="store_true")
parser.add_argument("tests", nargs="*")


def main() -> None:
    args = parser.parse_args()
    fails = []
    unmatch = 0
    skipped = 0
    for t in TESTS:
        if args.tests and t.__name__ not in args.tests:
            unmatch += 1
            continue
        try:
            t()
        except SkipTest:
            print("S", end="", flush=True)
            skipped += 1
        except Exception as e:
            if args.fail_fast:
                raise
            fails.append(
                (
                    t,
                    e,
                    traceback.TracebackException.from_exception(e, capture_locals=True),
                )
            )
            print("E", end="", flush=True)
        else:
            print(".", end="", flush=True)
    if unmatch == len(TESTS):
        raise SystemExit("Matched no tests")
    print("")
    print(
        "Ran %s tests, %s failures%s"
        % (
            len(TESTS) - unmatch - skipped,
            len(fails),
            ", %s skipped" % skipped if skipped else "",
        )
    )
    for f, exc, tb in fails:
        print("\n\nFAILURE in %s" % f.__name__)
        for line in tb.format():
            print(line, end="")
    if fails:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
