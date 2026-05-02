import os
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Kalorie AI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "kalorie.db"

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                device_id TEXT PRIMARY KEY,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS profile (
                device_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS entries (
                device_id TEXT NOT NULL,
                date TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(device_id, date)
            );
            CREATE TABLE IF NOT EXISTS receptar (
                device_id TEXT NOT NULL,
                name TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(device_id, name)
            );
            CREATE TABLE IF NOT EXISTS history (
                device_id TEXT NOT NULL,
                date TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(device_id, date)
            );
        """)

init_db()

@contextmanager
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

class SyncBody(BaseModel):
    device_id: str
    username: Optional[str] = None
    profile: Optional[dict] = None
    entries: Optional[dict] = None
    history: Optional[dict] = None
    receptar: Optional[list] = None

def merge_entries(server_items: list, incoming: list) -> list:
    """Merge dvou seznamů jídel - vyhraj vždy záznam s novějším _t timestampem."""
    merged = {str(e.get("id")): e for e in server_items}
    for item in incoming:
        key = str(item.get("id"))
        if key not in merged:
            merged[key] = item
        else:
            # Vyhraj novější _t
            server_t = merged[key].get("_t", 0) or 0
            incoming_t = item.get("_t", 0) or 0
            if incoming_t > server_t:
                merged[key] = item
    return list(merged.values())

@app.get("/")
def home():
    return {"status": "OK", "message": "Kalorie backend běží!"}

@app.post("/sync")
def sync(body: SyncBody):
    if body.username and body.username.strip():
        did = "user_" + body.username.lower().strip()
    else:
        did = body.device_id

    now = datetime.utcnow().isoformat()

    with get_db() as con:
        con.execute("INSERT OR IGNORE INTO users(device_id) VALUES(?)", (did,))

        if body.profile:
            con.execute("""
                INSERT INTO profile(device_id, data, updated_at) VALUES(?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
            """, (did, json.dumps(body.profile), now))

        if body.entries:
            for date, incoming in body.entries.items():
                row = con.execute(
                    "SELECT data FROM entries WHERE device_id=? AND date=?", (did, date)
                ).fetchone()

                server_items = json.loads(row["data"]) if row else []
                merged = merge_entries(server_items, incoming)

                con.execute("""
                    INSERT INTO entries(device_id, date, data, updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(device_id, date) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """, (did, date, json.dumps(merged), now))

        if body.history:
            for date, items in body.history.items():
                con.execute("""
                    INSERT OR IGNORE INTO history(device_id, date, data, updated_at) VALUES(?,?,?,?)
                """, (did, date, json.dumps(items), now))

        if body.receptar is not None:
            for recept in body.receptar:
                name = recept.get("jidlo", "")
                if not name:
                    continue
                con.execute("""
                    INSERT INTO receptar(device_id, name, data, updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(device_id, name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """, (did, name, json.dumps(recept), now))

        prof_row = con.execute("SELECT data FROM profile WHERE device_id=?", (did,)).fetchone()
        entries_rows = con.execute("SELECT date, data FROM entries WHERE device_id=?", (did,)).fetchall()
        hist_rows = con.execute("SELECT date, data FROM history WHERE device_id=?", (did,)).fetchall()
        rec_rows = con.execute("SELECT data FROM receptar WHERE device_id=?", (did,)).fetchall()

    return {
        "ok": True,
        "did": did,
        "profile": json.loads(prof_row["data"]) if prof_row else {},
        "entries": {r["date"]: json.loads(r["data"]) for r in entries_rows},
        "history": {r["date"]: json.loads(r["data"]) for r in hist_rows},
        "receptar": [json.loads(r["data"]) for r in rec_rows],
    }

@app.get("/data/{device_id}")
def get_all(device_id: str):
    with get_db() as con:
        prof = con.execute("SELECT data FROM profile WHERE device_id=?", (device_id,)).fetchone()
        entries = con.execute("SELECT date, data FROM entries WHERE device_id=?", (device_id,)).fetchall()
        hist = con.execute("SELECT date, data FROM history WHERE device_id=?", (device_id,)).fetchall()
        recs = con.execute("SELECT data FROM receptar WHERE device_id=?", (device_id,)).fetchall()
    return {
        "profile": json.loads(prof["data"]) if prof else {},
        "entries": {r["date"]: json.loads(r["data"]) for r in entries},
        "history": {r["date"]: json.loads(r["data"]) for r in hist},
        "receptar": [json.loads(r["data"]) for r in recs],
    }
