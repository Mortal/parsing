import argparse
import re
import traceback
from parsing import iter_tokens, ParsingError


python_lexer = re.compile(
    r'''
(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)
|(?P<number>[0-9]+)
|(?P<comment>\#.*)
|(?P<indent>^[ ]+)
|(?P<op>!=|[<>]=?|->|[][(),=:@.|%*/+-])
|(?P<string>
    "["]"(?:\\.|[^\\"]|"(?:[^"]|"[^"]))*"["]"
    |'[']'(?:\\.|[^\\']|'(?:[^']|'[^']))*'[']'
    |"(?:\\.|[^\\"])*"
    |'(?:\\.|[^\\'])*'
)
''', re.M | re.X)


parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    with open(args.filename) as fp:
        contents = fp.read()
    try:
        list(iter_tokens(python_lexer, args.filename, contents))
    except ParsingError as e:
        traceback.print_exc()
        lines = e.err.buffer.contents.splitlines()
        print('File "%s", line %s' % (e.err.buffer.filename, e.err.pos.lineno))
        print(lines[e.err.pos.lineno - 1])
        print(" " * e.err.pos.column + "^" + "~" * (e.err.length - 1))
        print('%s:%s:%s: %s' % (e.err.buffer.filename, e.err.pos.lineno, e.err.pos.column, e))
        print(repr(not not e.err.buffer.contents[e.err.pos.index + e.err.length].strip()))


if __name__ == "__main__":
    main()
