"""Tiny schema upgrade step run at startup.

create_all() makes missing tables but never adds columns to existing ones, so new nullable
columns are added here with ALTER TABLE. Safe to run every time: it only adds what is missing.
"""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

# table -> [(column, SQL type)]; all nullable, so existing rows stay valid.
NEW_COLUMNS = {
    "attendance_sessions": [
        ("scheduled_session", "VARCHAR(80)"),
        ("scheduled_login", "TIME"),
        ("scheduled_logout", "TIME"),
        ("day_schedule", "TEXT"),
    ],
}


def add_missing_columns(engine: Engine) -> list[str]:
    added = []
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, columns in NEW_COLUMNS.items():
            if not insp.has_table(table):
                continue
            have = {c["name"] for c in insp.get_columns(table)}
            for name, sql_type in columns:
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type} NULL"))
                    added.append(f"{table}.{name}")
    return added
