import argparse
import os
import sqlite3
import traceback
from dataclasses import dataclass
from os import PathLike
from pathlib import PurePath

from parsing import ParsingError
from reaperparser import parse_reaper_project

parser = argparse.ArgumentParser()
parser.add_argument("filename")
parser.add_argument("-o", "--output", required=True)


def check_and_delete_existing(path: str) -> None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = [row[0] for row in cur.fetchall()]
    if set(names) != {
        "files",
        "mediadirs",
        "mediadir_files",
        "projects",
        "project_files",
    }:
        raise SystemExit(f"refusing to overwrite existing '{path}' with tables {names}")
    os.unlink(path)


def main() -> None:
    args = parser.parse_args()
    if os.path.isfile(args.output):
        check_and_delete_existing(args.output)
    conn = sqlite3.connect(args.output)
    conn.executescript("""
    CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT UNIQUE, size INT);
    CREATE TABLE mediadirs (id INTEGER PRIMARY KEY, path TEXT UNIQUE);
    CREATE TABLE mediadir_files (
        id INTEGER PRIMARY KEY,
        mediadir INTEGER REFERENCES mediadirs(id) ON DELETE CASCADE,
        file INTEGER REFERENCES files(id) ON DELETE CASCADE);
    CREATE TABLE projects (id INTEGER PRIMARY KEY, path TEXT UNIQUE, mediadir INTEGER);
    CREATE TABLE project_files (
        id INTEGER PRIMARY KEY,
        project INTEGER REFERENCES projects(id) ON DELETE CASCADE,
        file INTEGER REFERENCES files(id) ON DELETE CASCADE);
    """)
    cur = conn.cursor()

    projectlist: list[ProjectLinks] = []
    if os.path.isfile(args.filename):
        projectlist.append(process(args.filename))
    fileid: dict[PurePath, int] = {}
    for dirpath, dirs, files in os.walk(args.filename):
        dirs.sort()
        files.sort()
        for filename in files:
            path = PurePath(os.path.join(dirpath, filename))
            cur.execute(
                "INSERT INTO files (path, size) VALUES (?, ?)",
                (str(path), os.path.getsize(path)),
            )
            assert cur.lastrowid
            fileid[path] = cur.lastrowid
            ext = filename.lower()
            if ext.endswith(".rpp"):
                project = process(path)
                projectlist.append(project)
    projects: dict[PurePath, list[ProjectLinks]] = {}
    for project in projectlist:
        record_path = PurePath(project.project_path).parent / PurePath(
            project.record_path
        )
        projects.setdefault(record_path, []).append(project)
    for record_path in projects:
        cur.execute("INSERT INTO mediadirs (path) VALUES (?)", (str(record_path),))
        mediadirid = cur.lastrowid
        assert mediadirid
        for dirpath, dirs, files in os.walk(record_path):
            dirs.sort()
            files.sort()
            for filename in files:
                filepath = record_path / dirpath / filename
                cur.execute(
                    "INSERT INTO mediadir_files (mediadir, file) VALUES (?, ?)",
                    (mediadirid, fileid[filepath]),
                )
        for project in projects[record_path]:
            project_dir = PurePath(project.project_path).parent
            cur.execute(
                "INSERT INTO projects (path, mediadir) VALUES (?, ?)",
                (project.project_path, mediadirid),
            )
            projectid = cur.lastrowid
            assert projectid
            for item in project.media_items:
                itempath = project_dir / item
                cur.execute(
                    "INSERT INTO project_files (project, file) VALUES (?, ?)",
                    (projectid, fileid[itempath]),
                )
    cur.close()
    conn.commit()
    conn.close()


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
