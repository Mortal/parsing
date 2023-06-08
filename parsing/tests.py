import argparse
import traceback
from typing import Callable

import parsing.cmakemerger
import parsing.pythonmerger


class SkipTest(Exception):
    pass


TESTS: list[Callable[[], None]] = []


@TESTS.append
def cmakemerge_middle() -> None:
    def_f1 = "add(f1)\n"
    def_f2 = "add(f2)\n"
    def_f3 = "add(f3)\n"
    def_f4 = "add(f4)\n"
    a, b, c = parsing.cmakemerger.smart_merge(
        def_f1 + def_f4,
        def_f1 + def_f2 + def_f4,
        def_f1 + def_f3 + def_f4,
    )
    assert a == b == c == def_f1 + def_f2 + def_f3 + def_f4


@TESTS.append
def cmakemerge_start() -> None:
    def_f1 = "add(f1)\n"
    def_f2 = "add(f2)\n"
    def_f3 = "add(f3)\n"
    a, b, c = parsing.cmakemerger.smart_merge(
        def_f3,
        def_f1 + def_f3,
        def_f2 + def_f3,
    )
    assert a == b == c == def_f1 + def_f2 + def_f3


@TESTS.append
def cmakemerge_end() -> None:
    def_f1 = "add(f1)\n"
    def_f2 = "add(f2)\n"
    def_f3 = "add(f3)\n"
    a, b, c = parsing.cmakemerger.smart_merge(
        def_f1,
        def_f1 + def_f2,
        def_f1 + def_f3,
    )
    assert a == b == c == def_f1 + def_f2 + def_f3


@TESTS.append
def pythonmerge_basic_middle() -> None:
    def_f1 = "def f1():\n\tpass\n\n"
    def_f2 = "def f2():\n\tpass\n\n"
    def_f3 = "def f3():\n\tpass\n\n"
    def_f4 = "def f4():\n\tpass\n\n"
    a, b, c = parsing.pythonmerger.smart_merge(
        def_f1 + def_f4,
        def_f1 + def_f2 + def_f4,
        def_f1 + def_f3 + def_f4,
    )
    assert a == b == c == def_f1 + def_f2 + def_f3 + def_f4


@TESTS.append
def pythonmerge_basic_start() -> None:
    def_f1 = "def f1():\n\tpass\n\n"
    def_f2 = "def f2():\n\tpass\n\n"
    def_f3 = "def f3():\n\tpass\n\n"
    a, b, c = parsing.pythonmerger.smart_merge(
        def_f3,
        def_f1 + def_f3,
        def_f2 + def_f3,
    )
    assert a == b == c == def_f1 + def_f2 + def_f3


@TESTS.append
def pythonmerge_basic_end() -> None:
    def_f1 = "def f1():\n\tpass\n\n"
    def_f2 = "def f2():\n\tpass\n\n"
    def_f3 = "def f3():\n\tpass\n\n"
    a, b, c = parsing.pythonmerger.smart_merge(
        def_f1,
        def_f1 + def_f2,
        def_f1 + def_f3,
    )
    assert a == b == c == def_f1 + def_f2 + def_f3


@TESTS.append
def pythonmerge_comments_identify() -> None:
    def_f1 = "# BEGIN f1\n@print\ndef f1():\n\tpass\n\n"
    def_f2 = "# BEGIN f2\n@print\ndef f2():\n\tpass\n\n"
    defs = parsing.pythonmerger.identify_function_definitions(def_f1 + def_f2)
    assert defs == [("f1", def_f1), ("f2", def_f2)]


@TESTS.append
def pythonmerge_comments() -> None:
    def_f1 = "# BEGIN f1\n@print\ndef f1():\n\tpass\n\n"
    def_f2 = "# BEGIN f2\n@print\ndef f2():\n\tpass\n\n"
    def_f3 = "# BEGIN f3\n@print\ndef f3():\n\tpass\n\n"
    def_f4 = "# BEGIN f4\n@print\ndef f4():\n\tpass\n\n"
    a, b, c = parsing.pythonmerger.smart_merge(
        def_f1 + def_f4,
        def_f1 + def_f2 + def_f4,
        def_f1 + def_f3 + def_f4,
    )
    assert a == b == c == def_f1 + def_f2 + def_f3 + def_f4


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
