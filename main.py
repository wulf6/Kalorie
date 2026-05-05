import json
import os
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

# ── In-memory store ──────────────────────────────────────────────────────────
# Struktura: STORE[username] = { profile, entries, history, receptar, aktivity, weight_log }
STORE: dict = {}
BACKUP_PATH = "/tmp/kalorie_backup.json"

def load_backup():
    """Načti backup ze souboru při startu (pokud existuje)."""
    global STORE
    try:
        if os.path.exists(BACKUP_PATH):
            with open(BACKUP_PATH, "r") as f:
                STORE = json.load(f)
            print(f"Backup načten: {len(STORE)} uživatelů")
    except Exception as e:
        print(f"Backup nelze načíst: {e}")
        STORE = {}

def save_backup():
    """Ulož aktuální stav na disk (best-effort)."""
    try:
        with open(BACKUP_PATH, "w") as f:
            json.dump(STORE, f)
    except Exception as e:
        print(f"Backup nelze uložit: {e}")

def empty_user():
    return {
        "profile": {},
        "entries": {},
        "history": {},
        "receptar": {},   # dict name -> item
        "aktivity": {},   # dict act_id -> item
        "weight_log": {}, # dict date -> item
    }

load_backup()

# ── Merge helpers ────────────────────────────────────────────────────────────

def merge_entries(server: dict, incoming: list) -> dict:
    """Merge jídla podle id a _t timestampu."""
    result = dict(server)
    for item in incoming:
        key = str(item.get("id", ""))
        if not key:
            continue
        if key not in result:
            result[key] = item
        else:
            if (item.get("_t") or 0) > (result[key].get("_t") or 0):
                result[key] = item
    return result

def merge_profile(server: dict, incoming: dict) -> dict:
    """Profil merge - vyhraje novější _profileTs, Gemini klíč podle geminiKeyTs."""
    if not server:
        return incoming
    if not incoming:
        return server

    server_ts = server.get("_profileTs") or 0
    incoming_ts = incoming.get("_profileTs") or 0

    # Vyber základní profil podle _profileTs
    base = incoming if incoming_ts >= server_ts else server

    # Gemini klíč - vyhraje novější geminiKeyTs
    old_key_ts = server.get("geminiKeyTs") or 0
    new_key_ts = incoming.get("geminiKeyTs") or 0
    if old_key_ts > new_key_ts:
        base = dict(base)
        base["geminiKey"] = server.get("geminiKey", "")
        base["geminiKeyTs"] = old_key_ts

    return base

# ── API ───────────────────────────────────────────────────────────────────────

class SyncBody(BaseModel):
    device_id: str
    username: Optional[str] = None
    profile: Optional[dict] = None
    entries: Optional[dict] = None
    history: Optional[dict] = None
    receptar: Optional[list] = None
    aktivity: Optional[list] = None
    weight_log: Optional[list] = None

@app.get("/")
def home():
    return {"status": "OK", "message": "Kalorie backend běží!", "users": len(STORE)}

@app.post("/sync")
def sync(body: SyncBody):
    # Urči klíč uživatele
    if body.username and body.username.strip():
        uid = "user_" + body.username.lower().strip()
    else:
        uid = body.device_id

    if uid not in STORE:
        STORE[uid] = empty_user()

    user = STORE[uid]

    # ── Profil ──
    if body.profile:
        user["profile"] = merge_profile(user.get("profile", {}), body.profile)

    # ── Entries (jídla) ──
    if body.entries:
        for date, incoming_list in body.entries.items():
            server_dict = user["entries"].get(date, {})
            user["entries"][date] = merge_entries(server_dict, incoming_list)

    # ── Historie ──
    if body.history:
        for date, items in body.history.items():
            if date not in user["history"]:
                user["history"][date] = items  # starší dny nepřepisuj

    # ── Receptář ──
    if body.receptar is not None:
        for recept in body.receptar:
            name = recept.get("jidlo", "")
            if name:
                user["receptar"][name] = recept

    # ── Aktivity ──
    if body.aktivity is not None:
        for act in body.aktivity:
            act_id = str(act.get("id", ""))
            if not act_id:
                continue
            if act_id not in user["aktivity"]:
                user["aktivity"][act_id] = act
            else:
                if (act.get("_t") or 0) > (user["aktivity"][act_id].get("_t") or 0):
                    user["aktivity"][act_id] = act

    # ── Weight log ──
    if body.weight_log is not None:
        for entry in body.weight_log:
            date = entry.get("d", "")
            if not date:
                continue
            if date not in user["weight_log"]:
                user["weight_log"][date] = entry
            else:
                if (entry.get("_t") or 0) >= (user["weight_log"][date].get("_t") or 0):
                    user["weight_log"][date] = entry

    # Ulož backup
    save_backup()

    # ── Vrať kompletní stav ──
    return _user_response(user, uid)

@app.get("/data/{uid}")
def get_data(uid: str):
    if uid not in STORE:
        return {"profile": {}, "entries": {}, "history": {}, "receptar": [], "aktivity": [], "weight_log": []}
    return _user_response(STORE[uid], uid)

def _user_response(user: dict, uid: str) -> dict:
    """Převeď interní formát na response - entries jako list, weight_log jako list atd."""
    # Entries: dict of date -> dict of id->item  =>  dict of date -> list
    entries_out = {}
    for date, items_dict in user.get("entries", {}).items():
        entries_out[date] = list(items_dict.values())

    return {
        "ok": True,
        "did": uid,
        "profile": user.get("profile", {}),
        "entries": entries_out,
        "history": user.get("history", {}),
        "receptar": list(user.get("receptar", {}).values()),
        "aktivity": list(user.get("aktivity", {}).values()),
        "weight_log": sorted(user.get("weight_log", {}).values(), key=lambda x: x.get("d", "")),
    }
