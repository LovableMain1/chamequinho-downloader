#!/usr/bin/env python3
"""
Deezer Bot — v11 PRO
• Busca e download via Deezer (MP3 128 kbps)
• Cards com botões que atualizam in-place (sem novas mensagens)
• Cancelamento a qualquer momento durante download/envio
• Menu exibido automaticamente após conclusão
• 🆕 Explorar catálogo Deezer (charts, gêneros, editorial)
• 🆕 Álbuns com capas embutidas via ffmpeg
• 🆕 Arquivo de usuários em dzMusic/usuarios.json
• 🆕 Multi-usuário simultâneo otimizado
"""

import asyncio, json, logging, math, os, re, shutil, socket
import subprocess, tempfile, threading, time, zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from io import BytesIO
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import (
    ChunkedEncodingError, ConnectionError as ReqConnError,
    ConnectTimeout, ProxyError, ReadTimeout,
)
from urllib3.util.retry import Retry
from dotenv import load_dotenv

from telethon import TelegramClient, events, Button
from telethon.tl.types import DocumentAttributeAudio

from deezer import Deezer
from deemix import generateDownloadObject
from deemix.settings import load as loadSettings
from deemix.downloader import Downloader

from mutagen.id3 import ID3, TIT2, TPE1
from mutagen.mp3 import MP3

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
ENV_PATH = Path("/sdcard/dzMusic/.env")
load_dotenv(dotenv_path=ENV_PATH)

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

BASE_DIR = Path("/sdcard/dzMusic")
DOWNLOAD_DIR = BASE_DIR / "downloads"
ARL_FILE = BASE_DIR / "arl_user.txt"
USERS_FILE = BASE_DIR / "usuarios.json"

for d in (DOWNLOAD_DIR, BASE_DIR):
    d.mkdir(parents=True, exist_ok=True)

ITEMS_PER_PAGE = 8
DZ_BATCH = 50
MAX_REQ_MIN = 50
BLOCK_SECS = 60
SPAM_WINDOW = 2.0
SPAM_SOFT = 20
SPAM_HARD = 35
MAX_GLOBAL_DL = 4
MAX_SEND_PARA = 5
FFMPEG_BIN = shutil.which("ffmpeg") or "ffmpeg"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("dzbot")

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "Mozilla/5.0"
_executor = ThreadPoolExecutor(
    max_workers=MAX_GLOBAL_DL * 3,
    thread_name_prefix="dz"
)

# ═══════════════════════════════════════════════════════════════
# GERENCIADOR DE USUÁRIOS (arquivo JSON em dzMusic)
# ═══════════════════════════════════════════════════════════════
class UserTracker:
    """Salva informações de todos os usuários em usuarios.json"""

    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._users: dict[int, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for u in data.get("usuarios", []):
                    uid = u.get("id")
                    if uid:
                        self._users[uid] = u
            except Exception:
                pass

    def _save(self):
        data = {
            "total": len(self._users),
            "atualizado": datetime.utcnow().isoformat(timespec="seconds"),
            "usuarios": list(self._users.values())
        }
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def register(self, sender):
        """Registra ou atualiza um usuário a partir do objeto sender do Telegram"""
        uid = sender.id
        with self._lock:
            existing = self._users.get(uid, {})
            self._users[uid] = {
                "id": uid,
                "nome": getattr(sender, "first_name", "") or "",
                "sobrenome": getattr(sender, "last_name", "") or "",
                "username": getattr(sender, "username", "") or "",
                "primeiro_uso": existing.get("primeiro_uso",
                    datetime.utcnow().isoformat(timespec="seconds")),
                "ultimo_uso": datetime.utcnow().isoformat(timespec="seconds"),
                "total_buscas": existing.get("total_buscas", 0),
                "total_downloads": existing.get("total_downloads", 0),
            }
            try:
                self._save()
            except Exception as e:
                log.error(f"UserTracker save: {e}")

    def increment(self, uid: int, field: str):
        with self._lock:
            if uid in self._users:
                self._users[uid][field] = self._users[uid].get(field, 0) + 1
                try:
                    self._save()
                except Exception:
                    pass

    def get_all(self) -> list[dict]:
        return list(self._users.values())

    def count(self) -> int:
        return len(self._users)

    def get(self, uid: int) -> dict | None:
        return self._users.get(uid)


user_tracker = UserTracker(USERS_FILE)

# ═══════════════════════════════════════════════════════════════
# ERROS AMIGÁVEIS
# ═══════════════════════════════════════════════════════════════
_EXC_CONN = (
    ReqConnError, ReadTimeout, ConnectTimeout,
    ChunkedEncodingError, ProxyError,
    ConnectionResetError, ConnectionAbortedError,
    ConnectionRefusedError, BrokenPipeError,
    TimeoutError, socket.timeout, OSError,
)
_SIG_CONN = ("connection","reset by peer","broken pipe","timed out",
    "errno 104","errno 110","errno 111","remotedisconnected",
    "max retries exceeded","network is unreachable")
_SIG_ARL = ("unauthorized","403","invalid arl","not logged","token expired")
_SIG_CONT = ("not available","not found","no tracks","list index",
    "nonetype","geo blocked","track is not readable")

def friendly_error(e: Exception, ctx: str = "") -> str:
    raw = str(e).lower()
    if isinstance(e, _EXC_CONN) or any(s in raw for s in _SIG_CONN):
        cat, msg = "CONN", "📡 **Falha de conexão.**\n\nTente novamente."
    elif any(s in raw for s in _SIG_ARL):
        cat, msg = "ARL", "🔑 **Sessão Deezer expirada.**\n\nAtualize sua ARL."
    elif any(s in raw for s in _SIG_CONT):
        cat, msg = "CONTENT", "🚫 **Conteúdo indisponível.**"
    else:
        cat, msg = "UNK", "⚠️ **Algo deu errado.**\n\nTente novamente."
    log.error(f"[{cat}] {ctx} — {type(e).__name__}: {e}",
        exc_info=(cat == "UNK"))
    return msg

# ═══════════════════════════════════════════════════════════════
# UTILS
# ═══════════════════════════════════════════════════════════════
def _patch_dz(dz: Deezer) -> Deezer:
    a = HTTPAdapter(max_retries=Retry(
        total=5, backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"], raise_on_status=False,
    ))
    dz.session.mount("http://", a)
    dz.session.mount("https://", a)
    _o = dz.session.request
    def _t(*a, **k):
        k.setdefault("timeout", (30, 90))
        return _o(*a, **k)
    dz.session.request = _t
    return dz

def safe(t: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', "_", t)

def fmt_dur(s) -> str:
    try:
        m, s2 = divmod(int(s), 60)
        h, m = divmod(m, 60)
        return f"{h}h{m:02d}m" if h else f"{m}m{s2:02d}s"
    except:
        return "—"

def fmt_num(n) -> str:
    try: return f"{int(n):,}".replace(",", ".")
    except: return str(n)

# ═══════════════════════════════════════════════════════════════
# USER ARL MANAGER
# ═══════════════════════════════════════════════════════════════
class UserARLManager:
    HEADER = "# Deezer Bot — ARLs\n# user_id|arl|name|country|plan|added_at\n"

    def __init__(self, path: Path):
        self.path = path
        self._lock = asyncio.Lock()
        self._c: dict[int, dict] = {}
        self._load()

    def _load(self):
        if not self.path.exists():
            self.path.write_text(self.HEADER, encoding="utf-8")
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"): continue
            p = line.split("|")
            if len(p) < 2: continue
            try:
                uid = int(p[0])
                self._c[uid] = {
                    "user_id": uid,
                    "arl": p[1],
                    "name": p[2] if len(p) > 2 else "",
                    "country": p[3] if len(p) > 3 else "",
                    "plan": p[4] if len(p) > 4 else "",
                    "added_at": p[5] if len(p) > 5 else "",
                }
            except: continue

    def _save(self):
        lines = [self.HEADER]
        for d in self._c.values():
            lines.append("|".join([
                str(d["user_id"]), d["arl"],
                d.get("name",""), d.get("country",""),
                d.get("plan",""), d.get("added_at",""),
            ]) + "\n")
        self.path.write_text("".join(lines), encoding="utf-8")

    def get(self, uid: int) -> dict | None:
        return self._c.get(uid)

    def count(self) -> int:
        return len(self._c)

    async def save(self, uid: int, arl: str,
        name="", country="", plan=""):
        async with self._lock:
            self._c[uid] = {
                "user_id": uid, "arl": arl.strip(),
                "name": name, "country": country, "plan": plan,
                "added_at": datetime.utcnow().isoformat(timespec="seconds"),
            }
            await asyncio.get_event_loop().run_in_executor(
                _executor, self._save)

    async def remove(self, uid: int) -> bool:
        async with self._lock:
            if uid not in self._c: return False
            del self._c[uid]
            await asyncio.get_event_loop().run_in_executor(
                _executor, self._save)
            return True

    @staticmethod
    def validate_arl(arl: str) -> dict | None:
        try:
            dz = Deezer()
            if not dz.login_via_arl(arl.strip()): return None
            info = {"name": "Usuário Deezer", "country": "—", "plan": "—"}
            try:
                r = dz.session.get(
                    "https://api.deezer.com/user/me", timeout=10)
                if r.ok:
                    d = r.json()
                    info["name"] = d.get("name", info["name"])
                    info["country"] = d.get("country", info["country"])
            except Exception: pass
            try:
                cu = getattr(dz, "current_user", {}) or {}
                info["name"] = cu.get("name", info["name"])
                info["country"] = cu.get("country", info["country"])
                info["plan"] = cu.get("offer_name", info["plan"])
            except Exception: pass
            _patch_dz(dz)
            return info
        except Exception as e:
            log.error(f"validate_arl: {e}")
            return None

    def open_session(self, uid: int) -> Deezer | None:
        d = self.get(uid)
        if not d: return None
        try:
            dz = Deezer()
            if dz.login_via_arl(d["arl"]):
                _patch_dz(dz)
                return dz
        except Exception: pass
        return None

user_arl = UserARLManager(ARL_FILE)

# ═══════════════════════════════════════════════════════════════
# ARL POOL
# ═══════════════════════════════════════════════════════════════
def _read_arls() -> list[str]:
    load_dotenv(dotenv_path=ENV_PATH, override=True)
    return [a.strip() for a in
        os.getenv("DEEZER_ARL", "").split(",") if a.strip()]

def _write_arls(arls: list[str]):
    text = ENV_PATH.read_text(encoding="utf-8")
    lines = []; updated = False
    for line in text.splitlines():
        if line.startswith("DEEZER_ARL="):
            lines.append(f"DEEZER_ARL={','.join(arls)}")
            updated = True
        else:
            lines.append(line)
    if not updated:
        lines.append(f"DEEZER_ARL={','.join(arls)}")
    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

class ARLPool:
    def __init__(self):
        self._lock = threading.Lock()
        self._sessions: list[dict] = []
        for i, arl in enumerate(_read_arls(), 1):
            s = self._make(i, arl)
            if s: self._sessions.append(s)
        if not self._sessions:
            raise RuntimeError("Nenhuma ARL válida no .env")

    def _make(self, idx, arl) -> dict | None:
        dz = Deezer()
        ok = dz.login_via_arl(arl)
        log.info(f"{'✅' if ok else '❌'} ARL #{idx} [{arl[:18]}…]")
        if not ok: return None
        _patch_dz(dz)
        return {"idx": idx, "arl": arl, "dz": dz}

    def primary(self) -> dict: return self._sessions[0]
    def all(self) -> list[dict]: return list(self._sessions)
    def arls(self) -> list[str]: return [s["arl"] for s in self._sessions]
    def count(self) -> int: return len(self._sessions)

    def status(self) -> str:
        lines = [f"🟢 **Pool Deezer** — {self.count()} sessão(ões)"]
        for i, s in enumerate(self._sessions):
            tag = " _(primária)_" if i == 0 else ""
            lines.append(f"  `{s['arl'][:22]}…`{tag}")
        return "\n".join(lines)

    def add(self, arl: str) -> bool:
        nxt = max((s["idx"] for s in self._sessions), default=0) + 1
        s = self._make(nxt, arl)
        if s:
            with self._lock: self._sessions.append(s)
        return s is not None

    def remove(self, pos: int) -> str | None:
        with self._lock:
            if 0 <= pos < len(self._sessions):
                r = self._sessions.pop(pos)
                for i, s in enumerate(self._sessions, 1): s["idx"] = i
                return r["arl"]
        return None

    def refresh_all(self):
        with self._lock:
            for s in self._sessions:
                if s["dz"].login_via_arl(s["arl"]):
                    _patch_dz(s["dz"])

pool = ARLPool()

# ═══════════════════════════════════════════════════════════════
# RATE LIMITER + ANTI-SPAM
# ═══════════════════════════════════════════════════════════════
class RateLimiter:
    def __init__(self):
        self._ev: dict[int, deque] = {}
        self._bl: dict[int, float] = {}

    def check(self, uid: int) -> tuple[bool, int]:
        if uid == OWNER_ID: return True, 0
        now = time.time()
        if uid in self._bl:
            if now < self._bl[uid]: return False, int(self._bl[uid] - now)
            del self._bl[uid]
        q = self._ev.setdefault(uid, deque())
        cutoff = now - 60
        while q and q[0] < cutoff: q.popleft()
        if len(q) >= MAX_REQ_MIN:
            self._bl[uid] = now + BLOCK_SECS; return False, BLOCK_SECS
        q.append(now); return True, 0

    def unblock(self, uid: int):
        self._bl.pop(uid, None); self._ev.pop(uid, None)

    def unblock_all(self):
        self._bl.clear(); self._ev.clear()

    def blocked_list(self) -> list:
        now = time.time()
        return [(u, int(t - now)) for u, t in self._bl.items() if t > now]

class AntiSpam:
    def __init__(self):
        self._cl: dict[int, deque] = {}
        self._bl: dict[int, float] = {}

    def hit(self, uid: int) -> tuple[bool, str]:
        if uid == OWNER_ID: return True, ""
        now = time.time()
        if uid in self._bl:
            rem = self._bl[uid] - now
            if rem > 0: return False, f"🚦 Aguarde **{int(rem)}s**."
            del self._bl[uid]
        q = self._cl.setdefault(uid, deque())
        cutoff = now - SPAM_WINDOW
        while q and q[0] < cutoff: q.popleft()
        q.append(now); cnt = len(q)
        if cnt >= SPAM_HARD:
            self._bl[uid] = now + 90
            return False, "🚦 Muitas ações! Aguarde **90s**."
        if cnt >= SPAM_SOFT:
            self._bl[uid] = now + 30
            return False, "🚦 Devagar! Aguarde **30s**."
        return True, ""

    def clear(self, uid: int):
        self._bl.pop(uid, None); self._cl.pop(uid, None)

    def clear_all(self):
        self._bl.clear(); self._cl.clear()

rate = RateLimiter()
spam = AntiSpam()

# ═══════════════════════════════════════════════════════════════
# DEEZER PAGER
# ═══════════════════════════════════════════════════════════════
class DeezerPager:
    def __init__(self, title: str, url: str, params: dict,
        item_type: str, extra: dict | None = None):
        self.title = title
        self.url = url
        self.params = params
        self.item_type = item_type
        self.extra = extra or {}
        self._total: int | None = None
        self._cache: dict[int, dict] = {}

    @property
    def total(self) -> int: return self._total or 0

    @property
    def total_pages(self) -> int:
        return max(1, math.ceil(self._total / ITEMS_PER_PAGE)) \
            if self._total else 1

    def _fetch(self, offset: int, limit: int) -> dict:
        r = HTTP.get(self.url,
            params={**self.params, "index": offset, "limit": limit},
            timeout=15)
        r.raise_for_status()
        return r.json()

    async def _ensure(self, page: int):
        start = page * ITEMS_PER_PAGE
        end = start + ITEMS_PER_PAGE
        missing = [i for i in range(start, end) if i not in self._cache]
        if not missing: return
        batch_offs = set((i // DZ_BATCH) * DZ_BATCH for i in missing)
        loop = asyncio.get_event_loop()
        for off in sorted(batch_offs):
            data = await loop.run_in_executor(
                _executor, self._fetch, off, DZ_BATCH)
            if self._total is None:
                self._total = data.get("total", 0)
            for j, item in enumerate(data.get("data", [])):
                self._cache[off + j] = item

    async def get_page(self, page: int) -> list[dict]:
        await self._ensure(page)
        s = page * ITEMS_PER_PAGE
        e = min(s + ITEMS_PER_PAGE, self._total or s + ITEMS_PER_PAGE)
        return [self._cache[i] for i in range(s, e) if i in self._cache]

    def item_label(self, item: dict) -> str:
        t = self.item_type
        n = item.get("title") or item.get("name") or "?"
        if t == "track":
            a = (item.get("artist") or {}).get("name", "")
            return f"🎵 {n[:30]} — {a[:18]}" if a else f"🎵 {n[:46]}"
        if t == "album":
            a = (item.get("artist") or {}).get("name", "")
            y = str(item.get("release_date", ""))[:4]
            return f"💿 {n[:26]} ({y}) — {a[:14]}"
        if t == "artist": return f"👤 {n[:46]}"
        if t == "playlist":
            c = (item.get("creator") or {}).get("name", "")
            return f"📋 {n[:28]} — {c[:16]}"
        return n[:48]

    def item_cb(self, item: dict) -> bytes:
        short = {
            "track":"tr","album":"al",
            "artist":"ar","playlist":"pl"
        }[self.item_type]
        return f"sel:{short}:{item.get('id','0')}".encode()

# ═══════════════════════════════════════════════════════════════
# ESTADO DE NAVEGAÇÃO
# ═══════════════════════════════════════════════════════════════
class NavState:
    __slots__ = ("stack", "page", "query", "step", "pending",
        "card_msg", "card_caption", "card_btns")

    def __init__(self):
        self.stack: list[DeezerPager] = []
        self.page: int = 0
        self.query: str = ""
        self.step: str = "idle"
        self.pending: dict = {}
        self.card_msg = None
        self.card_caption: str = ""
        self.card_btns: list = []

    @property
    def pager(self) -> DeezerPager | None:
        return self.stack[-1] if self.stack else None

    def push(self, p): self.stack.append(p); self.page = 0

    def pop(self) -> bool:
        if len(self.stack) > 1:
            self.stack.pop(); self.page = 0; return True
        return False

    def clear(self):
        self.stack.clear(); self.page = 0
        self.step = "idle"
        self.pending = {}
        self.card_msg = None
        self.card_caption = ""
        self.card_btns = []

_nav: dict[int, NavState] = {}
_dl_locks: dict[int, asyncio.Lock] = {}
_dl_tasks: dict[int, asyncio.Task] = {}
_cancel_flags: dict[int, bool] = {}

def nav(uid: int) -> NavState:
    if uid not in _nav: _nav[uid] = NavState()
    return _nav[uid]

def dl_lock(uid: int) -> asyncio.Lock:
    if uid not in _dl_locks: _dl_locks[uid] = asyncio.Lock()
    return _dl_locks[uid]

# ═══════════════════════════════════════════════════════════════
# DEEZER API
# ═══════════════════════════════════════════════════════════════
DZ = "https://api.deezer.com"
DZ_URL_RE = re.compile(
    r"deezer\.com(?:/[a-z]{2})?/(track|album|playlist|artist)/(\d+)"
)

def resolve_short(url: str) -> str:
    if "link.deezer.com" in url:
        try: return HTTP.head(url, allow_redirects=True, timeout=15).url
        except Exception: pass
    return url

def detect_dz_url(text: str) -> tuple[str, str] | None:
    m = DZ_URL_RE.search(resolve_short(text.strip()))
    return (m.group(1), m.group(2)) if m else None

def _api(path: str, **p):
    r = HTTP.get(f"{DZ}/{path}", params=p, timeout=15)
    r.raise_for_status()
    return r.json()

def dl_dz_url(tipo, iid):
    return f"https://www.deezer.com/{tipo}/{iid}"

# ═══════════════════════════════════════════════════════════════
# EXPLORAR — API helpers
# ═══════════════════════════════════════════════════════════════
def _fetch_chart_tracks():
    return _api("chart/0/tracks", limit=50)

def _fetch_chart_albums():
    return _api("chart/0/albums", limit=50)

def _fetch_chart_artists():
    return _api("chart/0/artists", limit=50)

def _fetch_chart_playlists():
    return _api("chart/0/playlists", limit=50)

def _fetch_genres():
    return _api("genre")

def _fetch_genre_artists(genre_id):
    return _api(f"genre/{genre_id}/artists", limit=50)

def _fetch_editorial():
    return _api("editorial")

def _fetch_editorial_releases(editorial_id):
    return _api(f"editorial/{editorial_id}/releases", limit=50)

# ═══════════════════════════════════════════════════════════════
# CARDS
# ═══════════════════════════════════════════════════════════════
def card_track(t: dict) -> str:
    return (
        f"🎵 **{t.get('title','?')}**\n\n"
        f"👤 Artista : {t.get('artist',{}).get('name','—')}\n"
        f"💿 Álbum : {t.get('album',{}).get('title','—')}\n"
        f"⏱ Duração : {fmt_dur(t.get('duration',0))}\n"
        f"📅 Lançado : {str(t.get('release_date','—'))[:10]}\n"
        f"🎧 Formato : MP3 128 kbps"
    )

def card_album(a: dict) -> str:
    genres = ", ".join(
        g["name"] for g in a.get("genres", {}).get("data", [])
    ) or "—"
    yr = str(a.get("release_date", ""))[:4] or "—"
    return (
        f"💿 **{a.get('title','?')} ({yr})**\n\n"
        f"👤 Artista : {a.get('artist',{}).get('name','—')}\n"
        f"📅 Ano : {yr}\n"
        f"🎵 Faixas : {a.get('nb_tracks','?')}\n"
        f"🎼 Gênero : {genres}\n"
        f"⏱ Duração : {fmt_dur(a.get('duration',0))}\n"
        f"🎧 Formato : MP3 128 kbps"
    )

def card_playlist(p: dict) -> str:
    return (
        f"📋 **{p.get('title','?')}**\n\n"
        f"👤 Criador : {p.get('creator',{}).get('name','—')}\n"
        f"🎵 Faixas : {p.get('nb_tracks','?')}\n"
        f"⏱ Duração : {fmt_dur(p.get('duration',0))}\n"
        f"🎧 Formato : MP3 128 kbps"
    )

def card_artist(a: dict) -> str:
    return (
        f"👤 **{a.get('name','?')}**\n\n"
        f"💿 Álbuns : {a.get('nb_album','?')}\n"
        f"❤️ Fãs : {fmt_num(a.get('nb_fan',0))}\n"
        f"🌐 Link : [Deezer]({a.get('link','')})"
    )

# ═══════════════════════════════════════════════════════════════
# BOTÕES
# ═══════════════════════════════════════════════════════════════
def main_menu_btns(uid: int) -> list:
    rows = [
        [Button.inline("🔍 Buscar", b"hint_search"),
         Button.inline("🌍 Explorar", b"explore")],
        [Button.inline("🔑 Minha ARL Deezer", b"my_arl")],
    ]
    if uid == OWNER_ID:
        rows += [
            [Button.inline("⚙️ Pool Deezer", b"ow:panel")],
            [Button.inline("🔓 Remover Limitações", b"ow:unlimit"),
             Button.inline("👥 Usuários", b"ow:users")],
        ]
    return rows

def explore_btns() -> list:
    return [
        [Button.inline("🔥 Top Faixas", b"exp:top_tracks"),
         Button.inline("💿 Top Álbuns", b"exp:top_albums")],
        [Button.inline("👤 Top Artistas", b"exp:top_artists"),
         Button.inline("📋 Top Playlists", b"exp:top_playlists")],
        [Button.inline("🎼 Gêneros", b"exp:genres"),
         Button.inline("📰 Editorial", b"exp:editorial")],
        [Button.inline("🏠 Menu", b"mn")],
    ]

def search_type_btns() -> list:
    return [
        [Button.inline("🎵 Faixas", b"stype:tr"),
         Button.inline("💿 Álbuns", b"stype:al")],
        [Button.inline("📋 Playlists", b"stype:pl"),
         Button.inline("👤 Artistas", b"stype:ar")],
        [Button.inline("❌ Cancelar", b"mn")],
    ]

async def pager_btns(uid: int) -> list:
    st = nav(uid); pg = st.pager
    if not pg: return [[Button.inline("🏠 Menu", b"mn")]]
    items = await pg.get_page(st.page)
    total_p = pg.total_pages
    rows = []
    for item in items:
        rows.append([Button.inline(pg.item_label(item)[:60], pg.item_cb(item))])
    nav_row = []
    if st.page > 0:
        nav_row.append(Button.inline("◀️", b"pg:prev"))
    lbl = f"📄 {st.page+1}/{total_p}"
    if pg.total: lbl += f" ({pg.total})"
    nav_row.append(Button.inline(lbl, b"noop"))
    if st.page+1 < total_p:
        nav_row.append(Button.inline("▶️", b"pg:next"))
    rows.append(nav_row)
    ctx = []
    if len(st.stack) > 1: ctx.append(Button.inline("◀️ Voltar", b"back"))
    ctx.append(Button.inline("🏠 Menu", b"mn"))
    rows.append(ctx)
    return rows

def dl_mode_btns(uid: int, has_multi: bool) -> list:
    rows = []
    if has_multi:
        rows += [
            [Button.inline("🎵 Arquivos individuais",
                f"dlm:f:{uid}".encode())],
            [Button.inline("🗜️ ZIP compactado",
                f"dlm:z:{uid}".encode())],
        ]
    else:
        rows.append([Button.inline("⬇️ Baixar",
            f"dlm:f:{uid}".encode())])
    rows.append([Button.inline("◀️ Voltar", b"dl:back"),
        Button.inline("🏠 Menu", b"mn")])
    return rows

def cancel_btn(uid: int) -> list:
    return [[Button.inline("❌ Cancelar envio",
        f"dl:cancel:{uid}".encode())]]

def album_btns(aid: str) -> list:
    return [
        [Button.inline("⬇️ Baixar álbum", f"dl:al:{aid}".encode())],
        [Button.inline("🎵 Ver faixas", f"al:tracks:{aid}".encode())],
        [Button.inline("◀️ Voltar", b"back"),
         Button.inline("🏠 Menu", b"mn")],
    ]

def track_btns(tid: str) -> list:
    return [
        [Button.inline("⬇️ Baixar faixa", f"dl:tr:{tid}".encode())],
        [Button.inline("◀️ Voltar", b"back"),
         Button.inline("🏠 Menu", b"mn")],
    ]

def playlist_btns(plid: str) -> list:
    return [
        [Button.inline("⬇️ Baixar playlist", f"dl:pl:{plid}".encode())],
        [Button.inline("🎵 Ver faixas", f"pl:tracks:{plid}".encode())],
        [Button.inline("◀️ Voltar", b"back"),
         Button.inline("🏠 Menu", b"mn")],
    ]

def artist_btns(aid: str) -> list:
    return [
        [Button.inline("💿 Ver álbuns", f"ar:al:{aid}".encode())],
        [Button.inline("🏆 Top faixas", f"ar:top:{aid}".encode())],
        [Button.inline("◀️ Voltar", b"back"),
         Button.inline("🏠 Menu", b"mn")],
    ]

def owner_panel_btns() -> list:
    return [
        [Button.inline("➕ Adicionar ARL", b"ow:add")],
        [Button.inline("🗑 Remover ARL", b"ow:listrm")],
        [Button.inline("🔄 Renovar sessões", b"ow:refresh")],
        [Button.inline("🔓 Remover limitações", b"ow:unlimit")],
        [Button.inline("📊 Estatísticas", b"ow:stats")],
        [Button.inline("👥 Usuários", b"ow:users")],
        [Button.inline("🏠 Menu", b"mn")],
    ]

# ═══════════════════════════════════════════════════════════════
# TELEGRAM CLIENT
# ═══════════════════════════════════════════════════════════════
bot = TelegramClient("dz_bot_v11", API_ID, API_HASH)

async def _gate(event, is_cb: bool = True) -> bool:
    ok, msg = spam.hit(event.sender_id)
    if not ok:
        if is_cb: await event.answer(msg[:200], alert=True)
        else: await event.respond(msg, parse_mode="md")
        return False
    return True

async def _fetch_cover(url: str | None) -> bytes | None:
    if not url: return None
    try:
        r = await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: HTTP.get(url, timeout=10))
        return r.content if r.ok else None
    except Exception: return None

def _thumb(cover: bytes | None) -> BytesIO | None:
    if not cover: return None
    b = BytesIO(cover); b.name = "cover.jpg"; return b

async def _send_card(chat_id, cover: bytes | None,
    caption: str, btns: list):
    kw = {"caption": caption, "parse_mode": "md",
        "buttons": btns or None}
    if cover:
        buf = BytesIO(cover); buf.name = "c.jpg"
        return await bot.send_file(chat_id, buf, **kw)
    return await bot.send_message(
        chat_id, caption, buttons=btns or None, parse_mode="md")

async def send_menu(uid: int, event=None):
    nav(uid).clear()
    arl_d = user_arl.get(uid)
    arl_tag = (f"🔑 ARL: ✅ _{arl_d.get('name','Configurada')}_\n"
        if arl_d else "🔑 ARL: ❌ Não configurada\n")
    text = (
        f"🎵 **Deezer Bot — v11 PRO**\n\n"
        f"{arl_tag}\n"
        f"Digite o nome de uma música, álbum ou artista\n"
        f"ou cole um link do Deezer.\n\n"
        f"🌍 Use **Explorar** para navegar no catálogo!"
    )
    if event:
        try: await event.delete()
        except Exception: pass
    await bot.send_message(
        uid, text, buttons=main_menu_btns(uid), parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Básicos
# ═══════════════════════════════════════════════════════════════
@bot.on(events.NewMessage(pattern="/start"))
async def h_start(event):
    # Registra usuário
    try:
        sender = await event.get_sender()
        user_tracker.register(sender)
    except Exception:
        pass
    await send_menu(event.sender_id)

@bot.on(events.CallbackQuery(data=b"mn"))
async def h_mn(event):
    await event.answer()
    await send_menu(event.sender_id, event)

@bot.on(events.CallbackQuery(data=b"noop"))
async def h_noop(event):
    await event.answer()

@bot.on(events.CallbackQuery(data=b"hint_search"))
async def h_hint(event):
    await event.answer("Digite o nome ou cole um link 🎵")

@bot.on(events.CallbackQuery(data=b"back"))
async def h_back(event):
    await event.answer()
    uid = event.sender_id; st = nav(uid)
    if st.pop():
        btns = await pager_btns(uid)
        pg = st.pager
        try: await event.edit(pg.title, buttons=btns, parse_mode="md")
        except: await bot.send_message(
            uid, pg.title, buttons=btns, parse_mode="md")
    else:
        await send_menu(uid, event)

# ═══════════════════════════════════════════════════════════════
# HANDLER — Voltar da tela de modo (dentro do card)
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(data=b"dl:back"))
async def h_dl_back(event):
    await event.answer()
    uid = event.sender_id; st = nav(uid)
    if st.card_caption and st.card_btns:
        try:
            await event.edit(
                st.card_caption,
                buttons=st.card_btns,
                parse_mode="md"
            )
        except Exception:
            await send_menu(uid, event)
    else:
        await send_menu(uid, event)

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Paginação
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(pattern=rb"pg:(prev|next)"))
async def h_page(event):
    if not await _gate(event): return
    await event.answer()
    uid = event.sender_id; st = nav(uid)
    if not st.pager: return
    d = event.pattern_match.group(1)
    if d == b"next" and st.page+1 < st.pager.total_pages: st.page += 1
    elif d == b"prev" and st.page > 0: st.page -= 1
    btns = await pager_btns(uid)
    try: await event.edit(st.pager.title, buttons=btns, parse_mode="md")
    except: pass

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Explorar Catálogo Deezer
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(data=b"explore"))
async def h_explore(event):
    await event.answer()
    try:
        await event.edit(
            "🌍 **Explorar Catálogo Deezer**\n\n"
            "Navegue pelos mais populares, gêneros e lançamentos!",
            buttons=explore_btns(), parse_mode="md")
    except:
        await bot.send_message(
            event.sender_id,
            "🌍 **Explorar Catálogo Deezer**\n\n"
            "Navegue pelos mais populares, gêneros e lançamentos!",
            buttons=explore_btns(), parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"exp:(top_tracks|top_albums|top_artists|top_playlists)"))
async def h_exp_charts(event):
    if not await _gate(event): return
    await event.answer("⏳")
    uid = event.sender_id
    chart_type = event.pattern_match.group(1).decode()

    pager_map = {
        "top_tracks": ("🔥 **Top Faixas**", f"{DZ}/chart/0/tracks", "track"),
        "top_albums": ("💿 **Top Álbuns**", f"{DZ}/chart/0/albums", "album"),
        "top_artists": ("👤 **Top Artistas**", f"{DZ}/chart/0/artists", "artist"),
        "top_playlists": ("📋 **Top Playlists**", f"{DZ}/chart/0/playlists", "playlist"),
    }

    title, url, item_type = pager_map[chart_type]
    pg = DeezerPager(title, url, {}, item_type)

    try:
        await pg.get_page(0)
    except Exception as e:
        return await event.edit(
            friendly_error(e, f"chart {chart_type}"),
            buttons=[[Button.inline("🌍 Explorar", b"explore"),
                      Button.inline("🏠 Menu", b"mn")]],
            parse_mode="md")

    st = nav(uid)
    st.stack.clear()
    st.push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(data=b"exp:genres"))
async def h_exp_genres(event):
    if not await _gate(event): return
    await event.answer("⏳")

    try:
        data = await asyncio.get_event_loop().run_in_executor(
            _executor, _fetch_genres)
        genres = data.get("data", [])
    except Exception as e:
        return await event.edit(
            friendly_error(e, "genres"),
            buttons=[[Button.inline("🌍 Explorar", b"explore")]],
            parse_mode="md")

    rows = []
    for i in range(0, len(genres), 2):
        row = []
        for g in genres[i:i+2]:
            name = g.get("name", "?")[:20]
            gid = g.get("id", 0)
            if gid == 0: continue  # skip "All"
            row.append(Button.inline(f"🎼 {name}", f"genre:{gid}:{name}".encode()))
        if row:
            rows.append(row)
    rows.append([Button.inline("🌍 Explorar", b"explore"),
                 Button.inline("🏠 Menu", b"mn")])

    await event.edit("🎼 **Gêneros Musicais**\n\nEscolha um gênero:",
        buttons=rows, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"genre:(\d+):(.+)"))
async def h_genre(event):
    if not await _gate(event): return
    await event.answer("⏳")
    uid = event.sender_id
    gid = event.pattern_match.group(1).decode()
    gname = event.pattern_match.group(2).decode()

    pg = DeezerPager(
        f"🎼 **{gname}** — Artistas",
        f"{DZ}/genre/{gid}/artists", {}, "artist")

    try:
        await pg.get_page(0)
    except Exception as e:
        return await event.edit(
            friendly_error(e, f"genre {gid}"),
            buttons=[[Button.inline("🎼 Gêneros", b"exp:genres")]],
            parse_mode="md")

    st = nav(uid)
    st.stack.clear()
    st.push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(data=b"exp:editorial"))
async def h_exp_editorial(event):
    if not await _gate(event): return
    await event.answer("⏳")

    try:
        data = await asyncio.get_event_loop().run_in_executor(
            _executor, _fetch_editorial)
        items = data.get("data", [])
    except Exception as e:
        return await event.edit(
            friendly_error(e, "editorial"),
            buttons=[[Button.inline("🌍 Explorar", b"explore")]],
            parse_mode="md")

    rows = []
    for ed in items[:12]:
        name = ed.get("name", "?")[:30]
        eid = ed.get("id", 0)
        rows.append([Button.inline(f"📰 {name}", f"edrel:{eid}:{name}".encode())])
    rows.append([Button.inline("🌍 Explorar", b"explore"),
                 Button.inline("🏠 Menu", b"mn")])

    await event.edit("📰 **Editorial Deezer**\n\nEscolha uma seleção:",
        buttons=rows, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"edrel:(\d+):(.+)"))
async def h_editorial_releases(event):
    if not await _gate(event): return
    await event.answer("⏳")
    uid = event.sender_id
    eid = event.pattern_match.group(1).decode()
    ename = event.pattern_match.group(2).decode()

    pg = DeezerPager(
        f"📰 **{ename}** — Lançamentos",
        f"{DZ}/editorial/{eid}/releases", {}, "album")

    try:
        await pg.get_page(0)
    except Exception as e:
        return await event.edit(
            friendly_error(e, f"editorial {eid}"),
            buttons=[[Button.inline("📰 Editorial", b"exp:editorial")]],
            parse_mode="md")

    st = nav(uid)
    st.stack.clear()
    st.push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Tipo de busca
# ═══════════════════════════════════════════════════════════════
def _pager_search(query: str, tipo: str) -> DeezerPager:
    paths = {
        "tr": ("search", "track", "🎵"),
        "al": ("search/album", "album", "💿"),
        "pl": ("search/playlist", "playlist", "📋"),
        "ar": ("search/artist", "artist", "👤"),
    }
    path, item_type, ico = paths[tipo]
    return DeezerPager(
        f"{ico} Resultados: **{query}**",
        f"{DZ}/{path}", {"q": query}, item_type,
    )

@bot.on(events.CallbackQuery(pattern=rb"stype:(tr|al|pl|ar)"))
async def h_stype(event):
    if not await _gate(event): return
    await event.answer()
    uid = event.sender_id; tipo = event.pattern_match.group(1).decode()
    st = nav(uid)
    if not st.query:
        return await event.edit(
            "❌ Sessão expirada.",
            buttons=[[Button.inline("🏠 Menu", b"mn")]])
    await event.edit(f"🔍 Buscando **{st.query}**…", parse_mode="md")

    # Conta busca do usuário
    user_tracker.increment(uid, "total_buscas")

    pg = _pager_search(st.query, tipo)
    try:
        await pg.get_page(0)
    except Exception as e:
        return await event.edit(
            friendly_error(e, f"search {tipo}"),
            buttons=[[Button.inline("🏠 Menu", b"mn")]], parse_mode="md")
    if pg.total == 0:
        return await event.edit(
            f"😔 Sem resultados para **{st.query}**.",
            buttons=[[Button.inline("🔄 Mudar tipo", b"search_again")],
                     [Button.inline("🏠 Menu", b"mn")]],
            parse_mode="md")
    st.stack.clear(); st.push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(data=b"search_again"))
async def h_search_again(event):
    await event.answer(); uid = event.sender_id; st = nav(uid)
    if not st.query:
        return await event.edit(
            "❌ Sessão expirada.",
            buttons=[[Button.inline("🏠 Menu", b"mn")]])
    await event.edit(
        f"🔍 Buscar: **{st.query}**\n\nEscolha o tipo:",
        buttons=search_type_btns(), parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# HANDLER — Seleção item do pager
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(pattern=rb"sel:(tr|al|ar|pl):(\d+)"))
async def h_sel(event):
    if not await _gate(event): return
    await event.answer()
    uid = event.sender_id
    tipo = event.pattern_match.group(1).decode()
    iid = event.pattern_match.group(2).decode()
    st = nav(uid)

    try: await event.delete()
    except Exception: pass

    msg = await bot.send_message(uid, "⏳ Carregando…")
    loop = asyncio.get_event_loop()

    async def _finish_card(caption: str, btns: list, cover: bytes | None):
        await msg.delete()
        card = await _send_card(uid, cover, caption, btns)
        st.card_msg = card
        st.card_caption = caption
        st.card_btns = btns

    try:
        if tipo == "tr":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"track/{iid}"))
            cover = await _fetch_cover(
                (info.get("album") or {}).get("cover_xl"))
            st.pending = {
                "type": "track", "name": info.get("title", "Faixa"),
                "dz_url": dl_dz_url("track", iid),
                "cover_url": (info.get("album") or {}).get("cover_xl"),
                "artist": info.get("artist", {}).get("name", ""),
            }
            await _finish_card(card_track(info), track_btns(iid), cover)

        elif tipo == "al":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"album/{iid}"))
            cover = await _fetch_cover(info.get("cover_xl"))
            st.pending = {
                "type": "album", "name": info.get("title", "Álbum"),
                "dz_url": dl_dz_url("album", iid),
                "cover_url": info.get("cover_xl"),
                "artist": info.get("artist", {}).get("name", ""),
            }
            await _finish_card(card_album(info), album_btns(iid), cover)

        elif tipo == "ar":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"artist/{iid}"))
            cover = await _fetch_cover(info.get("picture_xl"))
            await _finish_card(card_artist(info), artist_btns(iid), cover)

        elif tipo == "pl":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"playlist/{iid}"))
            cover = await _fetch_cover(info.get("picture_xl"))
            st.pending = {
                "type": "playlist", "name": info.get("title", "Playlist"),
                "dz_url": dl_dz_url("playlist", iid),
                "cover_url": info.get("picture_xl"),
                "artist": "",
            }
            await _finish_card(card_playlist(info), playlist_btns(iid), cover)

    except Exception as e:
        await msg.edit(
            friendly_error(e, f"sel {tipo}:{iid}"),
            buttons=[[Button.inline("🏠 Menu", b"mn")]], parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# HANDLER — Botão ⬇️ Baixar no card
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(pattern=rb"dl:(tr|al|pl):(\d+)"))
async def h_dl_card(event):
    if not await _gate(event): return
    uid = event.sender_id; st = nav(uid)
    if not st.pending:
        return await event.answer(
            "❌ Pedido expirado. Selecione o item novamente.", alert=True)
    await event.answer()
    p = st.pending
    ico = "💿" if p["type"] != "track" else "🎵"
    await event.edit(
        f"📦 **Como deseja receber?**\n\n{ico} _{p['name']}_",
        buttons=dl_mode_btns(uid, p["type"] != "track"),
        parse_mode="md",
    )

# ═══════════════════════════════════════════════════════════════
# HANDLER — Modo escolhido → inicia task de download
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(pattern=rb"dlm:(f|z):(\d+)"))
async def h_dlm(event):
    if not await _gate(event): return
    modo = event.pattern_match.group(1).decode()
    uid = int(event.pattern_match.group(2))
    if event.sender_id != uid:
        return await event.answer("❌ Não é seu menu!", alert=True)
    st = nav(uid)
    if not st.pending:
        return await event.answer("❌ Pedido expirado.", alert=True)
    if uid in _dl_tasks:
        return await event.answer("⏳ Já tem um download ativo!", alert=True)
    await event.answer()
    _cancel_flags[uid] = False

    # Conta download do usuário
    user_tracker.increment(uid, "total_downloads")

    card = st.card_msg or event
    task = asyncio.create_task(
        _dl_task_dz(uid, modo, dict(st.pending), card))
    _dl_tasks[uid] = task

# ═══════════════════════════════════════════════════════════════
# HANDLER — Cancelar download
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(pattern=rb"dl:cancel:(\d+)"))
async def h_dl_cancel(event):
    uid = int(event.pattern_match.group(1))
    if event.sender_id != uid:
        return await event.answer("❌ Não é seu menu!", alert=True)
    _cancel_flags[uid] = True
    t = _dl_tasks.get(uid)
    if t and not t.done(): t.cancel()
    await event.answer("❌ Cancelando…")

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Sub-pagers (faixas de álbum, playlist, artista)
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(pattern=rb"al:tracks:(\d+)"))
async def h_al_tracks(event):
    if not await _gate(event): return
    await event.answer("⏳")
    uid = event.sender_id; aid = event.pattern_match.group(1).decode()
    try:
        info = await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: _api(f"album/{aid}"))
    except Exception as e:
        return await event.edit(friendly_error(e, f"album {aid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    pg = _pager_album_tracks(aid, info.get("title", "Álbum"))
    try: await pg.get_page(0)
    except Exception as e:
        return await event.edit(friendly_error(e, f"al:tracks {aid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    nav(uid).push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"pl:tracks:(\d+)"))
async def h_pl_tracks(event):
    if not await _gate(event): return
    await event.answer("⏳")
    uid = event.sender_id; plid = event.pattern_match.group(1).decode()
    try:
        info = await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: _api(f"playlist/{plid}"))
    except Exception as e:
        return await event.edit(friendly_error(e, f"playlist {plid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    pg = _pager_pl_tracks(plid, info.get("title", "Playlist"))
    try: await pg.get_page(0)
    except Exception as e:
        return await event.edit(friendly_error(e, f"pl:tracks {plid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    nav(uid).push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"ar:al:(\d+)"))
async def h_ar_albums(event):
    if not await _gate(event): return
    await event.answer("⏳")
    uid = event.sender_id; aid = event.pattern_match.group(1).decode()
    try:
        info = await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: _api(f"artist/{aid}"))
    except Exception as e:
        return await event.edit(friendly_error(e, f"artist {aid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    pg = _pager_artist_albums(aid, info.get("name", "Artista"))
    try: await pg.get_page(0)
    except Exception as e:
        return await event.edit(friendly_error(e, f"ar:al {aid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    nav(uid).push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"ar:top:(\d+)"))
async def h_ar_top(event):
    if not await _gate(event): return
    await event.answer("⏳")
    uid = event.sender_id; aid = event.pattern_match.group(1).decode()
    try:
        info = await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: _api(f"artist/{aid}"))
    except Exception as e:
        return await event.edit(friendly_error(e, f"artist {aid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    pg = _pager_artist_top(aid, info.get("name", "Artista"))
    try: await pg.get_page(0)
    except Exception as e:
        return await event.edit(friendly_error(e, f"ar:top {aid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")
    nav(uid).push(pg)
    btns = await pager_btns(uid)
    try: await event.edit(pg.title, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

def _pager_artist_albums(aid, name):
    return DeezerPager(f"💿 Álbuns: **{name}**",
        f"{DZ}/artist/{aid}/albums", {}, "album")

def _pager_artist_top(aid, name):
    return DeezerPager(f"🏆 Top: **{name}**",
        f"{DZ}/artist/{aid}/top", {}, "track")

def _pager_album_tracks(aid, title):
    return DeezerPager(f"🎵 Faixas: **{title}**",
        f"{DZ}/album/{aid}/tracks", {}, "track")

def _pager_pl_tracks(plid, title):
    return DeezerPager(f"📋 Faixas: **{title}**",
        f"{DZ}/playlist/{plid}/tracks", {}, "track")

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Admin Deezer
# ═══════════════════════════════════════════════════════════════
def _owner(fn):
    async def w(event):
        if event.sender_id != OWNER_ID:
            return await event.answer("⛔ Acesso restrito.", alert=True)
        await fn(event)
    w.__name__ = fn.__name__; return w

@bot.on(events.CallbackQuery(data=b"ow:panel"))
@_owner
async def h_ow_panel(event):
    await event.answer()
    await event.edit(
        f"⚙️ **Pool Deezer**\n\n{pool.status()}\n\n"
        f"👥 ARLs pessoais: {user_arl.count()}\n"
        f"📊 Usuários registrados: {user_tracker.count()}",
        buttons=owner_panel_btns(), parse_mode="md")

@bot.on(events.CallbackQuery(data=b"ow:add"))
@_owner
async def h_ow_add(event):
    await event.answer()
    nav(event.sender_id).step = "wait_arl_add"
    await event.edit("➕ Envie o token ARL para o pool.",
        buttons=[[Button.inline("❌ Cancelar", b"ow:panel")]])

@bot.on(events.CallbackQuery(data=b"ow:listrm"))
@_owner
async def h_ow_listrm(event):
    await event.answer()
    if pool.count() == 1:
        return await event.edit(
            "⚠️ Mínimo 1 ARL ativa.",
            buttons=[[Button.inline("◀️", b"ow:panel")]])
    rows = []
    for pos, s in enumerate(pool.all()):
        tag = " _(primária)_" if pos == 0 else ""
        rows.append([
            Button.inline(f"{s['arl'][:24]}…{tag}", b"noop"),
            Button.inline("🗑", f"ow:rm:{pos}".encode()),
        ])
    rows.append([Button.inline("◀️ Voltar", b"ow:panel")])
    await event.edit("🗑 Remover ARL:", buttons=rows, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"ow:rm:(\d+)"))
@_owner
async def h_ow_rm(event):
    pos = int(event.pattern_match.group(1))
    if pool.count() <= 1:
        return await event.answer("⚠️ Mínimo 1 ARL!", alert=True)
    if pool.remove(pos):
        _write_arls(pool.arls())
        await event.answer("✅ Removida!")
        await h_ow_listrm(event)
    else:
        await event.answer("❌ Não encontrada.", alert=True)

@bot.on(events.CallbackQuery(data=b"ow:refresh"))
@_owner
async def h_ow_refresh(event):
    await event.answer()
    await event.edit("🔄 Renovando sessões Deezer…")
    await asyncio.get_event_loop().run_in_executor(
        _executor, pool.refresh_all)
    await event.edit(f"✅ Renovadas!\n\n{pool.status()}",
        buttons=owner_panel_btns(), parse_mode="md")

@bot.on(events.CallbackQuery(data=b"ow:stats"))
@_owner
async def h_ow_stats(event):
    await event.answer()
    await event.edit(
        f"📊 **Estatísticas**\n\n"
        f"🟢 Pool Deezer : {pool.count()}\n"
        f"🟢 ARLs pessoais: {user_arl.count()}\n"
        f"👥 Usuários : {user_tracker.count()}\n"
        f"⬇️ Downloads : {len(_dl_tasks)}\n"
        f"🚫 Bloqueados : {len(rate.blocked_list())}\n"
        f"⚙️ Workers : DL={MAX_GLOBAL_DL} / UP={MAX_SEND_PARA}",
        buttons=owner_panel_btns(), parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# HANDLER — Listar Usuários (Owner)
# ═══════════════════════════════════════════════════════════════
_users_page: dict[int, int] = {}

@bot.on(events.CallbackQuery(data=b"ow:users"))
@_owner
async def h_ow_users(event):
    await event.answer()
    _users_page[event.sender_id] = 0
    await _show_users_page(event, 0)

@bot.on(events.CallbackQuery(pattern=rb"ow:upage:(\d+)"))
@_owner
async def h_ow_users_page(event):
    await event.answer()
    page = int(event.pattern_match.group(1))
    await _show_users_page(event, page)

async def _show_users_page(event, page: int):
    users = user_tracker.get_all()
    total = len(users)
    per_page = 8
    pages = max(1, math.ceil(total / per_page))
    page = max(0, min(page, pages - 1))
    start = page * per_page
    chunk = users[start:start + per_page]

    if not chunk:
        return await event.edit(
            "👥 **Usuários**\n\n⚠️ Nenhum usuário registrado.",
            buttons=[[Button.inline("◀️ Painel", b"ow:panel")]],
            parse_mode="md")

    lines = [f"👥 **Usuários Registrados** ({total})\n{'━' * 30}\n"]
    for u in chunk:
        nome = u.get("nome", "—")
        username = f"@{u['username']}" if u.get("username") else "—"
        buscas = u.get("total_buscas", 0)
        dls = u.get("total_downloads", 0)
        lines.append(
            f"👤 **{nome}** | {username}\n"
            f"   🆔 `{u['id']}` | 🔍 {buscas} | ⬇️ {dls}\n"
        )
    lines.append(f"{'━' * 30}\nPágina {page + 1}/{pages}")

    nav_btns = []
    if page > 0:
        nav_btns.append(Button.inline("◀️", f"ow:upage:{page-1}".encode()))
    nav_btns.append(Button.inline(f"{page+1}/{pages}", b"noop"))
    if page + 1 < pages:
        nav_btns.append(Button.inline("▶️", f"ow:upage:{page+1}".encode()))

    btns = [nav_btns, [Button.inline("◀️ Painel", b"ow:panel"),
                        Button.inline("🏠 Menu", b"mn")]]

    await event.edit("\n".join(lines), buttons=btns, parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Limitações
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(data=b"ow:unlimit"))
@_owner
async def h_ow_unlimit(event):
    await event.answer()
    blocked = rate.blocked_list()
    if not blocked:
        return await event.edit(
            "✅ Nenhum usuário limitado.",
            buttons=[[Button.inline("🔓 Limpar tudo", b"ow:unlimit_all")],
                     [Button.inline("◀️ Voltar", b"ow:panel")]])
    rows = []; text = f"🔓 **{len(blocked)} usuário(s):**\n\n"
    for uid_, rem in blocked:
        text += f"• `{uid_}` — {rem}s\n"
        rows.append([Button.inline(f"🔓 {uid_}",
            f"ow:unban:{uid_}".encode())])
    rows += [[Button.inline("🔓 Liberar TODOS", b"ow:unlimit_all")],
             [Button.inline("◀️ Voltar", b"ow:panel")]]
    await event.edit(text, buttons=rows, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"ow:unban:(\d+)"))
@_owner
async def h_ow_unban(event):
    uid_ = int(event.pattern_match.group(1))
    rate.unblock(uid_); spam.clear(uid_)
    await event.answer(f"✅ {uid_} liberado!", alert=True)
    await h_ow_unlimit(event)

@bot.on(events.CallbackQuery(data=b"ow:unlimit_all"))
@_owner
async def h_ow_unlimit_all(event):
    rate.unblock_all(); spam.clear_all()
    await event.answer("✅ Todos liberados!", alert=True)
    await event.edit("✅ Todas as restrições removidas.",
        buttons=[[Button.inline("◀️ Voltar", b"ow:panel")]])

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Minha ARL
# ═══════════════════════════════════════════════════════════════
@bot.on(events.CallbackQuery(data=b"my_arl"))
async def h_my_arl(event):
    await event.answer(); uid = event.sender_id; d = user_arl.get(uid)
    if d:
        text = (f"🔑 **Sua ARL Deezer**\n\n"
            f"👤 {d.get('name','—')} | 🌍 {d.get('country','—')}\n"
            f"🎵 Plano : {d.get('plan','—')}\n"
            f"📅 Adicio.: {d.get('added_at','—')[:10]}")
        btns = [[Button.inline("🔄 Atualizar", b"arl:set")],
                [Button.inline("🗑 Remover", b"arl:del")],
                [Button.inline("🏠 Menu", b"mn")]]
    else:
        text = (
            "🔑 **Minha ARL Deezer**\n\n"
            "Nenhuma ARL configurada.\n\n"
            "**Como obter:**\n"
            "1. Acesse deezer.com e faça login\n"
            "2. Abra DevTools (F12)\n"
            "3. Application → Cookies → deezer.com\n"
            "4. Copie o valor do cookie `arl`"
        )
        btns = [[Button.inline("➕ Configurar minha ARL", b"arl:set")],
                [Button.inline("🏠 Menu", b"mn")]]
    try: await event.edit(text, buttons=btns, parse_mode="md")
    except: await bot.send_message(uid, text, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(data=b"arl:set"))
async def h_arl_set(event):
    await event.answer()
    nav(event.sender_id).step = "wait_arl"
    await event.edit("🔑 Envie seu token ARL Deezer.",
        buttons=[[Button.inline("❌ Cancelar", b"my_arl")]])

@bot.on(events.CallbackQuery(data=b"arl:del"))
async def h_arl_del(event):
    await event.answer()
    ok = await user_arl.remove(event.sender_id)
    await event.edit(
        "✅ ARL removida." if ok else "ℹ️ Nenhuma ARL configurada.",
        buttons=[[Button.inline("🏠 Menu", b"mn")]])

# ═══════════════════════════════════════════════════════════════
# HANDLER — Mensagens de texto / links
# ═══════════════════════════════════════════════════════════════
@bot.on(events.NewMessage())
async def h_text(event):
    if not event.text or event.text.startswith("/"): return
    uid = event.sender_id
    if not await _gate(event, is_cb=False): return
    text = event.text.strip()
    st = nav(uid)

    # Registra usuário em cada interação
    try:
        sender = await event.get_sender()
        user_tracker.register(sender)
    except Exception:
        pass

    # ARL pessoal
    if st.step == "wait_arl":
        msg = await event.respond("🔍 Verificando ARL…")
        info = await asyncio.get_event_loop().run_in_executor(
            _executor, UserARLManager.validate_arl, text)
        if info is None:
            return await msg.edit(
                "❌ **ARL inválida ou expirada.**",
                buttons=[[Button.inline("❌ Cancelar", b"my_arl")]],
                parse_mode="md")
        await user_arl.save(uid, text,
            name=info.get("name",""),
            country=info.get("country",""),
            plan=info.get("plan",""))
        st.step = "idle"
        return await msg.edit(
            f"✅ **ARL configurada!**\n\n"
            f"👤 {info.get('name','—')} | 🌍 {info.get('country','—')}\n"
            f"🎵 Plano: {info.get('plan','—')}",
            buttons=[[Button.inline("🏠 Menu", b"mn")]],
            parse_mode="md")

    # ARL admin pool
    if st.step == "wait_arl_add" and uid == OWNER_ID:
        msg = await event.respond("🔍 Validando ARL…")
        if len(text) < 100 or not re.match(r"^[a-f0-9]+$", text):
            return await msg.edit(
                "❌ Token inválido.",
                buttons=[[Button.inline("◀️", b"ow:panel")]])
        if text in pool.arls():
            return await msg.edit(
                "⚠️ ARL já existe.",
                buttons=[[Button.inline("◀️", b"ow:panel")]])
        ok = await asyncio.get_event_loop().run_in_executor(
            _executor, pool.add, text)
        if ok:
            _write_arls(pool.arls()); st.step = "idle"
            return await msg.edit(
                f"✅ ARL adicionada!\n\n{pool.status()}",
                buttons=owner_panel_btns(), parse_mode="md")
        return await msg.edit(
            "❌ ARL expirada.",
            buttons=[[Button.inline("◀️", b"ow:panel")]])

    # Rate limit
    ok, wait = rate.check(uid)
    if not ok:
        return await event.respond(
            f"⏳ Muitas buscas. Aguarde **{wait}s**.", parse_mode="md")

    # Link Deezer
    dz_detected = detect_dz_url(text)
    if dz_detected:
        tipo, iid = dz_detected
        msg = await event.respond("🟢 Link Deezer detectado…")
        asyncio.create_task(_handle_dz_link(msg, uid, tipo, iid))
        return

    # Busca por texto
    st.query = text
    await event.respond(
        f"🔍 Buscar: **{text}**\n\nEscolha o tipo:",
        buttons=search_type_btns(),
        parse_mode="md",
    )

async def _handle_dz_link(msg, uid: int, tipo: str, iid: str):
    loop = asyncio.get_event_loop(); st = nav(uid)

    async def _finish(caption, btns, cover):
        await msg.delete()
        card = await _send_card(uid, cover, caption, btns)
        st.card_msg = card
        st.card_caption = caption
        st.card_btns = btns

    try:
        if tipo == "track":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"track/{iid}"))
            cover = await _fetch_cover(
                (info.get("album") or {}).get("cover_xl"))
            st.pending = {
                "type": "track", "name": info.get("title","Faixa"),
                "dz_url": dl_dz_url("track", iid),
                "cover_url": (info.get("album") or {}).get("cover_xl"),
                "artist": info.get("artist",{}).get("name",""),
            }
            await _finish(card_track(info), track_btns(iid), cover)

        elif tipo == "album":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"album/{iid}"))
            cover = await _fetch_cover(info.get("cover_xl"))
            st.pending = {
                "type": "album", "name": info.get("title","Álbum"),
                "dz_url": dl_dz_url("album", iid),
                "cover_url": info.get("cover_xl"),
                "artist": info.get("artist",{}).get("name",""),
            }
            await _finish(card_album(info), album_btns(iid), cover)

        elif tipo == "playlist":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"playlist/{iid}"))
            cover = await _fetch_cover(info.get("picture_xl"))
            st.pending = {
                "type": "playlist", "name": info.get("title","Playlist"),
                "dz_url": dl_dz_url("playlist", iid),
                "cover_url": info.get("picture_xl"), "artist": "",
            }
            await _finish(card_playlist(info), playlist_btns(iid), cover)

        elif tipo == "artist":
            info = await loop.run_in_executor(
                _executor, lambda: _api(f"artist/{iid}"))
            cover = await _fetch_cover(info.get("picture_xl"))
            await _finish(card_artist(info), artist_btns(iid), cover)

    except Exception as e:
        await msg.edit(
            friendly_error(e, f"dz link {tipo}/{iid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# DOWNLOAD DEEZER — helpers
# ═══════════════════════════════════════════════════════════════
SETTINGS = loadSettings()
SETTINGS.update({
    "maxBitrate": "1",
    "downloadLocation": str(DOWNLOAD_DIR),
    "createArtistFolder": False, "createAlbumFolder": True,
    "createPlaylistFolder": True, "maxConcurrentDownloads": 1,
    "overwriteFile": "y",
})
for k, v in {
    "title":True,"artist":True,"album":True,"cover":True,
    "trackNumber":True,"discNumber":True,"albumArtist":True,
    "genre":True,"year":True,"length":True,"saveID3v1":True,
    "padTracks":True,"illegalCharacterReplacer":"_",
}.items():
    SETTINGS["tags"][k] = v

class _Tracker:
    def __init__(self): self.downloaded = []; self.failed = []
    def send(self, k, d=None):
        if isinstance(d, dict) and k == "updateQueue":
            (self.downloaded if d.get("downloaded") else
             self.failed if d.get("failed") else []).append(d)

def _run_dl(dz, obj, s, t):
    try: Downloader(dz, obj, s, t).start()
    except TypeError: Downloader(dz, obj, s).start()

def _dl_with_dz(url: str, dest: Path, dz: Deezer) -> _Tracker:
    s = dict(SETTINGS); s["downloadLocation"] = str(dest)
    t = _Tracker()
    obj = generateDownloadObject(dz, url, s["maxBitrate"])
    if obj is None: raise RuntimeError("generateDownloadObject retornou None")
    if isinstance(obj, list):
        if not obj: raise RuntimeError("Lista vazia")
        for o in obj: _run_dl(dz, o, s, t)
    else:
        _run_dl(dz, obj, s, t)
    time.sleep(1); return t

def _choose_dz(uid: int) -> list[Deezer]:
    sessions = []
    p = user_arl.open_session(uid)
    if p: sessions.append(p)
    sessions.extend(s["dz"] for s in pool.all())
    return sessions

def _sync_dz_download(url: str, dest: Path, uid: int) -> _Tracker:
    last_err = None
    for dz in _choose_dz(uid):
        for attempt in range(1, 4):
            try:
                t = _dl_with_dz(url, dest, dz)
                if list(dest.rglob("*.mp3")): return t
                raise RuntimeError("Nenhum MP3 gerado")
            except Exception as e:
                last_err = e
                if any(k in str(e).lower()
                    for k in ("unauthorized","403","invalid arl")): break
                time.sleep(4 * attempt)
    raise last_err or RuntimeError("Todas as ARLs falharam")

def _mp3_sort_key(mp3: Path):
    try:
        tags = ID3(str(mp3))
        t = str(tags.get("TRCK","0")).split("/")[0].strip()
        d = str(tags.get("TPOS","1")).split("/")[0].strip()
        return (int(d) if d.isdigit() else 1, int(t) if t.isdigit() else 0)
    except: return (999, 999)

def find_mp3s(path: Path) -> list[Path]:
    return sorted(path.rglob("*.mp3"), key=_mp3_sort_key)

def get_mp3_meta(mp3: Path) -> tuple[str, str, int]:
    try:
        tags = ID3(str(mp3))
        title = str(tags.get("TIT2", TIT2(text=[mp3.stem])))
        art = str(tags.get("TPE1", TPE1(text=[""])))
        dur = int(MP3(str(mp3)).info.length)
        return title, art, dur
    except: return mp3.stem, "", 0

def _embed_cover(mp3: Path, cover: bytes) -> bool:
    """Embute capa no MP3 via ffmpeg — usado APENAS para álbuns"""
    tc = to = None
    try:
        fd, tc = tempfile.mkstemp(suffix=".jpg")
        with os.fdopen(fd, "wb") as f: f.write(cover)
        to = mp3.with_suffix(".tmp.mp3")
        cmd = [FFMPEG_BIN, "-y", "-i", str(mp3), "-i", tc,
            "-map","0:a","-map","1:0","-c:a","copy",
            "-c:v","mjpeg","-id3v2_version","3",
            "-metadata:s:v","title=Album cover",
            "-metadata:s:v","comment=Cover (front)", str(to)]
        r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, timeout=60)
        if r.returncode == 0: to.replace(mp3); return True
    except Exception: pass
    finally:
        for f in (tc, to):
            if f:
                try: Path(str(f)).unlink(missing_ok=True)
                except: pass
    return False

async def _embed_covers(mp3s: list[Path], cover: bytes):
    loop = asyncio.get_event_loop()
    await asyncio.gather(
        *[loop.run_in_executor(_executor, _embed_cover, m, cover)
          for m in mp3s],
        return_exceptions=True)

def make_zip(dest: Path, name: str, files: list[Path]) -> Path:
    zp = dest.parent / f"{safe(name)}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files: zf.write(f, f.relative_to(dest))
    return zp

async def _send_mp3(uid: int, mp3: Path,
    cover: bytes | None, also_ch=False):
    title, art, dur = get_mp3_meta(mp3)
    attrs = [DocumentAttributeAudio(
        duration=dur, title=title, performer=art, voice=False)]
    async def _sf(chat):
        await bot.send_file(chat, str(mp3),
            attributes=attrs, thumb=_thumb(cover))
    tasks = [_sf(uid)]
    if also_ch and CHANNEL_ID: tasks.append(_sf(CHANNEL_ID))
    await asyncio.gather(*tasks, return_exceptions=True)

# ═══════════════════════════════════════════════════════════════
# TASK — Download + Envio Deezer
# ═══════════════════════════════════════════════════════════════
_global_dl = asyncio.Semaphore(MAX_GLOBAL_DL)

async def _dl_task_dz(uid: int, modo: str, pending: dict, card_msg):
    async with dl_lock(uid):
        async with _global_dl:
            nome = pending["name"]
            tipo = pending["type"]
            cover_url = pending.get("cover_url")
            dz_url = pending["dz_url"]
            ico = {"album":"💿","playlist":"📋","track":"🎵"}.get(tipo,"🎵")
            dest = DOWNLOAD_DIR / str(uid) / safe(nome)
            dest.mkdir(parents=True, exist_ok=True)

            def _cancelled() -> bool:
                return _cancel_flags.get(uid, False)

            async def _upd(text: str, show_cancel=True):
                btns = cancel_btn(uid) if show_cancel else None
                try:
                    await card_msg.edit(text, buttons=btns, parse_mode="md")
                except Exception: pass

            try:
                cover = await _fetch_cover(cover_url)

                # ── Download ──────────────────────────────────
                await _upd(
                    f"📥 **Baixando…**\n\n{ico} _{nome}_\n\n⏳ Aguarde…")

                tracker = await asyncio.get_event_loop().run_in_executor(
                    _executor, _sync_dz_download, dz_url, dest, uid)

                if _cancelled(): raise asyncio.CancelledError()

                mp3s = find_mp3s(dest)
                if not mp3s:
                    await card_msg.edit(
                        "😔 **Nenhum arquivo baixado.**\n\n"
                        "ARL expirada ou conteúdo indisponível.",
                        buttons=[[Button.inline("🏠 Menu", b"mn")]],
                        parse_mode="md")
                    return

                total = len(mp3s)
                falhas = len(getattr(tracker, "failed", []))

                # ── Capa via ffmpeg (APENAS álbum) ─────────────
                if tipo == "album" and cover:
                    await _upd(
                        f"🖼️ **Embutindo capas via ffmpeg…**\n\n"
                        f"{ico} _{nome}_\n📀 {total} faixa(s)")
                    if _cancelled(): raise asyncio.CancelledError()
                    await _embed_covers(mp3s, cover)

                # ── Envio ─────────────────────────────────────
                if modo == "z" and tipo != "track":
                    await _upd(
                        f"🗜️ **Compactando {total} faixa(s)…**\n\n"
                        f"{ico} _{nome}_")
                    if _cancelled(): raise asyncio.CancelledError()

                    zp = await asyncio.get_event_loop().run_in_executor(
                        _executor, make_zip, dest, nome, mp3s)

                    await _upd(
                        f"📤 **Enviando ZIP…**\n\n{ico} _{nome}_")
                    if _cancelled(): raise asyncio.CancelledError()

                    await bot.send_file(
                        uid, str(zp),
                        caption=(f"🗜️ **{nome}**\n"
                            f"🎵 {total} faixa(s)"
                            + (f"\n⚠️ {falhas} com falha" if falhas else "")),
                        thumb=_thumb(cover), parse_mode="md")
                    asyncio.get_event_loop().run_in_executor(
                        _executor, lambda: zp.unlink(missing_ok=True))

                else:
                    # Arquivos individuais
                    also_ch = tipo in ("album", "track")
                    done = 0
                    sem = asyncio.Semaphore(MAX_SEND_PARA)

                    for mp3 in mp3s:
                        if _cancelled(): raise asyncio.CancelledError()
                        async with sem:
                            await _send_mp3(uid, mp3, cover, also_ch)
                        done += 1
                        if done % 2 == 0 or done == total:
                            await _upd(
                                f"📤 **Enviando…**\n\n"
                                f"{ico} _{nome}_\n"
                                f"🎵 {done}/{total} faixa(s)")

                # ── Concluído ─────────────────────────────────
                aviso = f"\n⚠️ {falhas} com falha" if falhas else ""
                await card_msg.edit(
                    f"✅ **Download concluído!**\n\n"
                    f"{ico} {nome}\n"
                    f"🎵 {total} faixa(s) | MP3 128 kbps{aviso}",
                    buttons=None, parse_mode="md")

                await asyncio.sleep(3)
                await send_menu(uid)

            except asyncio.CancelledError:
                try:
                    await card_msg.edit(
                        f"❌ **Envio cancelado.**\n\n{ico} _{nome}_",
                        buttons=None, parse_mode="md")
                except Exception: pass
                await asyncio.sleep(1)
                await send_menu(uid)

            except Exception as e:
                nav(uid).pending = pending
                try:
                    await card_msg.edit(
                        friendly_error(e, f"dz '{nome}'"),
                        buttons=[[Button.inline("🏠 Menu", b"mn")]],
                        parse_mode="md")
                except Exception: pass

            finally:
                _dl_tasks.pop(uid, None)
                _cancel_flags.pop(uid, None)
                shutil.rmtree(dest, ignore_errors=True)

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    log.info(
        f"\n{'═'*52}\n"
        f"  🎵 Deezer Bot — v11 PRO\n"
        f"  🟢 Pool Deezer : {pool.count()} sessão(ões)\n"
        f"  🟢 ARLs pessoais : {user_arl.count()}\n"
        f"  👥 Usuários : {user_tracker.count()}\n"
        f"  ⚙️ Workers DL : {MAX_GLOBAL_DL}\n"
        f"  ⚙️ Workers UP : {MAX_SEND_PARA}\n"
        f"{'═'*52}"
    )
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
