from __future__ import annotations

import csv
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

_INT_RE = re.compile(r"[+-]?\d+")
_REAL_RE = re.compile(r"[+-]?(\d+\.\d*|\.\d+)([eE][+-]?\d+)?")


@dataclass
class ForeignKey:
    table: str
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableSpec:
    csv_path: Path
    table_name: str
    columns: list[str]
    pk: list[str]
    rows: list[dict[str, str]] = field(default_factory=list)


def prompt(message: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{message}{suffix}: ").strip()
    return value or default


def prompt_int(message: str) -> int:
    while True:
        raw = input(f"{message}: ").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("Please enter a positive whole number.")


def prompt_yes_no(message: str) -> bool:
    raw = input(f"{message} [y/N]: ").strip().lower()
    return raw in ("y", "yes")


def prompt_csv_path(message: str) -> Path:
    while True:
        raw = input(f"{message}: ").strip()
        path = Path(raw)
        if not path.exists():
            print(f"File not found: {path}")
            continue
        try:
            with path.open(newline="", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                header = next(reader, None)
            if not header:
                print(f"{path} has no header row.")
                continue
        except OSError as exc:
            print(f"Could not read {path}: {exc}")
            continue
        return path


def prompt_columns(message: str, columns: list[str]) -> list[str]:
    while True:
        raw = input(f"{message}: ").strip()
        if not raw:
            return []
        chosen = [c.strip() for c in raw.split(",") if c.strip()]
        unknown = [c for c in chosen if c not in columns]
        if unknown:
            print(f"Unknown column(s) {unknown}; available: {columns}")
            continue
        return chosen


def prompt_choice(message: str, choices: list[str]) -> str:
    while True:
        raw = input(f"{message} ({'/'.join(choices)}): ").strip()
        if raw in choices:
            return raw
        print(f"Please enter one of: {choices}")


def load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        columns = list(reader.fieldnames or [])
        rows = list(reader)
    return columns, rows


def sniff_type(values: list[str]) -> str:
    non_empty = [v for v in values if v != ""]
    if not non_empty:
        return "TEXT"
    if all(_INT_RE.fullmatch(v) for v in non_empty):
        return "INTEGER"
    if all(_REAL_RE.fullmatch(v) for v in non_empty):
        return "REAL"
    return "TEXT"


def convert_value(value: str, sql_type: str) -> object:
    if value == "":
        return None
    if sql_type == "INTEGER":
        return int(value)
    if sql_type == "REAL":
        return float(value)
    return value


def build_create_table(
    table: TableSpec, types: dict[str, str], fks: list[ForeignKey]
) -> str:
    col_defs = [f'"{c}" {types[c]}' for c in table.columns]
    constraints = []
    if table.pk:
        pk_cols = ", ".join(f'"{c}"' for c in table.pk)
        constraints.append(f"PRIMARY KEY ({pk_cols})")
    for fk in fks:
        constraints.append(
            f'FOREIGN KEY ("{fk.column}") REFERENCES "{fk.ref_table}" ("{fk.ref_column}")'
        )
    body = ",\n  ".join(col_defs + constraints)
    return f'CREATE TABLE "{table.table_name}" (\n  {body}\n)'


def collect_tables(n: int) -> list[TableSpec]:
    tables: list[TableSpec] = []
    used_names: set[str] = set()
    for i in range(1, n + 1):
        print(f"\n--- Table {i} of {n} ---")
        csv_path = prompt_csv_path("CSV file path")
        columns, rows = load_csv(csv_path)

        while True:
            table_name = prompt("Table name", default=csv_path.stem)
            if table_name in used_names:
                print(f"Table name {table_name!r} already used; choose another.")
                continue
            break
        used_names.add(table_name)

        print(f"Columns found: {', '.join(columns)}")
        pk: list[str] = []
        if prompt_yes_no("Does this table have a primary key?"):
            pk = prompt_columns("Primary key column(s) (comma-separated for composite)", columns)
            while not pk:
                print("Enter at least one column.")
                pk = prompt_columns(
                    "Primary key column(s) (comma-separated for composite)", columns
                )

        tables.append(
            TableSpec(csv_path=csv_path, table_name=table_name, columns=columns, pk=pk, rows=rows)
        )
    return tables


def collect_foreign_keys(tables: list[TableSpec]) -> list[ForeignKey]:
    print("\n--- Foreign keys ---")
    table_names = [t.table_name for t in tables]
    by_name = {t.table_name: t for t in tables}
    fks: list[ForeignKey] = []

    if not prompt_yes_no("Add a foreign key?"):
        return fks

    while True:
        fk_table = prompt_choice("  FK table", table_names)
        fk_column = prompt_columns("  FK column", by_name[fk_table].columns)
        while len(fk_column) != 1:
            print("  Enter exactly one column.")
            fk_column = prompt_columns("  FK column", by_name[fk_table].columns)
        ref_table = prompt_choice("  References table", table_names)
        ref_column = prompt_columns("  References column", by_name[ref_table].columns)
        while len(ref_column) != 1:
            print("  Enter exactly one column.")
            ref_column = prompt_columns("  References column", by_name[ref_table].columns)

        fks.append(ForeignKey(fk_table, fk_column[0], ref_table, ref_column[0]))

        if not prompt_yes_no("Add another foreign key?"):
            break
    return fks


def build_database(db_path: Path, tables: list[TableSpec], fks: list[ForeignKey]) -> bool:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        cur = conn.cursor()
        types_by_table: dict[str, dict[str, str]] = {}

        for table in tables:
            types = {
                c: sniff_type([row[c] for row in table.rows]) for c in table.columns
            }
            types_by_table[table.table_name] = types
            table_fks = [fk for fk in fks if fk.table == table.table_name]
            cur.execute(build_create_table(table, types, table_fks))

        for table in tables:
            types = types_by_table[table.table_name]
            placeholders = ", ".join("?" for _ in table.columns)
            col_list = ", ".join(f'"{c}"' for c in table.columns)
            insert_sql = f'INSERT INTO "{table.table_name}" ({col_list}) VALUES ({placeholders})'
            values = [
                tuple(convert_value(row[c], types[c]) for c in table.columns)
                for row in table.rows
            ]
            try:
                cur.executemany(insert_sql, values)
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                print(f"\nError loading '{table.table_name}': {exc}")
                if table.pk:
                    print(
                        f"  The primary key {table.pk} is not unique across all rows "
                        f"in {table.csv_path}. Re-run and choose different key column(s)."
                    )
                print("No changes were saved.")
                return False
            print(f"  {table.table_name}: {len(values)} rows")

        conn.commit()

        conn.execute("PRAGMA foreign_keys = ON")
        violations = cur.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            print("\nWarning: foreign key violations found:")
            for child_table, rowid, parent_table, _ in violations:
                print(f"  {child_table} (rowid {rowid}) -> missing match in {parent_table}")
        return True
    finally:
        conn.close()


def main() -> None:
    print("=== CSV to SQLite ===")
    db_path = Path(prompt("SQLite database file to create"))
    n_tables = prompt_int("How many tables (CSV files)?")

    tables = collect_tables(n_tables)
    fks = collect_foreign_keys(tables)

    print("\nCreating database...")
    if build_database(db_path, tables, fks):
        print(f"Done: {db_path}")


if __name__ == "__main__":
    main()
