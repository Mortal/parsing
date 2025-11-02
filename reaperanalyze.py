import argparse
import sqlite3


parser = argparse.ArgumentParser()
parser.add_argument("filename")


def main() -> None:
    args = parser.parse_args()
    conn = sqlite3.connect(f"file:{args.filename}?mode=ro", uri=True)
    cur = conn.cursor()

    cur.execute("SELECT id, path FROM mediadirs")
    for mediadirid, mediapath in list(cur.fetchall()):
        cur.execute(
            """
        SELECT SUM(files.size), projects.path
        FROM projects
        LEFT JOIN project_files ON project_files.project = projects.id
        LEFT JOIN files ON project_files.file = files.id
        WHERE projects.mediadir = ?
        GROUP BY projects.id
        """,
            (mediadirid,),
        )
        size_and_path: list[tuple[int, str]] = sorted(cur.fetchall())
        assert size_and_path
        cur.execute(
            """
        SELECT files.id IN (
            SELECT project_files.file FROM projects
            JOIN project_files ON project_files.project = projects.id
            WHERE projects.mediadir = ?
        ) AS in_project, SUM(files.size)
        FROM files
        JOIN mediadir_files ON mediadir_files.file = files.id
        WHERE mediadir_files.mediadir = ?
        GROUP BY in_project
        """,
            (mediadirid, mediadirid),
        )
        totsize: dict[bool, int] = dict(cur.fetchall())
        inproj = totsize.get(True, 0)
        outproj = totsize.get(False, 0)
        print(outproj, mediapath, inproj, max(size_and_path))


if __name__ == "__main__":
    main()
