import argparse
import re
from parsing import iter_tokens


python_lexer = re.compile(
    r'''
(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)
|(?P<indent>^[ ]+)
|(?P<op>!=|->|[][(),=:@-])
|(?P<string>"(?:\\.|[^\\"])")
''', re.M | re.X)


parser = argparse.ArgumentParser()


def main() -> None:
    args = parser.parse_args()
    filename = "parsing.py"
    with open(filename) as fp:
        contents = fp.read()
    list(iter_tokens(python_lexer, filename, contents))


if __name__ == "__main__":
    main()
