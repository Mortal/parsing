#!/usr/bin/env python3
import argparse
import email.charset
import email.header
import email.utils
import itertools
import mailbox
import os
import re
import string
import time
import traceback

from parsing import iter_tokens, ParsingError


parser = argparse.ArgumentParser()
parser.add_argument("-s", "--script")
parser.add_argument("-m", "--maildir")


sieve_lexer = re.compile(
    r"""
(?P<identifier>[a-z][a-z]*)
|(?P<comment>\#.*)
|(?P<operator>:[a-z]+)
|(?P<string>"(?:\\.|[^"\\])*")
|(?P<atom>[][{}();,])
|(?P<eof>\Z)
""",
    re.M | re.X
)


def parse_sieve_script(s: str, filename="-"):
    tokens = iter_tokens(sieve_lexer, filename, s)
    head_token = next(tokens)
    i = [0]

    def peek(s) -> str | None:
        if len(s) == 1:
            if head_token.kind != "atom":
                return None
            if head_token.text != s:
                return None
        elif s in ("comment", "eof", "identifier", "operator", "string"):
            if head_token.kind != s:
                return None
        elif s[:1] in string.ascii_lowercase:
            if head_token.kind != "identifier":
                return None
            if head_token.text != s:
                return None
        elif s[:1] == ":":
            if head_token.kind != "operator":
                return None
            if head_token.text != s:
                return None
        return head_token.text

    def skip(s):
        nonlocal head_token

        res = peek(s)
        if res is None:
            return None
        head_token = next(tokens)
        return res

    def lineno() -> int:
        if head_token is None:
            return -1
        return head_token.start.lineno

    def require(s) -> str:
        res = skip(s)
        if res is None:
            raise head_token.to_error("Expected %r but got %s" % (s, head_token.kind))
        return res

    def parse_string():
        v = require("string")
        return re.sub(r"\\(.)", r"\1", v[1:-1])

    def parse_list():
        res = []
        require("[")
        while peek("string") is not None:
            res.append(parse_string())
            if skip(",") is None:
                break
        require("]")
        return res

    def junk_atom():
        if skip("comment") or skip("identifier") or skip("operator") or skip("string") or skip(";"):
            return
        if peek("("):
            junk_paren()
        if peek("{"):
            junk_brace()
        raise head_token.to_error("Can't junk this")

    def junk_paren():
        require("(")
        while not skip(")"):
            junk_atom()

    def junk_brace():
        require("{")
        while not skip("}"):
            junk_atom()

    def junk_cond():
        while not peek("{"):
            junk_atom()

    def parse_cond():
        if skip("allof"):
            require("(")
            conds = []
            while True:
                conds.append(parse_cond())
                if skip(")"):
                    break
                require(",")
            return "allof", conds
        if skip("header"):
            op = require("operator")
            header_key = parse_string()
            needle = parse_string()
            return "header", (op, header_key, needle)
        if skip("address"):
            is_all = skip(":all") is not None
            require(":is")
            header_key = parse_string()
            needle = parse_string()
            return "address", (is_all, header_key, needle)
        if skip("not"):
            return "not", (parse_cond(),)
        print("-:%s: Unknown condition %r" % (lineno(), head_token.text[:10] if head_token else ""))
        junk_cond()
        return None

    def parse_then():
        if skip("fileinto"):
            is_create = skip(":create") is not None
            folder = parse_string()
            require(";")
            return "fileinto", (is_create, folder)
        if skip("redirect"):
            is_copy = skip(":copy") is not None
            recipient = parse_string()
            require(";")
            return "redirect", (is_copy, recipient)
        if peek("if"):
            return parse_if()
        raise head_token.to_error("Expected 'fileinto', 'redirect' or 'if'")

    def parse_then_list():
        res = []
        while not peek("}"):
            res.append(parse_then())
        return res

    def parse_if():
        require("if")
        cond = parse_cond()
        if cond is None:
            junk_brace()
            return None
        require("{")
        then = parse_then_list()
        require("}")
        return "if", cond, then

    def parse_statement():
        if skip("comment"):
            return None
        if skip("require"):
            parse_list()
            require(";")
            return None
        if peek("if"):
            return parse_if()
        if peek("eof"):
            return None
        raise head_token.to_error("Unknown start of statement %s" % head_token.kind)

    def parse_document():
        statements = []
        while peek("eof") is None:
            st = parse_statement()
            if st is not None:
                statements.append(st)
        return statements

    return parse_document()


def evaluate_script(script, message):
    actions = []
    why = []
    capture = []

    def evaluate_header(op, header_key, needle):
        try:
            header_value = message[header_key]
        except KeyError:
            return False
        if not header_value:
            return False
        if op == ":matches":
            pattern = re.sub(r"[^*]+|\*", lambda mo: "(.*)" if mo.group() == "*" else re.escape(mo.group()), needle)
            return re.search(pattern, str(header_value))
        elif op == ":is":
            return str(header_value) == needle
        elif op == ":contains":
            return needle in str(header_value)
        else:
            raise Exception("Unknown header op %r" % (op,))

    def evaluate_address(is_all, header_key, needle):
        header_values = message.get_all(header_key)
        if not header_values:
            return False
        emails = [
            e
            for n, e in
            email.utils.getaddresses(header_values)
        ]
        if is_all and len(emails) != 1:
            return False
        return needle in emails

    def evaluate_cond(cond_key, cond_args):
        if cond_key == "header":
            mo = evaluate_header(*cond_args)
            if not mo:
                return None
            if mo is True:
                return (cond_key, cond_args, None)
            return (cond_key, cond_args, mo)
        elif cond_key == "address":
            return evaluate_address(*cond_args) and (cond_key, cond_args, None)
        elif cond_key == "allof":
            mo = None
            for e in cond_args:
                r = evaluate_cond(*e)
                if not r:
                    return None
                if r[2]:
                    mo = r[2]
            return (cond_key, cond_args, mo)
        elif cond_key == "not":
            return not evaluate_cond(*cond_args[0]) and (cond_key, cond_args, None)
        raise Exception("Unknown cond %r" % (cond_key,))

    def evaluate_if(cond, then):
        r = evaluate_cond(*cond)
        if r:
            why.append(r[:2])
            if r[2]:
                capture.append(r[2])
            evaluate_body(then)
            if r[2]:
                capture.pop()
            why.pop()

    def evaluate_body(script):
        for st in script:
            if st[0] == "if":
                evaluate_if(st[1], st[2])
            elif st[0] == "fileinto":
                is_create, folder = st[1]

                def repl(mo):
                    if not capture:
                        return ""
                    which = int(mo.group(1))
                    try:
                        return capture[-1].group(which)
                    except IndexError:
                        return ""

                actions.append((why[:], ("fileinto", re.sub(r"\$\{(\d+)\}", repl, folder))))
            elif st[0] == "redirect":
                actions.append((why[:], st))
            else:
                raise Exception("Unknown statement %r" % (st[0],))

    evaluate_body(script)
    return actions


def messages_by_newest(maildir, *, max_age=None, n=None):
    min_mtime = None if max_age is None else time.time() - max_age
    mtimes_keys = []
    for key in maildir.iterkeys():
        path = os.path.join(maildir._path, maildir._lookup(key))
        mt = os.stat(path).st_mtime
        if min_mtime is not None and mt < min_mtime:
            continue
        mtimes_keys.append((mt, key))
    mtimes_keys.sort(reverse=True)
    res = (maildir[k] for t, k in mtimes_keys)
    return itertools.islice(res, 0, n)


def decode_any_header(value):
    """Wrapper around email.header.decode_header to absorb all errors."""
    try:
        chunks = email.header.decode_header(value)
    except email.errors.HeaderParseError:
        chunks = [(value, None)]
    header = email.header.Header()
    for string, charset in chunks:
        if charset is not None:
            if not isinstance(charset, email.charset.Charset):
                charset = email.charset.Charset(charset)
        try:
            try:
                header.append(string, charset, errors="strict")
            except LookupError:
                header.append(string, "latin1", errors="replace")
            except UnicodeDecodeError:
                header.append(string, "latin1", errors="strict")
        except:
            header.append(string, charset, errors="replace")
    return header


def main() -> None:
    args = parser.parse_args()
    script_path = args.script
    if script_path is None:
        script_path = os.path.expanduser("~/dovecot/sieve/script.sieve")
    maildir_path = args.maildir
    if maildir_path is None:
        maildir_path = os.path.expanduser("~/Maildir/.Spam")
    with open(script_path) as fp:
        try:
            script = parse_sieve_script(fp.read(), script_path)
        except ParsingError as e:
            traceback.print_exc()
            print(e.err.message_and_input_line())
            raise SystemExit(1)
    n = 0
    spamdir = mailbox.Maildir(maildir_path)
    days = 24*3600
    max_age = 180*days
    for message in messages_by_newest(spamdir, max_age=max_age):
        res = evaluate_script(script, message)
        actions = [a for w, a in res]
        if ("fileinto", "INBOX.Spam") not in actions:
            n += 1
            print(n, "In spam, but not matched:", str(decode_any_header(message["Subject"])), actions)
    n = 0
    inbox = mailbox.Maildir(os.path.expanduser("~/Maildir"))
    for message in messages_by_newest(inbox, max_age=max_age):
        res = evaluate_script(script, message)
        actions = [a for w, a in res]
        if ("fileinto", "INBOX.Spam") in actions:
            n += 1
            print(n, "In Inbox, but matched:", str(decode_any_header(message["Subject"])), res)


if __name__ == "__main__":
    main()
