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
        SELECT SUM(IFNULL(files.size, 0)), projects.path, projects.id
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
        size_and_path: list[tuple[int, str, int]] = list(cur.fetchall())
        if not size_and_path:
            cur.execute(
                """
            SELECT 0, projects.path, projects.id
            FROM projects
            WHERE projects.mediadir = ?
            """,
                (mediadirid,),
            )
            size_and_path = list(cur.fetchall())
        if not size_and_path:
            print(mediadirid, mediapath)
        assert size_and_path
        size_and_path.sort(
            key=lambda tup: (not tup[1].lower().endswith(".rpp-bak"), tup)
        )
        cur.execute(
            """
        SELECT (files.id IN (
            SELECT project_files.file FROM projects
            JOIN project_files ON project_files.project = projects.id
            WHERE projects.mediadir = ? AND NOT projects.is_backup
        )) + 2 * (files.id IN (
            SELECT project_files.file FROM projects
            JOIN project_files ON project_files.project = projects.id
            WHERE projects.mediadir = ? AND projects.is_backup
        )) + 4 * (files.id IN (
            SELECT project_files.file FROM projects
            JOIN project_files ON project_files.project = projects.id
            WHERE projects.mediadir = ? AND project_files.muted
        )) AS in_project, SUM(IFNULL(files.size, 0))
        FROM files
        JOIN mediadir_files ON mediadir_files.file = files.id
        WHERE mediadir_files.mediadir = ?
        GROUP BY in_project
        """,
            (mediadirid, mediadirid, mediadirid, mediadirid),
        )
        totsize: dict[int, int] = dict(cur.fetchall())
        inproj = outproj = inbak = inmuted = 0
        for k in totsize:
            if k & 1:
                # in project
                inproj += totsize[k]
                if k & 4:
                    # muted
                    inmuted += totsize[k]
            else:
                # out of project
                if k & 2:
                    inbak += totsize[k]
                    # in backup
                else:
                    outproj += totsize[k]
                    # also not in backup
        
        inproj = totsize.get(1, 0) + totsize.get(3, 0)
        outproj = totsize.get(0, 0)
        inbak = totsize.get(2, 0)
        projsize, projpath, projid = size_and_path[-1]
        if outproj:
            print(f"{humansize(outproj)} unused media in mediadir '{mediapath}'")
        if inbak:
            print(f"{humansize(inbak)} media only used in backups in mediadir '{mediapath}'")
        if inmuted:
            print(f"{humansize(inmuted)} of used media is muted in '{mediapath}'")
        # assert projsize <= inproj, (projsize, inproj)
        if projsize != inproj:
            print(f"{humansize(inproj - projsize)} used in smaller projects but not the largest project in mediadir '{mediapath}' '{projpath}'")
        if inproj > 101e6:
            print(humansize(projsize), projpath)

    cur.execute(
        """SELECT projects.path, files.path, files.size
        FROM project_files
        JOIN projects ON project_files.project = projects.id
        JOIN files ON project_files.file = files.id
        WHERE (
            NOT EXISTS (
                SELECT 1 FROM mediadir_files
                WHERE mediadir_files.mediadir = projects.mediadir
                AND mediadir_files.file = files.id
            )
            AND project_files.type != "VST"
        )
        OR files.size IS NULL
        """
    )
    for projectpath, filepath, filesize in cur.fetchall():
        kind = "Backup" if projectpath.lower().endswith(".rpp-bak") else "Project"
        if kind == "Backup":
            continue
        if filesize is None:
            print(f"{kind} '{projectpath}' uses missing file '{filepath}'")
        else:
            print(f"{kind} '{projectpath}' uses file '{filepath}' not in its media dir")


def humansize(bytes: int) -> str:
    return f"{bytes/2**20:.2f} MB"


if __name__ == "__main__":
    main()
