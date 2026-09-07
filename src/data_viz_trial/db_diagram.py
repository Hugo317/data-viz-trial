from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import graphviz

PK_COLOR = "#B8860B"
FK_COLOR = "#4B5563"
HEADER_COLOR = "gray20"


@dataclass
class Column:
    name: str
    type: str
    is_pk: bool
    is_fk: bool
    notnull: bool


@dataclass
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass
class Table:
    name: str
    columns: list[Column]
    foreign_keys: list[ForeignKey]


def read_schema(db_path: Path) -> list[Table]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        table_names = [row[0] for row in cur.fetchall()]

        tables = []
        for name in table_names:
            cur.execute(f'PRAGMA table_info("{name}")')
            table_info = cur.fetchall()

            cur.execute(f'PRAGMA foreign_key_list("{name}")')
            foreign_keys = [
                ForeignKey(column=row[3], ref_table=row[2], ref_column=row[4])
                for row in cur.fetchall()
            ]
            fk_columns = {fk.column for fk in foreign_keys}

            columns = [
                Column(
                    name=row[1],
                    type=row[2] or "",
                    is_pk=bool(row[5]),
                    is_fk=row[1] in fk_columns,
                    notnull=bool(row[3]),
                )
                for row in table_info
            ]

            tables.append(Table(name=name, columns=columns, foreign_keys=foreign_keys))
        return tables
    finally:
        conn.close()


def badge_html(col: Column) -> str:
    if col.is_pk and col.is_fk:
        text, color = "PK/FK", PK_COLOR
    elif col.is_pk:
        text, color = "PK", PK_COLOR
    elif col.is_fk:
        text, color = "FK", FK_COLOR
    else:
        return '<TD WIDTH="34"></TD>'
    return (
        f'<TD WIDTH="34" BGCOLOR="{color}">'
        f'<FONT COLOR="white" POINT-SIZE="9"><B> {text} </B></FONT></TD>'
    )


def build_diagram(tables: list[Table]) -> graphviz.Digraph:
    dot = graphviz.Digraph("erd", node_attr={"shape": "plaintext"})
    dot.attr(rankdir="LR", splines="polyline", nodesep="0.6", ranksep="1.0")

    for table in tables:
        rows = "".join(
            '<TR><TD ALIGN="LEFT" PORT="{port}" CELLPADDING="6">'
            '<TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR>'
            "{badge}"
            '<TD ALIGN="LEFT">{name} <FONT COLOR="gray50">{type}</FONT></TD>'
            "</TR></TABLE></TD></TR>".format(
                port=col.name,
                badge=badge_html(col),
                name=col.name,
                type=col.type,
            )
            for col in table.columns
        )
        label = (
            '<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="4">'
            f'<TR><TD BGCOLOR="{HEADER_COLOR}"><FONT COLOR="white"><B>{table.name}</B></FONT></TD></TR>'
            f"{rows}"
            "</TABLE>>"
        )
        dot.node(table.name, label=label)

    for table in tables:
        for fk in table.foreign_keys:
            dot.edge(
                f"{table.name}:{fk.column}:e",
                f"{fk.ref_table}:{fk.ref_column}:w",
                arrowhead="crow",
                arrowtail="tee",
                dir="both",
                color=FK_COLOR,
            )

    add_legend(dot)
    return dot


def add_legend(dot: graphviz.Digraph) -> None:
    legend_table = (
        "<<TABLE BORDER=\"1\" CELLBORDER=\"0\" CELLSPACING=\"0\" CELLPADDING=\"4\">"
        f'<TR><TD BGCOLOR="{HEADER_COLOR}"><FONT COLOR="white"><B>Legend</B></FONT></TD></TR>'
        '<TR><TD ALIGN="LEFT"><TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR>'
        f'<TD WIDTH="34" BGCOLOR="{PK_COLOR}"><FONT COLOR="white" POINT-SIZE="9"><B> PK </B></FONT></TD>'
        '<TD ALIGN="LEFT"> Primary key</TD>'
        "</TR></TABLE></TD></TR>"
        '<TR><TD ALIGN="LEFT"><TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0"><TR>'
        f'<TD WIDTH="34" BGCOLOR="{FK_COLOR}"><FONT COLOR="white" POINT-SIZE="9"><B> FK </B></FONT></TD>'
        '<TD ALIGN="LEFT"> Foreign key</TD>'
        "</TR></TABLE></TD></TR>"
        "</TABLE>>"
    )
    dot.node("legend_table", label=legend_table, shape="plaintext")

    dot.node("legend_one", label="One", shape="plaintext")
    dot.node("legend_many", label="Many", shape="plaintext")
    dot.edge(
        "legend_one",
        "legend_many",
        arrowhead="crow",
        arrowtail="tee",
        dir="both",
        color=FK_COLOR,
    )

    with dot.subgraph(name="cluster_legend") as legend:
        legend.attr(label="", style="invis")
        legend.node("legend_table")
        legend.node("legend_one")
        legend.node("legend_many")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate an ER diagram from a SQLite database.")
    parser.add_argument("db_path", type=Path, help="Path to the SQLite database file")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output file path without extension (default: <db name>_diagram)",
    )
    parser.add_argument(
        "-f", "--format", default="png", choices=["png", "svg", "pdf"],
        help="Output image format (default: png)",
    )
    args = parser.parse_args()

    if not args.db_path.exists():
        raise SystemExit(f"Database file not found: {args.db_path}")

    output = args.output or args.db_path.with_name(f"{args.db_path.stem}_diagram")

    tables = read_schema(args.db_path)
    if not tables:
        raise SystemExit("No tables found in database.")

    dot = build_diagram(tables)
    rendered_path = dot.render(filename=str(output), format=args.format, cleanup=True)
    print(f"Diagram written to {rendered_path}")


if __name__ == "__main__":
    main()
