import argparse
import os
import subprocess
import traceback
from dataclasses import dataclass
from os import PathLike
from pathlib import PurePath

from parsing import ParsingError
from reaperparser import parse_reaper_project

parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    projectlist: list[ProjectLinks] = []
    if os.path.isfile(args.filename):
        projectlist.append(process(args.filename))
    sizes: dict[PurePath, int] = {}
    uses: dict[PurePath, list[str]] = {}
    for dirpath, dirs, files in os.walk(args.filename):
        dirs.sort()
        files.sort()
        for filename in files:
            path = os.path.join(dirpath, filename)
            sizes[path] = os.path.getsize(path)
            ext = filename.lower()
            if ext.endswith(".rpp"):
                project = process(path)
                projectlist.append(project)
            elif ext.endswith((".wav", ".mp3", ".m4a", ".flac")):
                uses[path] = []
    projects: dict[PurePath, list[ProjectLinks]] = {}
    for project in projectlist:
        record_path = PurePath(project.project_path).parent / PurePath(project.record_path)
        projects.setdefault(record_path, []).append(project)
    owner: dict[PurePath, PurePath] = {}
    outsideuses: dict[str, list[PurePath]] = {}
    for record_path in projects:
        for dirpath, dirs, files in os.walk(record_path):
            dirs.sort()
            files.sort()
            for filename in files:
                filepath = record_path / dirpath / filename
                uses.setdefault(filepath, [])
                ex = owner.setdefault(filepath, record_path)
                if ex != record_path:
                    raise Exception(f"overlapping media dirs: {ex} {record_path} {filepath}")
        for project in projects[record_path]:
            if str(record_path) == "/home/mathias/Music/Media":
                print(project.project_path)
            project_dir = PurePath(project.project_path).parent
            for item in project.media_items:
                itempath = project_dir / PurePath(item)
                uses.setdefault(itempath, []).append(project.project_path)
                if record_path not in itempath.parents:
                    outsideuses.setdefault(project.project_path, []).append(itempath)
    for project_path, itempaths in outsideuses.items():
        print(project_path, "->", *sorted(set(owner[itempath] for itempath in itempaths)))
    record_path_sizes: dict[PurePath, int] = {record_path: 0 for record_path in projects}
    outside_record_path: list[tuple[PurePath, int]] = []
    for path in uses:
        if path not in sizes:
            try:
                sizes[path] = os.path.getsize(path)
            except FileNotFoundError:
                sizes[path] = -1
        if sizes[path] >= 0:
            if path in owner:
                record_path_sizes[owner[path]] += sizes[path]
            else:
                outside_record_path.append((path, sizes[path]))
    sizeinuse = 0
    sizenotinuse = 0
    for path in uses:
        if uses[path]:
            sizeinuse += sizes[path]
        else:
            sizenotinuse += sizes[path]
        print("\t".join(map(str, (len(uses[path]), sizes[path], path))))
    statbroken = 0
    brokennames: set[str] = set()
    for record_path in sorted(projects, key=lambda p: record_path_sizes[p]):
        print("===========", f"{record_path_sizes[record_path] / 2**30:.2f} GB -", record_path)
        for project in projects[record_path]:
            project_dir = PurePath(project.project_path).parent
            broken: list[str] = []
            totsize = 0.0
            for item in project.media_items:
                itempath = project_dir / PurePath(item)
                itemsize = sizes[itempath]
                if itemsize == -1:
                    broken.append(item)
                    brokennames.add(os.path.basename(item))
                else:
                    totsize += itemsize / len(uses[itempath])
            if broken:
                statbroken += 1
                print("BROKEN", round(totsize), project.project_path, *broken)
            else:
                print(round(totsize), project.project_path)
    print("===========", "Outside")
    for path, size in outside_record_path:
        print(size, path, *uses[path])

    print(f"{statbroken} broken projects, {sizeinuse/2**30:.2f} GB used media, {sizenotinuse/2**30:.2f} GB unused media")

    if brokennames:
        findargs = ["find", args.filename]
        for i, nam in enumerate(sorted(brokennames)):
            if i:
                findargs.append("-or")
            findargs += ["-name", nam]
        subprocess.call(findargs)


@dataclass(frozen=True)
class ProjectLinks:
    project_path: str
    record_path: str
    media_items: list[str]


def process(filename: PathLike) -> ProjectLinks:
    seen: set[str] = set()
    with open(filename) as fp:
        contents = fp.read()
    try:
        project = parse_reaper_project(contents, str(filename))
        record_path = project.record_path
        # media = PurePath(record_path)
        media_items: list[str] = []
        for track in project.tracks:
            for item in track.items:
                for source in item.sources:
                    pathstr = source.path
                    if pathstr is None:
                        continue
                    if pathstr not in seen:
                        # assert media in PurePath(pathstr).parents, (filename, media, pathstr)
                        seen.add(pathstr)
                        media_items.append(pathstr)
    except ParsingError as e:
        traceback.print_exc()
        print(e.message_and_input_line())
        raise SystemExit(1)
    return ProjectLinks(str(filename), record_path, media_items)


if __name__ == "__main__":
    main()
