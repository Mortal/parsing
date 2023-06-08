import json
from typing import Callable, Iterable, Iterator, Sequence, TypedDict

from parsing import (
    LineParser,
    Parenthesized,
    ParsingErr,
    ParsingError,
    Position,
    Span,
    Token,
    pythonparser,
)
from parsing.pythonparser import Block, Line, fixup_start_of_block, fixup_end_of_block
from .pythongrammar import Binop, Operand, parse_python_expression

_init_commands: list[str] = []


def nnoremap(key: str):
    def wrapper(f):
        _init_commands.append(
            f"nnoremap <silent> {key} :<C-U>py3 parsingvimplugin.codenavigation.{f.__name__}(vim)<CR>"
        )
        return f

    return wrapper


def onoremap(key: str):
    def wrapper(f):
        _init_commands.append(
            f"onoremap <silent> {key} :<C-U>py3 parsingvimplugin.codenavigation.{f.__name__}(vim)<CR>"
        )
        return f

    return wrapper


def vnoremap(key: str):
    def wrapper(f):
        _init_commands.append(
            f"vnoremap <silent> {key} :<C-U>py3 parsingvimplugin.codenavigation.{f.__name__}(vim)<CR>"
        )
        return f

    return wrapper


def identify_buffer_lines(buffer) -> Iterator[Line]:
    lexer_output = pythonparser.iter_python_tokens(
        buffer.name, "\n".join(buffer) + "\n"
    )
    matched_parens = pythonparser.match_python_parens(lexer_output)
    return pythonparser.identify_python_lines(matched_parens)


def identify_buffer_blocks(buffer) -> Iterator[Line | Block]:
    return pythonparser.identify_python_blocks(identify_buffer_lines(buffer))


@onoremap(r"\e")
def plug_select_expression_op(vim) -> None:
    row, col = vim.current.window.cursor
    select_expression(vim, row, col, row, col)


def create_positions(
    span: Span,
) -> list[int | tuple[int] | tuple[int, int] | tuple[int, int, int]]:
    "Convert a Span into something suitable for vim's matchaddpos."
    positions: list[int | tuple[int] | tuple[int, int] | tuple[int, int, int]] = []
    if span.start.lineno == span.end.lineno:
        if span.end.column - span.start.column <= 1:
            # "The first number is the line number, the
            #  second one is the column number (first column is 1, the value
            #  must correspond to the byte index as |col()| would return)."
            return [(span.start.lineno, span.start.column + 1)]
        # "As above, but the third number gives the
        #  length of the highlight in bytes."
        return [
            (
                span.start.lineno,
                span.start.column + 1,
                span.end.column - span.start.column + 1,
            )
        ]
    return [
        (span.start.lineno, span.start.column, 2 ** 30),
        # "A number.  This whole line will be highlighted."
        *range(span.start.lineno + 1, span.end.lineno),
        (span.end.lineno, 1, span.end.column),
    ]


@vnoremap(r"\e")
def plug_select_expression_visual(vim) -> None:
    r1, c1 = vim.current.buffer.mark("<")
    r2, c2 = vim.current.buffer.mark(">")
    try:
        select_expression(vim, r1, c1, r2, c2 + 1)
    except ParsingError as e:
        positions = create_positions(e.err.span)
        vim.command(f'call matchaddpos("PypError", {json.dumps(positions)})')
        vim.command(f"normal! {e.err.span.start.lineno}G")
        raise


def select_expression(vim, row1: int, col1: int, row2: int, col2: int) -> None:
    identified_lines = identify_buffer_lines(vim.current.buffer)
    try:
        myline = next(
            line
            for line in identified_lines
            if line.tokens
            and line.tokens[0].start.lineno <= row1
            and row2 < line.tokens[-1].end.lineno
        )
    except StopIteration:
        # print("line not found")
        return

    def inside1(start: Position) -> bool:
        r1, c1 = start.lineno, start.column
        return (r1, c1) <= (row1, col1)

    def inside2(end: Position) -> bool:
        r2, c2 = end.lineno, end.column
        return (row1, col1) < (r2, c2) and (row2, col2) <= (r2, c2)

    def visit_operand(operand: Operand) -> Span:
        # TODO: Better handling of trailers.
        # Parenthesized trailer, selection properly inside: Recurse.
        # Otherwise, select from atom up until trailer.
        if isinstance(operand.atom, Parenthesized):
            if inside1(operand.atom.left.end) and inside2(operand.atom.right.start):
                return visit_line(operand.atom.tokens) or Span(
                    operand.atom.tokens[0].start, operand.atom.tokens[-1].end
                )
        end = operand.atom.end
        if not inside2(end):
            for n in operand.trailers:
                for m in n:
                    if isinstance(m, Parenthesized):
                        if inside1(m.left.end) and inside2(m.right.start):
                            return visit_line(m.tokens) or Span(
                                m.tokens[0].start, m.tokens[-1].end
                            )
                if inside2(n[-1].end):
                    end = n[-1].end
                    break
        start = operand.atom.start
        if not inside1(start):
            for n in operand.prefixes[::-1]:
                if inside1(n[0].start):
                    start = n[0].start
                    break
        return Span(start, end)

    def visit_binop(binop: Binop) -> Span:
        if inside2(binop.left.end) or not binop.operands:
            return visit_operand(binop.left)
        if not inside1(binop.left.start):
            return Span(binop.start, binop.end)
        i = -1
        while i + 1 < len(binop.operands) and inside1(binop.operands[i + 1][1].start):
            i += 1
        # i is the last operand we are inside of
        j = max(0, i)
        while j < len(binop.operands) and not inside2(binop.operands[j][1].end):
            j += 1
        # j is the first operand
        if j == len(binop.operands):
            return Span(binop.start, binop.end)
        if i == -1:
            start = binop.left.start
        else:
            start = binop.operands[i][1].start
        end = binop.operands[j][1].end
        r1, c1 = start.lineno, start.column
        r2, c2 = end.lineno, end.column
        # raise Exception((r1,c1,r2,c2,row1,col1,row2,col2))
        if (r1, c1) == (row1, col1) and (row2, col2) == (r2, c2):
            # TODO: Precedence compare binop.operands[i][0]
            # and binop.operands[j][0]
            if i <= 0 and j + 1 == len(binop.operands):
                start = binop.left.start
                end = binop.operands[j][1].end
            elif i == -1:
                start = binop.left.start
                end = binop.operands[j + 1][1].end
            elif (j - i) % 2 == 0 or j + 1 == len(binop.operands):
                if i == 0:
                    start = binop.left.start
                else:
                    start = binop.operands[i - 1][1].start
            else:
                end = binop.operands[j + 1][1].end
        return Span(start, end)

    def visit_line(tokens: Sequence[Token | Parenthesized]) -> Span | None:
        p = LineParser(tokens).skip_whitespace()
        while p.has_next:
            n = parse_python_expression(p)
            r1, c1 = n.start.lineno, n.start.column
            r2, c2 = n.end.lineno, n.end.column
            if (r1, c1) <= (row1, col1) and (row2, col2) <= (r2, c2):
                return visit_binop(n)
        return None

    sp = visit_line(myline.tokens)
    if sp is None:
        return
    r1, c1 = sp.start.lineno, sp.start.column
    r2, c2 = sp.end.lineno, sp.end.column
    vim.current.window.cursor = r1, c1
    if c2 == 0:
        vim.command(f"normal! v{r2-1}G$")
    else:
        vim.command("normal! v")
        vim.current.window.cursor = r2, c2 - 1


@onoremap(r"\l")
@vnoremap(r"\l")
def plug_select_line(vim) -> None:
    identified_lines = identify_buffer_lines(vim.current.buffer)
    row, col = vim.current.window.cursor
    try:
        myline = next(
            line
            for line in identified_lines
            if line.tokens
            and line.tokens[0].start.lineno <= row
            and row < line.tokens[-1].end.lineno
        )
    except StopIteration:
        return
    r1 = myline.start.lineno
    r2 = myline.end.lineno - 1
    if r1 == r2:
        vim.command(f"normal! {r1}GV")
    else:
        vim.command(f"normal! {r1}GV{r2}G")


def block_last_lineno(block: Block, indent: str | None = None) -> int:
    if indent is None:
        indent = block.indent
    for line in block.tokens[::-1]:
        if isinstance(line, Block):
            return block_last_lineno(line, indent)
        if line.indent is None:
            # Blank line, or comment at start of line
            continue
        if not line.indent.text.startswith(indent):
            # Dedented comment
            continue
        if all(isinstance(t, Token) and not t.text.strip() for t in line.tokens):
            continue
        return line.end.lineno - 1
    raise Exception("All-blank block")


def select_matching_block(vim, matcher: Callable[[LineParser], bool]) -> None:
    identified_blocks = identify_buffer_blocks(vim.current.buffer)
    row, col = vim.current.window.cursor

    def visit(lines: Iterable[Line | Block]) -> tuple[int, int] | None:
        it = (l for l in lines if isinstance(l, Block) or l.first_non_blank is not None)
        cur = next(it, None)
        while cur is not None and cur.start.lineno <= row:
            if isinstance(cur, Block):
                if block_last_lineno(cur) >= row:
                    return visit(cur.tokens)
                cur = next(it, None)
                continue
            assert cur.first_non_blank is not None
            if cur.colon is None:
                # Not a def or async def cur
                cur = next(it, None)
                continue
            p = LineParser(cur.tokens).skip_whitespace()
            if not matcher(p):
                # Not a block we care about
                cur = next(it, None)
                continue
            start = cur.start.lineno
            cur = next(it, None)
            if isinstance(cur, Block):
                # Interesting block
                if block_last_lineno(cur) < row:
                    # This block does not contain our cursor
                    cur = next(it, None)
                    continue
                # Maybe there's an inner interesting block
                res = visit(cur.tokens)
                if res is not None:
                    return res
                return start, block_last_lineno(cur)
        return None

    res = visit(identified_blocks)
    if res is None:
        return
    start, end = res
    vim.command(f"normal! {start}GV{end}G")


@onoremap(r"\b")
@vnoremap(r"\b")
def plug_select_block(vim) -> None:
    def matcher(p: LineParser) -> bool:
        return True

    select_matching_block(vim, matcher)


@onoremap(r"\f")
@vnoremap(r"\f")
def plug_select_function(vim) -> None:
    def matcher(p: LineParser) -> bool:
        return bool(p.skip_token("def") or p.skip_tokens("async", "def"))

    select_matching_block(vim, matcher)


@onoremap(r"\c")
@vnoremap(r"\c")
def plug_select_class(vim) -> None:
    def matcher(p: LineParser) -> bool:
        return bool(p.skip_token("class"))

    select_matching_block(vim, matcher)


class FunDef(TypedDict):
    decorators: list[Line]
    async_: Token | None
    name: Token
    params: Parenthesized
    ret: Binop | None
    body: Block


class ImpDef(TypedDict):
    name: Token


class VarDef(TypedDict):
    name: Token


Definition = FunDef | ImpDef | VarDef


@nnoremap(r"\d")
def plug_go_to_definition(vim) -> None:
    row, col = vim.current.window.cursor
    identified_lines = list(identify_buffer_lines(vim.current.buffer))
    refn = find_reference_under_cursor(identified_lines, row, col)
    if refn is None:
        return
    refn_path, refn_fun = refn
    identified_blocks = list(pythonparser.identify_python_blocks(identified_lines))
    fixup_start_of_block(identified_blocks)
    fixup_end_of_block(identified_blocks)

    def visit_block(lines: Sequence[Line | Block]) -> dict[str, Definition]:
        defns: dict[str, Definition] = {}
        i = 0
        while i < len(lines):
            r1, c1 = lines[i].start.lineno, lines[i].start.column
            if not (r1, c1) <= (row, col):
                # Past cursor
                break
            j = i
            line = lines[i]
            if isinstance(line, Block):
                defns.update(visit_block(line.tokens))
                i += 1
                continue
            p = LineParser(line.tokens).skip_whitespace()
            decorators: list[Line] = []
            while i < len(lines) and p.skip_token("@"):
                decorators.append(line)
                i += 1
                if i == len(lines):
                    break
                line = lines[i]
                if isinstance(line, Block):
                    break
                p = LineParser(line.tokens).skip_whitespace()
            if i == len(lines):
                break
            async_ = p.skip_token("async")
            if p.skip_token("def"):
                name = p.require_token()
                assert i + 1 < len(lines)
                params = p.skip()
                assert isinstance(params, Parenthesized)
                if p.skip_token("->"):
                    ret = parse_python_expression(p)
                else:
                    ret = None
                p.require_token(":")
                p.skip_whitespace()
                while p.has_next and p.next.kind == "comment":
                    p.skip()
                    p.skip_whitespace()
                assert not p.has_next
                body = lines[i + 1]
                i += 2
                assert isinstance(body, Block), name.buffer.get_line_from_position(body.start)
                fundef: FunDef = {
                    "decorators": decorators,
                    "async_": async_,
                    "name": name,
                    "params": params,
                    "ret": ret,
                    "body": body,
                }
                defns[name.text] = fundef
                r1, c1 = body.start.lineno, body.start.column
                r2, c2 = body.end.lineno, body.end.column
                if (r1, c1) <= (row, col) and (row, col) <= (r2, c2):
                    visit_block(body.tokens)
            i += 1
        return defns

    defns = visit_block(identified_blocks)
    if refn_path[0].text in defns:
        defn = defns[refn_path[0].text]
        if "name" in defn:
            pos = defn["name"].start
            vim.current.window.cursor = pos.lineno, pos.column


def find_reference_under_cursor(identified_lines: Iterable[Line], row: int, col: int) -> tuple[list[Token], bool] | None:
    try:
        myline = next(
            line
            for line in identified_lines
            if line.tokens
            and line.tokens[0].start.lineno <= row
            and row < line.tokens[-1].end.lineno
        )
    except StopIteration:
        # print("line not found")
        return None

    def visit_operand(operand: Operand) -> tuple[list[Token], bool] | None:
        r1, c1 = operand.start.lineno, operand.start.column
        assert (r1, c1) <= (row, col)
        if isinstance(operand.atom, Parenthesized):
            r1, c1 = operand.atom.left.start.lineno, operand.atom.left.start.column
            r2, c2 = operand.atom.right.end.lineno, operand.atom.right.end.column
            if (r1, c1) <= (row, col) and (row, col) < (r2, c2):
                return visit_line(operand.atom.tokens)
            return None
        r2, c2 = operand.atom.end.lineno, operand.atom.end.column
        dotted_path = [operand.atom]
        if (row, col) < (r2, c2):
            is_call = False
            if operand.trailers:
                t = operand.trailers[0][0]
                is_call = isinstance(t, Parenthesized) and t.left.text == "("
            return dotted_path, is_call
        for i, tr in enumerate(operand.trailers):
            if dotted_path and tr[0].text == ".":
                assert isinstance(tr[1], Token)
                dotted_path.append(tr[1])
                r2, c2 = tr[-1].end.lineno, tr[-1].end.column
                if (row, col) < (r2, c2):
                    is_call = False
                    if i + 1 < len(operand.trailers):
                        t = operand.trailers[i + 1][0]
                        is_call = isinstance(t, Parenthesized) and t.left.text == "("
                    return dotted_path, is_call
            else:
                del dotted_path[:]
            for t in tr:
                if isinstance(t, Parenthesized):
                    r1, c1 = t.left.start.lineno, t.left.start.column
                    r2, c2 = t.right.end.lineno, t.right.end.column
                    if (r1, c1) <= (row, col) and (row, col) < (r2, c2):
                        return visit_line(t.tokens)
                    return None
        return None

    def visit_binop(binop: Binop) -> tuple[list[Token], bool] | None:
        r1, c1 = binop.left.start.lineno, binop.left.start.column
        r2, c2 = binop.left.end.lineno, binop.left.end.column
        if (r1, c1) <= (row, col) and (row, col) < (r2, c2):
            return visit_operand(binop.left)
        for _operator, operand in binop.operands:
            r1, c1 = operand.start.lineno, operand.start.column
            r2, c2 = operand.end.lineno, operand.end.column
            if (r1, c1) <= (row, col) and (row, col) < (r2, c2):
                return visit_operand(operand)
        return None

    def visit_line(tokens: Sequence[Token | Parenthesized]) -> tuple[list[Token], bool] | None:
        p = LineParser(tokens).skip_whitespace()
        while p.has_next:
            n = parse_python_expression(p)
            r1, c1 = n.start.lineno, n.start.column
            r2, c2 = n.end.lineno, n.end.column
            if (r1, c1) <= (row, col) and (row, col) < (r2, c2):
                return visit_binop(n)
        return None

    return visit_line(myline.tokens)


def load_vimplugin(vim) -> None:
    vim.command(
        """\
if !hlexists('PypError')
    highlight link PypError SpellBad
endif
"""
    )

    for c in _init_commands:
        vim.command(c)
