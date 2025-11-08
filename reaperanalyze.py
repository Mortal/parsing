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
        SELECT SUM(files.size), projects.path, projects.id
        FROM projects
        JOIN project_files ON project_files.project = projects.id
        JOIN files ON project_files.file = files.id
        JOIN mediadir_files ON mediadir_files.file = files.id
        WHERE projects.mediadir = ?
        AND mediadir_files.mediadir = projects.mediadir
        GROUP BY projects.id
        """,
            (mediadirid,),
        )
        size_and_path: list[tuple[int, str, int]] = sorted(cur.fetchall())
        if not size_and_path:
            cur.execute(
                """
            SELECT 0, projects.path, projects.id
            FROM projects
            WHERE projects.mediadir = ?
            """,
                (mediadirid,),
            )
            size_and_path = sorted(cur.fetchall())
        if not size_and_path:
            print(mediadirid, mediapath)
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
        projsize, projpath, projid = max(size_and_path)
        if outproj:
            print(f"{humansize(outproj)} unused media in mediadir '{mediapath}'")
        assert projsize <= inproj
        if projsize != inproj:
            print(f"{humansize(inproj - projsize)} used in smaller projects but not the largest project in mediadir '{mediapath}' '{projpath}'")

    cur.execute(
        """SELECT projects.path, files.path
        FROM project_files
        JOIN projects ON project_files.project = projects.id
        JOIN files ON project_files.file = files.id
        WHERE NOT EXISTS (
            SELECT 1 FROM mediadir_files
            WHERE mediadir_files.mediadir = projects.mediadir
            AND mediadir_files.file = files.id
        )
        AND project_files.type != "VST"
        """
    )
    for projectpath, filepath in cur.fetchall():
        print(f"Project '{projectpath}' uses file '{filepath}' not in its media dir")


def humansize(bytes: int) -> str:
    return f"{bytes/2**20:.2f} MB"


if __name__ == "__main__":
    main()
