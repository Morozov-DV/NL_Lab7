"""Зберігання історії експериментів у SQLite."""
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance", "history.db")


def _connect(db_path=None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def _session(db_path=None):
    """З'єднання з транзакцією (commit) і гарантованим закриттям."""
    with closing(_connect(db_path)) as conn:
        with conn:
            yield conn


def init_db(db_path=None):
    """Створює таблицю історії, якщо її ще немає."""
    with _session(db_path) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS runs (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   created_at TEXT NOT NULL,
                   params TEXT NOT NULL,
                   metrics TEXT NOT NULL,
                   result TEXT NOT NULL
               )""")


def save_run(result, db_path=None):
    """Зберігає експеримент і повертає його id."""
    with _session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO runs (created_at, params, metrics, result) VALUES (?, ?, ?, ?)",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             json.dumps(result["params"]),
             json.dumps(result["metrics"]),
             json.dumps(result)))
        return cur.lastrowid


def list_runs(limit=20, db_path=None):
    """Останні експерименти (без великих масивів результатів)."""
    with _session(db_path) as conn:
        rows = conn.execute(
            "SELECT id, created_at, params, metrics FROM runs ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
    return [{"id": r["id"], "created_at": r["created_at"],
             "params": json.loads(r["params"]), "metrics": json.loads(r["metrics"])}
            for r in rows]


def get_run(run_id, db_path=None):
    """Повний результат експерименту або None."""
    with _session(db_path) as conn:
        row = conn.execute("SELECT result FROM runs WHERE id = ?", (run_id,)).fetchone()
    return json.loads(row["result"]) if row else None
