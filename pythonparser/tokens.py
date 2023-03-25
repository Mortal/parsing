import re
from typing import Iterator

import parsing
from parsing import Token


python_lexer = re.compile(
    r"""
(?P<name>[\w][\w\d]*)
|(?P<newline>\n)
|(?P<indent>^[ \t]+)
|(?P<number>[0-9]+)
|(?P<comment>\#.*)
|(?P<backslash>\\)
|(?P<semicolon>;)
|(?P<op>-=|//=|//|[=!+*/%|<>]=?|->|-|[][(){},=:@.|%*/+^&~])
|(?P<string>
    "["]"(?:\\(?:.|\n)|[^\\"]|"(?:[^"]|"[^"]))*"["]"
    |'[']'(?:\\(?:.|\n)|[^\\']|'(?:[^']|'[^']))*'[']'
    |"(?:\\(?:.|\n)|[^\\"])*"
    |'(?:\\(?:.|\n)|[^\\'])*'
)
""",
    re.M | re.X,
)


def iter_python_tokens(filename: str, contents: str) -> Iterator[Token]:
    return parsing.iter_tokens(python_lexer, filename, contents)
