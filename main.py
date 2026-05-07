import json
import os
import base64
import urllib.request
import urllib.error
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

# ── Konfigurace ───────────────────────────────────────────────────────────────
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO = "wulf6/Kalorie"
GITHUB_FILE = "data.json"
GITHUB_BRANCH = "main"
BACKUP_PATH = "/tmp/kalorie_backup.json"

# ── In-memory store ───────────────────────────────────────────────────────────
STORE: dict = {}

def github_get_file():
    """Stáhni data.json z GitHubu."""
    if not GITHUB_TOKEN:
        return None, None
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "kalorie-backend"
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}, None  # soubor neexistuje
        print(f"GitHub GET error: {e}")
        return None, None
    except Exception as e:
        print(f"GitHub GET error: {e}")
        return None, None

def github_save_file(data: dict, sha: Optional[str] = None):
    """Ulož data.json na GitHub."""
    if not GITHUB_TOKEN:
        return False
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE}"
    content = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    body = {
        "message": f"sync {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
        "content": content,
        "branch": GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "kalorie-backend"
        },
        method="PUT"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("content", {}).get("sha")
    except Exception as e:
        print(f"GitHub PUT error: {e}")
        return False

def load_data():
    """Načti data - nejdřív z GitHubu, pak z /tmp backup."""
    global STORE
    # Zkus GitHub
    gh_data, sha = github_get_file()
    if gh_data is not None:
        STORE = gh_data
        print(f"Data načtena z GitHubu: {len(STORE)} uživatelů")
        # Ulož lokální backup
        try:
            with open(BACKUP_PATH, "w") as f:
                json.dump({"store": STORE, "sha": sha}, f)
        except:
            pass
        return sha
    # Fallback na /tmp
    try:
        if os.path.exists(BACKUP_PATH):
            with open(BACKUP_PATH, "r") as f:
                backup = json.load(f)
                STORE = backup.get("store", {})
                print(f"Data načtena z /tmp: {len(STORE)} uživatelů")
                return backup.get("sha")
    except Exception as e:
        print(f"Backup error: {e}")
    STORE = {}
    return None

# SHA posledního uloženého souboru na GitHubu
_github_sha = load_data()

def save_data():
    """Ulož data na GitHub a do /tmp."""
    global _github_sha
    new_sha = github_save_file(STORE, _github_sha)
    if new_sha:
        _github_sha = new_sha
        # Aktualizuj /tmp backup
        try:
            with open(BACKUP_PATH, "w") as f:
                json.dump({"store": STORE, "sha": _github_sha}, f)
        except:
            pass
        return True
    else:
        # GitHub selhal - ulož aspoň do /tmp
        try:
            with open(BACKUP_PATH, "w") as f:
                json.dump({"store": STORE, "sha": _github_sha}, f)
        except:
            pass
        return False

def empty_user():
    return {
        "profile": {},
        "entries": {},
        "history": {},
        "receptar": {},
        "aktivity": {},
        "weight_log": {},
    }

# ── Merge helpers ─────────────────────────────────────────────────────────────

def merge_entries(server: dict, incoming: list) -> dict:
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
    if not server:
        return incoming
    if not incoming:
        return server
    server_ts = server.get("_profileTs") or 0
    incoming_ts = incoming.get("_profileTs") or 0
    base = incoming if incoming_ts >= server_ts else server
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
    if body.username and body.username.strip():
        uid = "user_" + body.username.lower().strip()
    else:
        uid = body.device_id

    if uid not in STORE:
        STORE[uid] = empty_user()

    user = STORE[uid]

    if body.profile:
        user["profile"] = merge_profile(user.get("profile", {}), body.profile)

    if body.entries:
        for date, incoming_list in body.entries.items():
            server_dict = user["entries"].get(date, {})
            user["entries"][date] = merge_entries(server_dict, incoming_list)

    if body.history:
        for date, items in body.history.items():
            if date not in user["history"]:
                user["history"][date] = items

    if body.receptar is not None:
        for recept in body.receptar:
            name = recept.get("jidlo", "")
            if name:
                user["receptar"][name] = recept

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

    # Ulož na GitHub
    save_data()

    return _user_response(user, uid)

@app.get("/data/{uid}")
def get_data(uid: str):
    if uid not in STORE:
        return {"profile": {}, "entries": {}, "history": {}, "receptar": [], "aktivity": [], "weight_log": []}
    return _user_response(STORE[uid], uid)

def _user_response(user: dict, uid: str) -> dict:
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
