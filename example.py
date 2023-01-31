import argparse
import re
import traceback
from parsing import iter_tokens, ParsingError, Token


python_lexer = re.compile(
    r"""
(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)
|(?P<newline>\n)
|(?P<blankline>^[ \t]+$)
|(?P<indent>^[ \t]+)
|(?P<number>[0-9]+)
|(?P<comment>\#.*)
|(?P<op>!=|[<>]=?|->|[][(){},=:@.|%*/+-])
|(?P<string>
    "["]"(?:\\.|[^\\"]|"(?:[^"]|"[^"]))*"["]"
    |'[']'(?:\\.|[^\\']|'(?:[^']|'[^']))*'[']'
    |"(?:\\.|[^\\"])*"
    |'(?:\\.|[^\\'])*'
)
""",
    re.M | re.X,
)


parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    with open(args.filename) as fp:
        contents = fp.read()
    parens = {"{": "}", "[": "]", "(": ")"}
    try:
        paren_stack: list[tuple[str, Token]] = []
        indent = ""
        got_colon = False
        expect_indent = False
        for tok in iter_tokens(python_lexer, args.filename, contents):
            text = tok.text
            if text in parens:
                paren_stack.append((parens[text], tok))
            elif text in parens.values():
                if not paren_stack:
                    raise tok.to_error("unmatched parenthesis")
                if paren_stack[-1][0] != text:
                    raise tok.to_error(
                        "incorrectly matched parentheses: %s%s"
                        % (paren_stack[-1][1].text, text)
                    )
                paren_stack.pop()
            elif not paren_stack:
                if tok.kind == "newline":
                    expect_indent = got_colon
                elif tok.kind == "indent":
                    if expect_indent:
                        if len(text) <= len(indent):
                            raise tok.to_error("expected indent")
                    elif len(text) > len(indent):
                        raise tok.to_error("unexpected indent")
                    indent = text
                else:
                    if tok.pos.column == 0:
                        indent = ""
                    if text == ":":
                        got_colon = True
                    else:
                        got_colon = False

    except ParsingError as e:
        traceback.print_exc()
        lines = e.err.buffer.contents.splitlines()
        print('File "%s", line %s' % (e.err.buffer.filename, e.err.pos.lineno))
        print(lines[e.err.pos.lineno - 1])
        print(" " * e.err.pos.column + "^" + "~" * (e.err.length - 1))
        print(
            "%s:%s:%s: %s"
            % (e.err.buffer.filename, e.err.pos.lineno, e.err.pos.column, e)
        )
        print(
            repr(not not e.err.buffer.contents[e.err.pos.index + e.err.length].strip())
        )


if __name__ == "__main__":
    main()
