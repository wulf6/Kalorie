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
            CREATE TABLE IF NOT EXISTS weight_log (
                device_id TEXT NOT NULL,
                date TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(device_id, date)
            );
            CREATE TABLE IF NOT EXISTS aktivity (
                device_id TEXT NOT NULL,
                act_id TEXT NOT NULL,
                data TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(device_id, act_id)
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
    aktivity: Optional[list] = None
    weight_log: Optional[list] = None

def merge_entries(server_items: list, incoming: list) -> list:
    merged = {str(e.get("id")): e for e in server_items}
    for item in incoming:
        key = str(item.get("id"))
        if key not in merged:
            merged[key] = item
        else:
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

        # Profil - ulož vždy nejnovější, Gemini klíč vyhraje novější timestamp
        if body.profile:
            existing = con.execute("SELECT data FROM profile WHERE device_id=?", (did,)).fetchone()
            if existing:
                old_prof = json.loads(existing["data"])
                new_prof = dict(body.profile)
                # Gemini klíč - vyhraje novější timestamp
                old_ts = old_prof.get("geminiKeyTs", 0) or 0
                new_ts = new_prof.get("geminiKeyTs", 0) or 0
                if old_ts > new_ts:
                    new_prof["geminiKey"] = old_prof.get("geminiKey", "")
                    new_prof["geminiKeyTs"] = old_ts
                # Nový profil má přednost (přišel ze zařízení s novějšími daty)
                final_prof = new_prof
            else:
                final_prof = body.profile

            con.execute("""
                INSERT INTO profile(device_id, data, updated_at) VALUES(?,?,?)
                ON CONFLICT(device_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
            """, (did, json.dumps(final_prof), now))

        # Entries
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

        # Historie
        if body.history:
            for date, items in body.history.items():
                con.execute("""
                    INSERT OR IGNORE INTO history(device_id, date, data, updated_at) VALUES(?,?,?,?)
                """, (did, date, json.dumps(items), now))

        # Receptář
        if body.receptar is not None:
            for recept in body.receptar:
                name = recept.get("jidlo", "")
                if not name:
                    continue
                con.execute("""
                    INSERT INTO receptar(device_id, name, data, updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(device_id, name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """, (did, name, json.dumps(recept), now))

        # Weight log
        if body.weight_log is not None:
            for entry in body.weight_log:
                date = entry.get("d", "")
                if not date:
                    continue
                con.execute("""
                    INSERT INTO weight_log(device_id, date, data, updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(device_id, date) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """, (did, date, json.dumps(entry), now))

        # Aktivity
        if body.aktivity is not None:
            for act in body.aktivity:
                act_id = str(act.get("id", ""))
                if not act_id:
                    continue
                con.execute("""
                    INSERT INTO aktivity(device_id, act_id, data, updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(device_id, act_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                """, (did, act_id, json.dumps(act), now))

        # Vrať vše
        prof_row = con.execute("SELECT data FROM profile WHERE device_id=?", (did,)).fetchone()
        entries_rows = con.execute("SELECT date, data FROM entries WHERE device_id=?", (did,)).fetchall()
        hist_rows = con.execute("SELECT date, data FROM history WHERE device_id=?", (did,)).fetchall()
        rec_rows = con.execute("SELECT data FROM receptar WHERE device_id=?", (did,)).fetchall()
        act_rows = con.execute("SELECT data FROM aktivity WHERE device_id=?", (did,)).fetchall()
        weight_rows = con.execute("SELECT data FROM weight_log WHERE device_id=?", (did,)).fetchall()

    return {
        "ok": True,
        "did": did,
        "profile": json.loads(prof_row["data"]) if prof_row else {},
        "entries": {r["date"]: json.loads(r["data"]) for r in entries_rows},
        "history": {r["date"]: json.loads(r["data"]) for r in hist_rows},
        "receptar": [json.loads(r["data"]) for r in rec_rows],
        "aktivity": [json.loads(r["data"]) for r in act_rows],
        "weight_log": [json.loads(r["data"]) for r in weight_rows],
    }

@app.get("/data/{device_id}")
def get_all(device_id: str):
    with get_db() as con:
        prof = con.execute("SELECT data FROM profile WHERE device_id=?", (device_id,)).fetchone()
        entries = con.execute("SELECT date, data FROM entries WHERE device_id=?", (device_id,)).fetchall()
        hist = con.execute("SELECT date, data FROM history WHERE device_id=?", (device_id,)).fetchall()
        recs = con.execute("SELECT data FROM receptar WHERE device_id=?", (device_id,)).fetchall()
        acts = con.execute("SELECT data FROM aktivity WHERE device_id=?", (device_id,)).fetchall()
        weights = con.execute("SELECT data FROM weight_log WHERE device_id=?", (device_id,)).fetchall()
    return {
        "profile": json.loads(prof["data"]) if prof else {},
        "entries": {r["date"]: json.loads(r["data"]) for r in entries},
        "history": {r["date"]: json.loads(r["data"]) for r in hist},
        "receptar": [json.loads(r["data"]) for r in recs],
        "aktivity": [json.loads(r["data"]) for r in acts],
        "weight_log": [json.loads(r["data"]) for r in weights],
    }
