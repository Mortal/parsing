import argparse
import os
import shlex
import subprocess
import traceback
from pathlib import Path

from parsing import Token, ParsingError
from reaperparser import parse_reaper_project, ReaperNode, RSource


parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    if os.path.isfile(args.filename):
        main_process(args.filename)
    else:
        for dirpath, dirs, files in os.walk(args.filename):
            dirs.sort()
            files.sort()
            for filename in files:
                path = os.path.join(dirpath, filename)
                ext = filename.lower()
                if ext.endswith(".rpp"):
                    main_process(path)


def main_process(path: str) -> None:
    print(path)
    with open(path, newline="") as fp:
        contents = fp.read()
    try:
        project = parse_reaper_project(contents, str(path))
    except ParsingError as e:
        traceback.print_exc()
        print(e.message_and_input_line())
        raise SystemExit(1)

    prevtoken: Token | None = None
    output: list[str] = []
    need_convert: list[Path] = []
    converted: list[Path] = []

    def visit(node: ReaperNode) -> None:
        nonlocal prevtoken

        if isinstance(node, RSource) and node.type == "WAVE":
            pathstr = node.path
            assert pathstr is not None
            relpath = Path(pathstr)
            assert relpath.suffix.lower() == ".wav", relpath.suffix
            siblings = {p.suffix.lower(): p for p in (Path(path).parent / relpath).parent.iterdir() if p.stem == relpath.stem and p.suffix.lower() != ".wav"}
            if prevtoken is not None:
                assert prevtoken.buffer is node.inner.left.buffer
                ws = node.inner.left.buffer.contents[prevtoken.end.index : node.inner.left.start.index]
                assert not ws.strip(), (ws, prevtoken, node.inner.left)
                output.append(ws)
            if ".flac" in siblings:
                newrelpath = relpath.parent / siblings[".flac"].name
                newpath = Path(path).parent / newrelpath
                if newpath not in converted:
                    converted.append(newpath)
                output.append(f'<SOURCE FLAC\r\nFILE "{newrelpath}"\r\n>\r\n')
            elif ".mp3" in siblings:
                newrelpath = relpath.parent / siblings[".mp3"].name
                newpath = Path(path).parent / newrelpath
                if newpath not in converted:
                    converted.append(newpath)
                output.append(f'<SOURCE MP3\r\nFILE "{newrelpath}"\r\n>\r\n')
            elif not siblings:
                newpath = Path(path).parent / relpath
                if newpath not in need_convert:
                    need_convert.append(newpath)
                    print(need_convert[-1])
                output.append(f'<SOURCE WAVE\r\nFILE "{relpath}"\r\n>\r\n')
            else:
                raise Exception(f"unknown siblings: {siblings}")
            prevtoken = node.inner.tail[-1] if node.inner.tail else node.inner.right
            return
        for child in node.visit_reaper():
            if isinstance(child, Token):
                if prevtoken is not None:
                    assert prevtoken.buffer is child.buffer
                    ws = child.buffer.contents[prevtoken.end.index : child.start.index]
                    assert not ws.strip(), (ws, prevtoken, child)
                    output.append(ws)
                output.append(child.text)
                prevtoken = child
                continue
            visit(child)

    visit(project)

    if need_convert:
        print("Please convert the following to FLAC or MP3:")
        print(f'for i in {" ".join(shlex.quote(str(p)) for p in need_convert)}; do lame -V2 $i || break; done')
        if converted:
            print(f"({len(converted)} already converted)")
    elif converted:
        print("Emitting new project with the following converted:")
        for pathpath in converted:
            print(pathpath)
        with open(f"{path}~", "w", newline="") as ofp:
            ofp.write(contents)
        subprocess.check_call(("diff", path, f"{path}~"))
        with open(f"{path}_", "w", newline="") as ofp:
            ofp.write("".join(output))
        subprocess.check_call(("mv", "-T", f"{path}_", path))
        # Run the parser to check that it works
        parse_reaper_project("".join(output), str(path))


if __name__ == "__main__":
    main()
