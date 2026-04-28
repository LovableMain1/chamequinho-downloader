#!/usr/bin/env python3
"""
Deezer Bot — v13 (DM-only PRO) — Silva Edition
• Apenas DM (sem grupos / tópicos)
• 128 kbps liberado para todos
• 320 kbps + álbuns só para usuários com ARL premium própria
• FLAC apenas para usuários whitelisted pelo OWNER
• Card único atualizado in-place (foto preservada)
"""

# ═══════════════════════════════════════════════════════════════
# AUTO-INSTALAÇÃO
# ═══════════════════════════════════════════════════════════════
import sys
import subprocess
import importlib
import os

def _pip_install(package: str, import_name: str | None = None):
    mod = import_name or package.replace("-", "_")
    try:
        importlib.import_module(mod)
    except ImportError:
        print(f"📦 Instalando {package}...", flush=True)
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", package,
             "--quiet", "--disable-pip-version-check"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        print(f"✅ {package} instalado!", flush=True)

_DEPS = [
    ("telethon", "telethon"), ("requests", "requests"),
    ("urllib3", "urllib3"), ("python-dotenv", "dotenv"),
    ("mutagen", "mutagen"), ("deezer-py", "deezer"), ("deemix", "deemix"),
]
print("🔍 Verificando dependências...", flush=True)
for _pkg, _mod in _DEPS:
    _pip_install(_pkg, _mod)
print("✅ Todas as dependências OK!\n", flush=True)

# ═══════════════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════════════
import asyncio, json, logging, math, re, shutil, socket
import subprocess as _subprocess, tempfile, threading, time, zipfile
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

from mutagen.id3 import ID3, TIT2, TPE1, TDRC, TCON
from mutagen.mp3 import MP3

# ═══════════════════════════════════════════════════════════════
# CAMINHOS
# ═══════════════════════════════════════════════════════════════
BASE_DIR        = Path(__file__).resolve().parent
ENV_PATH        = BASE_DIR / ".env"
DOWNLOAD_DIR    = BASE_DIR / "downloads"
ARL_FILE        = BASE_DIR / "arl_user.txt"
USERS_INFO_FILE = BASE_DIR / "users_info.json"
ADMIN_CFG_FILE  = BASE_DIR / "admin_config.json"

for _d in (BASE_DIR, DOWNLOAD_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════
load_dotenv(dotenv_path=ENV_PATH)

API_ID     = int(os.getenv("API_ID", "0"))
API_HASH   = os.getenv("API_HASH", "")
BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
OWNER_ID   = int(os.getenv("OWNER_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

_MISSING = [k for k, v in {
    "API_ID": API_ID, "API_HASH": API_HASH, "BOT_TOKEN": BOT_TOKEN
}.items() if not v or v == 0]
if _MISSING:
    raise SystemExit(
        f"❌ Variáveis faltando no .env: {', '.join(_MISSING)}\n"
        f"   Arquivo esperado em: {ENV_PATH}"
    )

ITEMS_PER_PAGE = 8
DZ_BATCH       = 50
MAX_REQ_MIN    = 50
BLOCK_SECS     = 60
SPAM_WINDOW    = 2.0
SPAM_SOFT      = 20
SPAM_HARD      = 35
MAX_GLOBAL_DL  = 8
MAX_SEND_PARA  = 8
FFMPEG_BIN     = shutil.which("ffmpeg") or "ffmpeg"

# ── Mapa de qualidade ──────────────────────────────────────────
QUALITY_MAP = {
    "9": ("FLAC",    "🎵 FLAC (Lossless)"),
    "3": ("MP3_320", "🎵 MP3 320 kbps"),
    "1": ("MP3_128", "🎵 MP3 128 kbps"),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("dzbot")

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "Mozilla/5.0"
_executor = ThreadPoolExecutor(
    max_workers=MAX_GLOBAL_DL * 3, thread_name_prefix="dz"
)

# ═══════════════════════════════════════════════════════════════
# REGISTRO DE USUÁRIOS
# ═══════════════════════════════════════════════════════════════
class UsersRegistry:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(
                    self.path.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

    def _save(self):
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8")

    def register(self, uid: int, first_name="", last_name="", username=""):
        key = str(uid)
        now = datetime.utcnow().isoformat(timespec="seconds")
        with self._lock:
            if key in self._data:
                self._data[key]["last_seen"] = now
                self._data[key]["interactions"] = \
                    self._data[key].get("interactions", 0) + 1
                for f, v in [("first_name", first_name),
                              ("last_name", last_name),
                              ("username", username)]:
                    if v:
                        self._data[key][f] = v
            else:
                self._data[key] = {
                    "user_id": uid, "first_name": first_name,
                    "last_name": last_name, "username": username,
                    "first_seen": now, "last_seen": now,
                    "interactions": 1, "downloads": 0,
                }
            self._save()

    def add_download(self, uid: int):
        key = str(uid)
        with self._lock:
            if key in self._data:
                self._data[key]["downloads"] = \
                    self._data[key].get("downloads", 0) + 1
                self._save()

    def count(self) -> int:
        return len(self._data)

    def get_all(self) -> dict:
        return dict(self._data)

users_reg = UsersRegistry(USERS_INFO_FILE)

# ═══════════════════════════════════════════════════════════════
# ADMIN CONFIG — qualidade por usuário, visibilidade ARL
# ═══════════════════════════════════════════════════════════════
class AdminConfig:
    """
    Persiste configurações do admin:
    - user_quality:     {uid_str: "9"|"3"|"1"}  → qualidade máxima permitida
    - arl_info_visible: {uid_str: bool}          → se usuário vê infos ARL
    - groups_allowed:   bool                     → permitir bot ser adicionado a grupos
    """
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._data: dict = {
            "user_quality": {},
            "arl_info_visible": {},
            "groups_allowed": False,  # padrão: bloqueado
        }
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                # Mapas
                for k in ("user_quality", "arl_info_visible"):
                    self._data[k] = d.get(k, {})
                # Booleanos / escalares
                if "groups_allowed" in d:
                    self._data["groups_allowed"] = bool(d["groups_allowed"])
            except Exception:
                pass

    def _save(self):
        self.path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8")

    # ── Qualidade por usuário ─────────────────────────────────
    def get_user_quality(self, uid: int) -> str | None:
        """Retorna bitrate máximo do usuário ou None (sem restrição)."""
        return self._data["user_quality"].get(str(uid))

    def set_user_quality(self, uid: int, bitrate: str | None):
        with self._lock:
            if bitrate is None:
                self._data["user_quality"].pop(str(uid), None)
            else:
                self._data["user_quality"][str(uid)] = bitrate
            self._save()

    def list_user_qualities(self) -> dict:
        return dict(self._data["user_quality"])

    # ── Visibilidade de infos da ARL ─────────────────────────
    def arl_info_visible(self, uid: int) -> bool:
        """True = usuário pode ver infos da conta ARL (padrão: True)."""
        return self._data["arl_info_visible"].get(str(uid), True)

    def set_arl_info_visible(self, uid: int, visible: bool):
        with self._lock:
            self._data["arl_info_visible"][str(uid)] = visible
            self._save()

    # ── Permissão para grupos (bot ser adicionado) ───────────
    def groups_allowed(self) -> bool:
        return bool(self._data.get("groups_allowed", False))

    def set_groups_allowed(self, allowed: bool):
        with self._lock:
            self._data["groups_allowed"] = bool(allowed)
            self._save()

admin_cfg = AdminConfig(ADMIN_CFG_FILE)

# ═══════════════════════════════════════════════════════════════
# FLAC WHITELIST (DM-only — sem grupos, sem permissões extras)
# ═══════════════════════════════════════════════════════════════
FLAC_FILE = BASE_DIR / "flac_whitelist.json"

class FlacWhitelist:
    """UIDs liberados pelo OWNER para baixar em FLAC."""
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self._uids: set[int] = set()
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                d = json.loads(self.path.read_text(encoding="utf-8"))
                self._uids = set(int(x) for x in d.get("uids", []))
            except Exception:
                self._uids = set()

    def _save(self):
        self.path.write_text(
            json.dumps({"uids": sorted(self._uids)},
                       indent=2, ensure_ascii=False),
            encoding="utf-8")

    def can_flac(self, uid: int) -> bool:
        return uid == OWNER_ID or uid in self._uids

    def add(self, uid: int):
        with self._lock:
            self._uids.add(int(uid))
            self._save()

    def remove(self, uid: int) -> bool:
        with self._lock:
            if uid in self._uids:
                self._uids.discard(int(uid))
                self._save()
                return True
            return False

    def list(self) -> list[int]:
        return sorted(self._uids)

flac_wl = FlacWhitelist(FLAC_FILE)


def _is_premium_plan(plan: str) -> bool:
    """Detecta se o plano da ARL é premium (libera 320/álbuns)."""
    if not plan:
        return False
    p = str(plan).lower()
    bad = ("free", "gratu", "discovery", "—", "deezer free")
    if any(b in p for b in bad):
        return False
    good = ("premium", "hifi", "hi-fi", "family", "student",
            "duo", "plus", "deluxe")
    return any(g in p for g in good)



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
_SIG_CONN = ("connection", "reset by peer", "broken pipe", "timed out",
             "errno 104", "errno 110", "errno 111", "remotedisconnected",
             "max retries exceeded", "network is unreachable")
_SIG_ARL  = ("unauthorized", "403", "invalid arl", "not logged", "token expired")
_SIG_CONT = ("not available", "not found", "no tracks", "list index",
             "nonetype", "geo blocked", "track is not readable")

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
    except Exception:
        return "—"

def fmt_num(n) -> str:
    try:
        return f"{int(n):,}".replace(",", ".")
    except Exception:
        return str(n)

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
            if not line or line.startswith("#"):
                continue
            p = line.split("|")
            if len(p) < 2:
                continue
            try:
                uid = int(p[0])
                self._c[uid] = {
                    "user_id": uid, "arl": p[1],
                    "name":     p[2] if len(p) > 2 else "",
                    "country":  p[3] if len(p) > 3 else "",
                    "plan":     p[4] if len(p) > 4 else "",
                    "added_at": p[5] if len(p) > 5 else "",
                }
            except Exception:
                continue

    def _save(self):
        lines = [self.HEADER]
        for d in self._c.values():
            lines.append("|".join([
                str(d["user_id"]), d["arl"], d.get("name", ""),
                d.get("country", ""), d.get("plan", ""), d.get("added_at", ""),
            ]) + "\n")
        self.path.write_text("".join(lines), encoding="utf-8")

    def get(self, uid: int) -> dict | None:
        return self._c.get(uid)

    def is_premium(self, uid: int) -> bool:
        """Apenas usuários com ARL própria de plano premium."""
        d = self._c.get(uid)
        if not d:
            return False
        return _is_premium_plan(d.get("plan", ""))

    def has_arl(self, uid: int) -> bool:
        return uid in self._c

    def count(self) -> int:
        return len(self._c)

    async def save(self, uid: int, arl: str, name="", country="", plan=""):
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
            if uid not in self._c:
                return False
            del self._c[uid]
            await asyncio.get_event_loop().run_in_executor(
                _executor, self._save)
            return True

    @staticmethod
    def validate_arl(arl: str) -> dict | None:
        try:
            dz = Deezer()
            if not dz.login_via_arl(arl.strip()):
                return None
            info = {"name": "Usuário Deezer", "country": "—", "plan": "—"}
            try:
                r = dz.session.get(
                    "https://api.deezer.com/user/me", timeout=10)
                if r.ok:
                    d = r.json()
                    info["name"]    = d.get("name", info["name"])
                    info["country"] = d.get("country", info["country"])
            except Exception:
                pass
            try:
                cu = getattr(dz, "current_user", {}) or {}
                info["name"]    = cu.get("name", info["name"])
                info["country"] = cu.get("country", info["country"])
                info["plan"]    = cu.get("offer_name", info["plan"])
            except Exception:
                pass
            _patch_dz(dz)
            return info
        except Exception as e:
            log.error(f"validate_arl: {e}")
            return None

    def open_session(self, uid: int) -> Deezer | None:
        d = self.get(uid)
        if not d:
            return None
        try:
            dz = Deezer()
            if dz.login_via_arl(d["arl"]):
                _patch_dz(dz)
                return dz
        except Exception:
            pass
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
    lines = []
    updated = False
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
            if s:
                self._sessions.append(s)
        if not self._sessions:
            raise RuntimeError(
                f"❌ Nenhuma ARL válida no .env\n"
                f"   Adicione DEEZER_ARL=seu_token em: {ENV_PATH}"
            )

    def _make(self, idx, arl) -> dict | None:
        dz = Deezer()
        ok = dz.login_via_arl(arl)
        log.info(f"{'✅' if ok else '❌'} ARL #{idx} [{arl[:18]}…]")
        if not ok:
            return None
        _patch_dz(dz)
        return {"idx": idx, "arl": arl, "dz": dz}

    def primary(self) -> dict:  return self._sessions[0]
    def all(self) -> list[dict]: return list(self._sessions)
    def arls(self) -> list[str]: return [s["arl"] for s in self._sessions]
    def count(self) -> int:      return len(self._sessions)

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
            with self._lock:
                self._sessions.append(s)
        return s is not None

    def remove(self, pos: int) -> str | None:
        with self._lock:
            if 0 <= pos < len(self._sessions):
                r = self._sessions.pop(pos)
                for i, s in enumerate(self._sessions, 1):
                    s["idx"] = i
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
        if uid == OWNER_ID:
            return True, 0
        now = time.time()
        if uid in self._bl:
            if now < self._bl[uid]:
                return False, int(self._bl[uid] - now)
            del self._bl[uid]
        q = self._ev.setdefault(uid, deque())
        cutoff = now - 60
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= MAX_REQ_MIN:
            self._bl[uid] = now + BLOCK_SECS
            return False, BLOCK_SECS
        q.append(now)
        return True, 0

    def unblock(self, uid: int):
        self._bl.pop(uid, None)
        self._ev.pop(uid, None)

    def unblock_all(self):
        self._bl.clear()
        self._ev.clear()

    def blocked_list(self) -> list:
        now = time.time()
        return [(u, int(t - now)) for u, t in self._bl.items() if t > now]

class AntiSpam:
    def __init__(self):
        self._cl: dict[int, deque] = {}
        self._bl: dict[int, float] = {}

    def hit(self, uid: int) -> tuple[bool, str]:
        if uid == OWNER_ID:
            return True, ""
        now = time.time()
        if uid in self._bl:
            rem = self._bl[uid] - now
            if rem > 0:
                return False, f"🚦 Aguarde **{int(rem)}s**."
            del self._bl[uid]
        q = self._cl.setdefault(uid, deque())
        cutoff = now - SPAM_WINDOW
        while q and q[0] < cutoff:
            q.popleft()
        q.append(now)
        cnt = len(q)
        if cnt >= SPAM_HARD:
            self._bl[uid] = now + 90
            return False, "🚦 Muitas ações! Aguarde **90s**."
        if cnt >= SPAM_SOFT:
            self._bl[uid] = now + 30
            return False, "🚦 Devagar! Aguarde **30s**."
        return True, ""

    def clear(self, uid: int):
        self._bl.pop(uid, None)
        self._cl.pop(uid, None)

    def clear_all(self):
        self._bl.clear()
        self._cl.clear()

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
    def total(self) -> int:
        return self._total or 0

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
        end   = start + ITEMS_PER_PAGE
        missing = [i for i in range(start, end) if i not in self._cache]
        if not missing:
            return
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
        if t == "artist":
            return f"👤 {n[:46]}"
        if t == "playlist":
            c = (item.get("creator") or {}).get("name", "")
            return f"📋 {n[:28]} — {c[:16]}"
        return n[:48]

    def item_cb(self, item: dict) -> bytes:
        short = {"track": "tr", "album": "al",
                 "artist": "ar", "playlist": "pl"}[self.item_type]
        return f"sel:{short}:{item.get('id', '0')}".encode()

# ═══════════════════════════════════════════════════════════════
# ESTADO DE NAVEGAÇÃO — AGORA COM card_cover
# ═══════════════════════════════════════════════════════════════
class NavState:
    __slots__ = ("stack", "page", "query", "step", "pending",
                 "card_msg", "card_caption", "card_btns", "card_cover",
                 "explore_history")

    def __init__(self):
        self.stack: list[DeezerPager] = []
        self.page: int = 0
        self.query: str = ""
        self.step: str = "idle"
        self.pending: dict = {}
        self.card_msg = None
        self.card_caption: str = ""
        self.card_btns: list = []
        self.card_cover: bytes | None = None  # ← NOVO: capa do álbum
        self.explore_history: list[tuple[str, int]] = []

    @property
    def pager(self) -> DeezerPager | None:
        return self.stack[-1] if self.stack else None

    def push(self, p):
        self.stack.append(p)
        self.page = 0

    def pop(self) -> bool:
        if len(self.stack) > 1:
            self.stack.pop()
            self.page = 0
            return True
        return False

    def clear(self):
        self.stack.clear()
        self.page = 0
        self.step = "idle"
        self.pending = {}
        self.card_msg     = None
        self.card_caption = ""
        self.card_btns    = []
        self.card_cover   = None
        self.explore_history.clear()

_nav: dict[int, NavState] = {}
_dl_locks: dict[int, asyncio.Lock] = {}
_dl_tasks: dict[int, asyncio.Task] = {}
_cancel_flags: dict[int, bool] = {}

def nav(uid: int) -> NavState:
    if uid not in _nav:
        _nav[uid] = NavState()
    return _nav[uid]

def dl_lock(uid: int) -> asyncio.Lock:
    if uid not in _dl_locks:
        _dl_locks[uid] = asyncio.Lock()
    return _dl_locks[uid]

# ═══════════════════════════════════════════════════════════════
# DEEZER API
# ═══════════════════════════════════════════════════════════════
DZ = "https://api.deezer.com"
DZ_URL_RE = re.compile(
    r"deezer\.com(?:/[a-z]{2})?/(track|album|playlist|artist)/(\d+)",
    re.IGNORECASE,
)
# Qualquer URL relacionada ao Deezer (curtos, page.link, www.deezer.com/...)
DZ_ANY_URL_RE = re.compile(
    r"https?://[^\s]*(?:deezer\.com|deezer\.page\.link|link\.deezer\.com|"
    r"dzr\.page\.link|deezer\.lnk\.to)[^\s]*",
    re.IGNORECASE,
)
# Detecta playlist em qualquer formato (rejeitada)
DZ_PLAYLIST_RE = re.compile(r"/playlist/\d+", re.IGNORECASE)

def _http_resolve(url: str) -> str:
    """Resolve qualquer redirect (curtos, page.link, lnk.to) até a URL final."""
    try:
        r = HTTP.head(url, allow_redirects=True, timeout=15)
        final = r.url or url
        # Alguns serviços (lnk.to) não respeitam HEAD — tenta GET
        if "deezer.com" not in final and "deezer.page.link" not in final:
            try:
                r2 = HTTP.get(url, allow_redirects=True, timeout=15,
                              stream=True)
                final = r2.url or final
                r2.close()
            except Exception:
                pass
        return final
    except Exception:
        try:
            r2 = HTTP.get(url, allow_redirects=True, timeout=15, stream=True)
            final = r2.url or url
            r2.close()
            return final
        except Exception:
            return url

def resolve_short(url: str) -> str:
    if any(x in url.lower() for x in
           ("link.deezer.com", "deezer.page.link",
            "dzr.page.link", "deezer.lnk.to")):
        return _http_resolve(url)
    return url

def detect_dz_url(text: str):
    """
    Aceita qualquer URL Deezer (curta ou longa).
    Retorna (tipo, id) — ou ("__playlist__", "") se for playlist
    (que é proibida) — ou None se nada.
    """
    m_any = DZ_ANY_URL_RE.search(text)
    if not m_any:
        # Permite também colar só o caminho deezer.com/album/123
        m_direct = DZ_URL_RE.search(text)
        if not m_direct:
            return None
        url = "https://www." + m_direct.group(0)
    else:
        url = m_any.group(0)

    final = resolve_short(url)
    if DZ_PLAYLIST_RE.search(final):
        return ("__playlist__", "")
    m = DZ_URL_RE.search(final)
    if m:
        return (m.group(1).lower(), m.group(2))
    # Tentativa final: pegar HTML e extrair og:url / canonical
    try:
        r = HTTP.get(final, timeout=15)
        if r.ok:
            m2 = DZ_URL_RE.search(r.text)
            if m2:
                if DZ_PLAYLIST_RE.search(m2.group(0)):
                    return ("__playlist__", "")
                return (m2.group(1).lower(), m2.group(2))
    except Exception:
        pass
    return None


def _api(path: str, **p):
    r = HTTP.get(f"{DZ}/{path}", params=p, timeout=15)
    r.raise_for_status()
    return r.json()

def dl_dz_url(tipo, iid):
    return f"https://www.deezer.com/{tipo}/{iid}"

# ═══════════════════════════════════════════════════════════════
# CARDS
# ═══════════════════════════════════════════════════════════════
def card_track(t: dict) -> str:
    return (
        f"🎵 **{t.get('title', '?')}**\n\n"
        f"👤 Artista : {t.get('artist', {}).get('name', '—')}\n"
        f"💿 Álbum   : {t.get('album', {}).get('title', '—')}\n"
        f"⏱ Duração : {fmt_dur(t.get('duration', 0))}\n"
        f"📅 Lançado : {str(t.get('release_date', '—'))[:10]}"
    )

def card_album(a: dict) -> str:
    genres = ", ".join(
        g["name"] for g in a.get("genres", {}).get("data", [])
    ) or "—"
    yr = str(a.get("release_date", ""))[:4] or "—"
    return (
        f"💿 **{a.get('title', '?')} ({yr})**\n\n"
        f"👤 Artista : {a.get('artist', {}).get('name', '—')}\n"
        f"📅 Ano     : {yr}\n"
        f"🎵 Faixas  : {a.get('nb_tracks', '?')}\n"
        f"🎼 Gênero  : {genres}\n"
        f"⏱ Duração : {fmt_dur(a.get('duration', 0))}"
    )

def card_playlist(p: dict) -> str:
    return (
        f"📋 **{p.get('title', '?')}**\n\n"
        f"👤 Criador : {p.get('creator', {}).get('name', '—')}\n"
        f"🎵 Faixas  : {p.get('nb_tracks', '?')}\n"
        f"⏱ Duração : {fmt_dur(p.get('duration', 0))}"
    )

def card_artist(a: dict) -> str:
    return (
        f"👤 **{a.get('name', '?')}**\n\n"
        f"💿 Álbuns : {a.get('nb_album', '?')}\n"
        f"❤️ Fãs   : {fmt_num(a.get('nb_fan', 0))}\n"
        f"🌐 Link  : [Deezer]({a.get('link', '')})"
    )

# ═══════════════════════════════════════════════════════════════
# BOTÕES — incluindo seleção de formato
# ═══════════════════════════════════════════════════════════════
def main_menu_btns(uid: int) -> list:
    rows = [[Button.inline("🌐 Explorar", b"explore")]]
    if uid == OWNER_ID:
        rows.append([Button.inline("🔑 Minha ARL Deezer", b"my_arl"),
                     Button.inline("⚙️ Pool Deezer", b"ow:panel")])
    else:
        rows.append([Button.inline("🔑 Minha ARL Deezer", b"my_arl")])
    if uid == OWNER_ID:
        rows.append([
            Button.inline("🎼 Liberar FLAC",      b"ow:flac"),
            Button.inline("🎚 Qualidade Usuários", b"ow:quality"),
        ])
        rows.append([
            Button.inline("🔓 Remover Limitações", b"ow:unlimit"),
            Button.inline("📊 Estatísticas", b"ow:stats"),
        ])
    return rows

def search_type_btns() -> list:
    return [
        [Button.inline("🎵 Faixas",    b"stype:tr"),
         Button.inline("💿 Álbuns",    b"stype:al")],
        [Button.inline("📋 Playlists", b"stype:pl"),
         Button.inline("👤 Artistas",  b"stype:ar")],
        [Button.inline("❌ Cancelar",  b"mn")],
    ]

async def pager_btns(uid: int) -> list:
    st = nav(uid)
    pg = st.pager
    if not pg:
        return [[Button.inline("🏠 Menu", b"mn")]]
    items = await pg.get_page(st.page)
    total_p = pg.total_pages
    rows = []
    for item in items:
        rows.append([Button.inline(pg.item_label(item)[:60], pg.item_cb(item))])
    nav_row = []
    if st.page > 0:
        nav_row.append(Button.inline("◀️", b"pg:prev"))
    lbl = f"📄 {st.page + 1}/{total_p}"
    if pg.total:
        lbl += f" ({pg.total})"
    nav_row.append(Button.inline(lbl, b"noop"))
    if st.page + 1 < total_p:
        nav_row.append(Button.inline("▶️", b"pg:next"))
    rows.append(nav_row)
    ctx = []
    if len(st.stack) > 1:
        ctx.append(Button.inline("◀️ Voltar", b"back"))
    ctx.append(Button.inline("🏠 Menu", b"mn"))
    rows.append(ctx)
    return rows

def dl_format_btns(uid: int, tipo: str, has_arl: bool) -> list:
    """
    Botões de seleção de formato — regras DM-only:
      • Todos os usuários podem baixar em MP3 128 kbps (faixa única).
      • Usuário com **qualquer ARL própria** configurada → MP3 320 kbps + álbuns.
      • FLAC → apenas usuários liberados pelo OWNER (whitelist).
      • OWNER tem todas as qualidades + ZIP de álbuns/playlists.
    Callback: dlstart:{bitrate}:{mode}:{uid}
      bitrate: 9=FLAC, 3=MP3_320, 1=MP3_128
      mode:    f=arquivos individuais, z=ZIP
    Para usuários sem ARL: álbuns/playlists são bloqueados (apenas faixas únicas).
    """
    is_multi = tipo in ("album", "playlist")
    rows = []

    can_flac    = flac_wl.can_flac(uid)
    can_320     = has_arl or uid == OWNER_ID
    # Admin pode restringir qualidade máxima manualmente
    max_q = admin_cfg.get_user_quality(uid)  # "9", "3", "1" ou None

    def _allowed(bitrate: str) -> bool:
        if bitrate == "9" and not can_flac:
            return False
        if bitrate == "3" and not can_320:
            return False
        if max_q is not None and int(bitrate) > int(max_q):
            return False
        return True

    if _allowed("9"):
        if is_multi:
            rows.append([
                Button.inline("🎼 FLAC — Arquivos", f"dlstart:9:f:{uid}".encode()),
                Button.inline("🎼 FLAC — ZIP",      f"dlstart:9:z:{uid}".encode()),
            ])
        else:
            rows.append([Button.inline("🎼 FLAC (Lossless)",
                                       f"dlstart:9:f:{uid}".encode())])

    if _allowed("3"):
        if is_multi:
            rows.append([
                Button.inline("🎵 MP3 320 — Arquivos", f"dlstart:3:f:{uid}".encode()),
                Button.inline("🎵 MP3 320 — ZIP",      f"dlstart:3:z:{uid}".encode()),
            ])
        else:
            rows.append([Button.inline("🎵 MP3 320 kbps",
                                       f"dlstart:3:f:{uid}".encode())])

    if _allowed("1"):
        # 128 kbps: faixa única para todos; álbum/playlist somente para premium/OWNER
        if is_multi:
            if can_320:
                rows.append([
                    Button.inline("🎶 MP3 128 — Arquivos", f"dlstart:1:f:{uid}".encode()),
                    Button.inline("🎶 MP3 128 — ZIP",      f"dlstart:1:z:{uid}".encode()),
                ])
            # Usuários sem premium não baixam álbum inteiro (apenas faixas únicas)
        else:
            rows.append([Button.inline("🎶 MP3 128 kbps",
                                       f"dlstart:1:f:{uid}".encode())])

    if not rows:
        rows.append([Button.inline("🚫 Sem qualidade disponível para este item", b"noop")])

    rows.append([
        Button.inline("◀️ Voltar", b"dl:back"),
        Button.inline("🏠 Menu",   b"mn"),
    ])
    return rows

def cancel_btn(uid: int) -> list:
    return [[Button.inline("❌ Cancelar envio", f"dl:cancel:{uid}".encode())]]

def album_btns(aid: str) -> list:
    return [
        [Button.inline("⬇️ Baixar álbum",  f"dl:al:{aid}".encode())],
        [Button.inline("🎵 Ver faixas",    f"al:tracks:{aid}".encode())],
        [Button.inline("◀️ Voltar", b"back"), Button.inline("🏠 Menu", b"mn")],
    ]

def track_btns(tid: str) -> list:
    return [
        [Button.inline("⬇️ Baixar faixa", f"dl:tr:{tid}".encode())],
        [Button.inline("◀️ Voltar", b"back"), Button.inline("🏠 Menu", b"mn")],
    ]

def playlist_btns(plid: str) -> list:
    return [
        [Button.inline("⬇️ Baixar playlist", f"dl:pl:{plid}".encode())],
        [Button.inline("🎵 Ver faixas",      f"pl:tracks:{plid}".encode())],
        [Button.inline("◀️ Voltar", b"back"), Button.inline("🏠 Menu", b"mn")],
    ]

def artist_btns(aid: str) -> list:
    return [
        [Button.inline("💿 Ver álbuns",  f"ar:al:{aid}".encode())],
        [Button.inline("🏆 Top faixas", f"ar:top:{aid}".encode())],
        [Button.inline("◀️ Voltar", b"back"), Button.inline("🏠 Menu", b"mn")],
    ]

def owner_panel_btns() -> list:
    return [
        [Button.inline("➕ Adicionar ARL",    b"ow:add"),
         Button.inline("🗑 Remover ARL",      b"ow:listrm")],
        [Button.inline("🔄 Renovar sessões",  b"ow:refresh")],
        [Button.inline("🔓 Remover limitações", b"ow:unlimit"),
         Button.inline("📊 Estatísticas",      b"ow:stats")],
        [Button.inline("🎼 Liberar FLAC",       b"ow:flac"),
         Button.inline("🎚 Qualidade Usuários", b"ow:quality")],
        [Button.inline("👁 ARL Visível",        b"ow:arlvis")],
        [Button.inline("🏠 Menu", b"mn")],
    ]

# ═══════════════════════════════════════════════════════════════
# TELEGRAM CLIENT — DM-ONLY (sem grupos / tópicos)
# ═══════════════════════════════════════════════════════════════
SESSION_PATH = str(BASE_DIR / "dz_bot_v13")
bot = TelegramClient(SESSION_PATH, API_ID, API_HASH)

def _event_chat_id(event) -> int:
    try:
        return int(event.chat_id)
    except Exception:
        return int(event.sender_id)

def _event_topic_id(event) -> int | None:
    return None  # DM-only

def _set_target(uid: int, chat_id: int, topic_id: int | None):
    return  # no-op

def _target_for(uid: int) -> tuple[int, int | None]:
    """Sempre envia para o DM do usuário."""
    return (uid, None)

def _send_kwargs(uid: int) -> dict:
    return {}

async def _gate(event, is_cb: bool = True) -> bool:
    """
    Gate DM-only:
      - O bot responde APENAS em conversas privadas.
      - Em grupos / canais / supergrupos: silenciosamente ignora.
      - Spam check sempre aplicado.
    """
    sender_id = event.sender_id
    chat_id   = _event_chat_id(event)
    is_dm     = chat_id == sender_id

    if not is_dm:
        return False

    ok, msg = spam.hit(sender_id)
    if not ok:
        if is_cb:
            await event.answer(msg[:200], alert=True)
        else:
            await event.respond(msg, parse_mode="md")
        return False
    return True


async def _fetch_cover(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        r = await asyncio.get_event_loop().run_in_executor(
            _executor, lambda: HTTP.get(url, timeout=10))
        return r.content if r.ok else None
    except Exception:
        return None

def _thumb(cover: bytes | None) -> BytesIO | None:
    if not cover:
        return None
    b = BytesIO(cover)
    b.name = "cover.jpg"
    return b

async def _send_card(chat_id, cover: bytes | None, caption: str, btns: list,
                     reply_to: int | None = None):
    """Envia card com ou sem foto. Suporta tópico via reply_to."""
    kw = {"caption": caption, "parse_mode": "md",
          "buttons": btns or None}
    if reply_to:
        kw["reply_to"] = reply_to
    if cover:
        buf = BytesIO(cover)
        buf.name = "c.jpg"
        return await bot.send_file(chat_id, buf, **kw)
    extra = {"reply_to": reply_to} if reply_to else {}
    return await bot.send_message(
        chat_id, caption, buttons=btns or None, parse_mode="md", **extra)

async def _edit_card(card_msg, caption: str, btns: list | None):
    """
    Edita o caption de um card (foto ou texto) sem recriar a mensagem.
    Em Telethon, Message.edit() em mensagem com media atualiza apenas o caption.
    """
    try:
        await card_msg.edit(caption, buttons=btns or None, parse_mode="md")
    except Exception as e:
        log.warning(f"_edit_card falhou: {e}")

async def send_menu(uid: int, event=None):
    nav(uid).clear()
    arl_d  = user_arl.get(uid)
    is_prem = user_arl.is_premium(uid)
    can_flac = flac_wl.can_flac(uid)

    if arl_d:
        plan = arl_d.get("plan", "—") or "—"
        if is_prem:
            arl_tag = f"🔑 ARL: ✅ _{arl_d.get('name','Configurada')}_ — 💎 {plan}\n"
        else:
            arl_tag = f"🔑 ARL: ✅ _{arl_d.get('name','Configurada')}_ — 🆓 {plan}\n"
    else:
        arl_tag = "🔑 ARL: ❌ Não configurada (somente MP3 128 kbps)\n"

    quals = ["MP3 128"]
    if is_prem or uid == OWNER_ID:
        quals.insert(0, "MP3 320")
    if can_flac:
        quals.insert(0, "FLAC")
    qual_line = "🎧 Qualidades disponíveis: " + " · ".join(quals)

    text = (
        f"🎵 **Deezer Bot — v13 (DM-only PRO)**\n\n"
        f"{arl_tag}{qual_line}\n\n"
        f"🔍 Digite o nome de uma música, álbum ou artista\n"
        f"ou cole um link do Deezer (faixa, álbum ou artista)."
    )
    if event:
        try:
            await event.delete()
        except Exception:
            pass
    await bot.send_message(
        uid, text, buttons=main_menu_btns(uid), parse_mode="md")

async def _register_user(event):
    try:
        sender = await event.get_sender()
        if sender:
            users_reg.register(
                uid=sender.id,
                first_name=getattr(sender, "first_name", "") or "",
                last_name=getattr(sender, "last_name", "")  or "",
                username=getattr(sender, "username", "")    or "",
            )
    except Exception:
        pass

# ═══════════════════════════════════════════════════════════════
# HANDLERS — Navegação básica
# ═══════════════════════════════════════════════════════════════
@bot.on(events.NewMessage(pattern="/start"))
async def h_start(event):
    await _register_user(event)
    await send_menu(event.sender_id)

@bot.on(events.CallbackQuery(data=b"mn"))
async def h_mn(event):
    await event.answer()
    await _register_user(event)
    await send_menu(event.sender_id, event)

@bot.on(events.CallbackQuery(data=b"noop"))
async def h_noop(event):
    await event.answer()

@bot.on(events.CallbackQuery(data=b"back"))
async def h_back(event):
    await event.answer()
    uid = event.sender_id
    st  = nav(uid)
    if st.pop():
        btns = await pager_btns(uid)
        pg   = st.pager
        try:
            await event.edit(pg.title, buttons=btns, parse_mode="md")
        except Exception:
            await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")
    else:
        await send_menu(uid, event)

@bot.on(events.CallbackQuery(data=b"dl:back"))
async def h_dl_back(event):
    """Volta do menu de formato para o card original do item."""
    await event.answer()
    uid = event.sender_id
    st  = nav(uid)
    if st.card_msg and st.card_caption and st.card_btns:
        await _edit_card(st.card_msg, st.card_caption, st.card_btns)
    else:
        await send_menu(uid, event)

@bot.on(events.CallbackQuery(pattern=rb"pg:(prev|next)"))
async def h_page(event):
    if not await _gate(event):
        return
    await event.answer()
    uid = event.sender_id
    st  = nav(uid)
    if not st.pager:
        return
    d = event.pattern_match.group(1)
    if d == b"next" and st.page + 1 < st.pager.total_pages:
        st.page += 1
    elif d == b"prev" and st.page > 0:
        st.page -= 1
    btns = await pager_btns(uid)
    try:
        await event.edit(st.pager.title, buttons=btns, parse_mode="md")
    except Exception:
        pass

# ─── Busca ────────────────────────────────────────────────────
def _pager_search(query: str, tipo: str) -> DeezerPager:
    paths = {
        "tr": ("search",           "track",    "🎵"),
        "al": ("search/album",     "album",    "💿"),
        "pl": ("search/playlist",  "playlist", "📋"),
        "ar": ("search/artist",    "artist",   "👤"),
    }
    path, item_type, ico = paths[tipo]
    return DeezerPager(
        f"{ico} Resultados: **{query}**",
        f"{DZ}/{path}", {"q": query}, item_type,
    )

@bot.on(events.CallbackQuery(pattern=rb"stype:(tr|al|pl|ar)"))
async def h_stype(event):
    if not await _gate(event):
        return
    await event.answer()
    uid  = event.sender_id
    tipo = event.pattern_match.group(1).decode()
    st   = nav(uid)
    if not st.query:
        return await event.edit(
            "❌ Sessão expirada.",
            buttons=[[Button.inline("🏠 Menu", b"mn")]])
    await event.edit(f"🔍 Buscando **{st.query}**…", parse_mode="md")
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
    st.stack.clear()
    st.push(pg)
    btns = await pager_btns(uid)
    try:
        await event.edit(pg.title, buttons=btns, parse_mode="md")
    except Exception:
        await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(data=b"search_again"))
async def h_search_again(event):
    await event.answer()
    uid = event.sender_id
    st  = nav(uid)
    if not st.query:
        return await event.edit(
            "❌ Sessão expirada.",
            buttons=[[Button.inline("🏠 Menu", b"mn")]])
    await event.edit(
        f"🔍 Buscar: **{st.query}**\n\nEscolha o tipo:",
        buttons=search_type_btns(), parse_mode="md")

# ─── Seleção de item ──────────────────────────────────────────
@bot.on(events.CallbackQuery(pattern=rb"sel:(tr|al|ar|pl):(\d+)"))
async def h_sel(event):
    if not await _gate(event):
        return
    await event.answer()
    uid  = event.sender_id
    tipo = event.pattern_match.group(1).decode()
    iid  = event.pattern_match.group(2).decode()
    st   = nav(uid)

    # Apaga card anterior se existir (evita acúmulo)
    if st.card_msg:
        try:
            await st.card_msg.delete()
        except Exception:
            pass
        st.card_msg = None

    # Edita mensagem atual para loading
    try:
        await event.edit("⏳ Carregando…")
    except Exception:
        pass

    loop = asyncio.get_event_loop()

    async def _finish_card(caption: str, btns: list, cover: bytes | None):
        """Apaga msg de loading e cria card único."""
        try:
            await event.delete()
        except Exception:
            pass
        _chat, _topic = _target_for(uid)
        card = await _send_card(_chat, cover, caption, btns, reply_to=_topic)
        st.card_msg     = card
        st.card_caption = caption
        st.card_btns    = btns
        st.card_cover   = cover  # ← salva capa

    try:
        if tipo == "tr":
            info  = await loop.run_in_executor(
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
            info  = await loop.run_in_executor(
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
            info  = await loop.run_in_executor(
                _executor, lambda: _api(f"artist/{iid}"))
            cover = await _fetch_cover(info.get("picture_xl"))
            await _finish_card(card_artist(info), artist_btns(iid), cover)

        elif tipo == "pl":
            info  = await loop.run_in_executor(
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
        err = friendly_error(e, f"sel {tipo}:{iid}")
        try:
            await event.edit(err,
                buttons=[[Button.inline("🏠 Menu", b"mn")]], parse_mode="md")
        except Exception:
            await bot.send_message(uid, err,
                buttons=[[Button.inline("🏠 Menu", b"mn")]], parse_mode="md")

# ─── Download: seleção de formato ─────────────────────────────
@bot.on(events.CallbackQuery(pattern=rb"dl:(tr|al|pl):(\d+)"))
async def h_dl_card(event):
    """Mostra seleção de formato/qualidade no próprio card."""
    if not await _gate(event):
        return
    uid = event.sender_id
    st  = nav(uid)
    if not st.pending:
        return await event.answer(
            "❌ Pedido expirado. Selecione o item novamente.", alert=True)
    await event.answer()

    p           = st.pending
    tipo        = p["type"]
    has_premium = user_arl.is_premium(uid) or uid == OWNER_ID
    ico         = "💿" if tipo != "track" else "🎵"

    # Atualiza caption do card existente (preserva a foto)
    can_flac = flac_wl.can_flac(uid)
    if has_premium and can_flac:
        premium_note = "\n✅ _Premium + FLAC liberado — todas as qualidades disponíveis_"
    elif has_premium:
        premium_note = ("\n✅ _ARL premium detectada — MP3 320 disponível_"
                        "\n🎼 _FLAC só para usuários liberados pelo dono_")
    elif can_flac:
        premium_note = "\n🎼 _FLAC liberado pelo dono — MP3 320 requer ARL premium própria_"
    else:
        premium_note = ("\n🎶 _Disponível: MP3 128 kbps_"
                        "\n⚠️ _Configure sua ARL premium para MP3 320 e álbuns_")
    caption = (
        f"{st.card_caption}\n\n"
        f"📦 **Escolha o formato:**{premium_note}"
    )
    btns = dl_format_btns(uid, tipo, has_premium)

    if st.card_msg:
        await _edit_card(st.card_msg, caption, btns)
    else:
        await event.edit(caption, buttons=btns, parse_mode="md")

# ─── Download: início ─────────────────────────────────────────
@bot.on(events.CallbackQuery(pattern=rb"dlstart:(\d):([fz]):(\d+)"))
async def h_dlstart(event):
    """
    Callback: dlstart:{bitrate}:{mode}:{uid}
    Inicia o download com o bitrate e modo selecionados.
    """
    if not await _gate(event):
        return
    bitrate = event.pattern_match.group(1).decode()  # "9", "3" ou "1"
    modo    = event.pattern_match.group(2).decode()  # "f" ou "z"
    uid     = int(event.pattern_match.group(3))

    if event.sender_id != uid:
        return await event.answer("❌ Não é seu menu!", alert=True)

    st = nav(uid)
    if not st.pending:
        return await event.answer("❌ Pedido expirado.", alert=True)
    if dl_lock(uid).locked():
        return await event.answer("⏳ Já há um download em andamento.", alert=True)

    pending = dict(st.pending)
    st.pending = {}
    _cancel_flags[uid] = False
    await event.answer()

    qual_label = QUALITY_MAP.get(bitrate, ("?", "?"))[1]
    ico        = {"album": "💿", "playlist": "📋", "track": "🎵"}.get(
        pending["type"], "🎵")

    # Atualiza card (mantém foto) com status inicial
    if st.card_msg:
        await _edit_card(
            st.card_msg,
            f"{st.card_caption}\n\n"
            f"📥 **Iniciando download…**\n"
            f"🎧 {qual_label}\n⏳ Aguarde…",
            cancel_btn(uid),
        )
        card_msg = st.card_msg
    else:
        card_msg = await bot.send_message(
            uid,
            f"📥 **Iniciando…**\n\n{ico} _{pending['name']}_\n⏳",
            buttons=cancel_btn(uid), parse_mode="md",
        )
        st.card_msg = card_msg

    task = asyncio.create_task(
        _dl_task_dz(uid, modo, bitrate, pending, card_msg)
    )
    _dl_tasks[uid] = task

@bot.on(events.CallbackQuery(pattern=rb"dl:cancel:(\d+)"))
async def h_dl_cancel(event):
    uid  = int(event.pattern_match.group(1))
    if event.sender_id != uid:
        return await event.answer("❌ Não é seu menu!", alert=True)
    task = _dl_tasks.get(uid)
    if task and not task.done():
        _cancel_flags[uid] = True
        task.cancel()
        await event.answer("❌ Cancelando…")
    else:
        await event.answer("Nenhum download ativo.", alert=True)

# ─── Artistas / Álbuns / Playlists ────────────────────────────
def _pager_artist_albums(aid, name):
    return DeezerPager(f"💿 Álbuns de **{name}**",
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

@bot.on(events.CallbackQuery(pattern=rb"ar:(al|top):(\d+)"))
async def h_artist_nav(event):
    if not await _gate(event):
        return
    await event.answer()
    uid    = event.sender_id
    st     = nav(uid)
    action = event.pattern_match.group(1).decode()
    aid    = event.pattern_match.group(2).decode()
    msg    = await bot.send_message(uid, "⏳ Carregando…")
    loop   = asyncio.get_event_loop()
    try:
        artist = await loop.run_in_executor(
            _executor, lambda: _api(f"artist/{aid}"))
        name = artist.get("name", "?")
        pg   = (_pager_artist_albums(aid, name)
                if action == "al" else _pager_artist_top(aid, name))
        await pg.get_page(0)
        if pg.total == 0:
            return await msg.edit("😔 Nenhum item.",
                buttons=[[Button.inline("🏠 Menu", b"mn")]])
        st.push(pg)
        btns = await pager_btns(uid)
        await msg.edit(pg.title, buttons=btns, parse_mode="md")
    except Exception as e:
        await msg.edit(friendly_error(e, f"artist {action} {aid}"),
            buttons=[[Button.inline("🏠 Menu", b"mn")]], parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"al:tracks:(\d+)"))
async def h_album_tracks(event):
    if not await _gate(event):
        return
    await event.answer()
    uid  = event.sender_id
    st   = nav(uid)
    aid  = event.pattern_match.group(1).decode()
    msg  = await bot.send_message(uid, "⏳ Carregando faixas…")
    loop = asyncio.get_event_loop()
    try:
        a  = await loop.run_in_executor(
            _executor, lambda: _api(f"album/{aid}"))
        pg = _pager_album_tracks(aid, a.get("title", "?"))
        await pg.get_page(0)
        st.push(pg)
        btns = await pager_btns(uid)
        await msg.edit(pg.title, buttons=btns, parse_mode="md")
    except Exception as e:
        await msg.edit(friendly_error(e, f"album tracks {aid}"),
            buttons=[[Button.inline("🏠 Menu", b"mn")]], parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"pl:tracks:(\d+)"))
async def h_pl_tracks(event):
    if not await _gate(event):
        return
    await event.answer()
    uid  = event.sender_id
    st   = nav(uid)
    plid = event.pattern_match.group(1).decode()
    msg  = await bot.send_message(uid, "⏳ Carregando faixas…")
    loop = asyncio.get_event_loop()
    try:
        p  = await loop.run_in_executor(
            _executor, lambda: _api(f"playlist/{plid}"))
        pg = _pager_pl_tracks(plid, p.get("title", "?"))
        await pg.get_page(0)
        st.push(pg)
        btns = await pager_btns(uid)
        await msg.edit(pg.title, buttons=btns, parse_mode="md")
    except Exception as e:
        await msg.edit(friendly_error(e, f"pl tracks {plid}"),
            buttons=[[Button.inline("🏠 Menu", b"mn")]], parse_mode="md")

# ─── Admin / Owner ────────────────────────────────────────────
def _owner(fn):
    async def w(event):
        if event.sender_id != OWNER_ID:
            return await event.answer("⛔ Acesso restrito.", alert=True)
        await fn(event)
    w.__name__ = fn.__name__
    return w

@bot.on(events.CallbackQuery(data=b"ow:panel"))
@_owner
async def h_ow_panel(event):
    await event.answer()
    await event.edit(
        f"⚙️ **Pool Deezer**\n\n{pool.status()}\n\n"
        f"👥 ARLs pessoais: {user_arl.count()}",
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
        return await event.edit("⚠️ Mínimo 1 ARL ativa.",
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
        f"🟢 Pool Deezer     : {pool.count()}\n"
        f"🟢 ARLs pessoais   : {user_arl.count()}\n"
        f"💎 Premiums detect.: {sum(1 for u in user_arl._c if user_arl.is_premium(u))}\n"
        f"🎼 FLAC liberados  : {len(flac_wl.list())}\n"
        f"👥 Usuários reg.   : {users_reg.count()}\n"
        f"⬇️ Downloads ativos: {len(_dl_tasks)}\n"
        f"🚫 Bloqueados      : {len(rate.blocked_list())}\n"
        f"⚙️ Workers DL/UP   : {MAX_GLOBAL_DL}/{MAX_SEND_PARA}",
        buttons=owner_panel_btns(), parse_mode="md")

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
    rows = []
    text = f"🔓 **{len(blocked)} usuário(s):**\n\n"
    for uid_, rem in blocked:
        text += f"• `{uid_}` — {rem}s\n"
        rows.append([Button.inline(f"🔓 {uid_}", f"ow:unban:{uid_}".encode())])
    rows += [[Button.inline("🔓 Liberar TODOS", b"ow:unlimit_all")],
             [Button.inline("◀️ Voltar",         b"ow:panel")]]
    await event.edit(text, buttons=rows, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"ow:unban:(\d+)"))
@_owner
async def h_ow_unban(event):
    uid_ = int(event.pattern_match.group(1))
    rate.unblock(uid_)
    spam.clear(uid_)
    await event.answer(f"✅ {uid_} liberado!", alert=True)
    await h_ow_unlimit(event)

@bot.on(events.CallbackQuery(data=b"ow:unlimit_all"))
@_owner
async def h_ow_unlimit_all(event):
    rate.unblock_all()
    spam.clear_all()
    await event.answer("✅ Todos liberados!", alert=True)
    await event.edit("✅ Todas as restrições removidas.",
        buttons=[[Button.inline("◀️ Voltar", b"ow:panel")]])

# ─── Painel: Qualidade por Usuário ────────────────────────────
QUALITY_LABELS = {
    "9": "🎵 FLAC (máximo)",
    "3": "🎵 MP3 320 kbps",
    "1": "🎵 MP3 128 kbps",
}

@bot.on(events.CallbackQuery(data=b"ow:quality"))
@_owner
async def h_ow_quality(event):
    await event.answer()
    qmap = admin_cfg.list_user_qualities()
    if qmap:
        lines = ["🎚 **Qualidade por Usuário**\n"]
        for uid_s, q in qmap.items():
            lines.append(f"• `{uid_s}` → {QUALITY_LABELS.get(q, q)}")
        text = "\n".join(lines)
    else:
        text = "🎚 **Qualidade por Usuário**\n\nNenhuma restrição definida."
    await event.edit(text, parse_mode="md", buttons=[
        [Button.inline("➕ Definir qualidade",  b"ow:quality:set")],
        [Button.inline("🗑 Remover restrição",  b"ow:quality:del")],
        [Button.inline("◀️ Voltar",             b"ow:panel")],
    ])

@bot.on(events.CallbackQuery(data=b"ow:quality:set"))
@_owner
async def h_ow_quality_set(event):
    await event.answer()
    nav(event.sender_id).step = "wait_quality_uid"
    await event.edit(
        "🎚 **Definir Qualidade**\n\nEnvie o **ID do usuário**:",
        buttons=[[Button.inline("❌ Cancelar", b"ow:quality")]], parse_mode="md")

@bot.on(events.CallbackQuery(data=b"ow:quality:del"))
@_owner
async def h_ow_quality_del(event):
    await event.answer()
    nav(event.sender_id).step = "wait_quality_del_uid"
    await event.edit(
        "🗑 **Remover Restrição**\n\nEnvie o **ID do usuário**:",
        buttons=[[Button.inline("❌ Cancelar", b"ow:quality")]], parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"ow:quality:pick:(\d+):([913])"))
@_owner
async def h_ow_quality_pick(event):
    await event.answer()
    target_uid = int(event.pattern_match.group(1))
    bitrate    = event.pattern_match.group(2).decode()
    admin_cfg.set_user_quality(target_uid, bitrate)
    await event.edit(
        f"✅ Qualidade de `{target_uid}` definida como **{QUALITY_LABELS[bitrate]}**",
        buttons=[[Button.inline("◀️ Qualidade", b"ow:quality"),
                  Button.inline("🏠 Menu",      b"mn")]], parse_mode="md")

# ─── Painel: Visibilidade de info ARL ─────────────────────────
@bot.on(events.CallbackQuery(data=b"ow:arlvis"))
@_owner
async def h_ow_arlvis(event):
    await event.answer()
    nav(event.sender_id).step = "wait_arlvis_uid"
    await event.edit(
        "👁 **Visibilidade de Info ARL**\n\nEnvie o **ID do usuário** para alternar:",
        buttons=[[Button.inline("❌ Cancelar", b"ow:panel")]], parse_mode="md")

# ─── Minha ARL ────────────────────────────────────────────────
@bot.on(events.CallbackQuery(data=b"my_arl"))
async def h_my_arl(event):
    await event.answer()
    uid = event.sender_id
    d   = user_arl.get(uid)
    show_info = admin_cfg.arl_info_visible(uid) or uid == OWNER_ID
    if d:
        if show_info:
            text = (f"🔑 **Sua ARL Deezer**\n\n"
                    f"👤 {d.get('name','—')} | 🌍 {d.get('country','—')}\n"
                    f"🎵 Plano : {d.get('plan','—')}\n"
                    f"📅 Adicio.: {d.get('added_at','—')[:10]}")
        else:
            text = "🔑 **Sua ARL Deezer**\n\n✅ ARL configurada e ativa."
        btns = [[Button.inline("🔄 Atualizar", b"arl:set")],
                [Button.inline("🗑 Remover",   b"arl:del")],
                [Button.inline("🏠 Menu",      b"mn")]]
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
    try:
        await event.edit(text, buttons=btns, parse_mode="md")
    except Exception:
        await bot.send_message(uid, text, buttons=btns, parse_mode="md")

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
# OWNER — FLAC Whitelist  (DM-only)
# ═══════════════════════════════════════════════════════════════
def _is_owner(event) -> bool:
    return event.sender_id == OWNER_ID

def _flac_panel_text() -> str:
    lst = flac_wl.list()
    if not lst:
        return ("🎼 **FLAC — Whitelist**\n\n"
                "_Nenhum usuário liberado para FLAC._\n\n"
                "👤 Apenas usuários nesta lista podem baixar em FLAC.\n"
                "Demais usuários podem baixar em MP3 320 (com ARL premium "
                "própria) ou MP3 128 (todos).")
    lines = ["🎼 **FLAC — Whitelist**\n",
             f"👥 {len(lst)} usuário(s) liberado(s):\n"]
    for u in lst:
        info = users_reg.get_all().get(str(u), {})
        nick = info.get("username") or info.get("first_name") or "—"
        lines.append(f"• `{u}` — {nick}")
    return "\n".join(lines)

def _flac_panel_btns() -> list:
    return [
        [Button.inline("➕ Liberar usuário", b"ow:flac:add"),
         Button.inline("➖ Remover usuário", b"ow:flac:rm")],
        [Button.inline("🔄 Atualizar", b"ow:flac"),
         Button.inline("🏠 Menu",      b"mn")],
    ]

@bot.on(events.CallbackQuery(data=b"ow:flac"))
async def h_ow_flac(event):
    if not _is_owner(event):
        return await event.answer("🔒", alert=True)
    await event.answer()
    try:
        await event.edit(_flac_panel_text(),
                         buttons=_flac_panel_btns(), parse_mode="md")
    except Exception:
        await bot.send_message(event.sender_id, _flac_panel_text(),
                               buttons=_flac_panel_btns(), parse_mode="md")

@bot.on(events.CallbackQuery(data=b"ow:flac:add"))
async def h_ow_flac_add(event):
    if not _is_owner(event):
        return await event.answer("🔒", alert=True)
    await event.answer()
    nav(event.sender_id).step = "wait_flac_add"
    await event.edit(
        "🎼 **Liberar FLAC**\n\n"
        "Envie o **ID do usuário** (ou @username, ou encaminhe uma "
        "mensagem dele):",
        buttons=[[Button.inline("❌ Cancelar", b"ow:flac")]],
        parse_mode="md")

@bot.on(events.CallbackQuery(data=b"ow:flac:rm"))
async def h_ow_flac_rm(event):
    if not _is_owner(event):
        return await event.answer("🔒", alert=True)
    await event.answer()
    nav(event.sender_id).step = "wait_flac_rm"
    await event.edit(
        "🎼 **Remover FLAC**\n\nEnvie o **ID do usuário** a remover:",
        buttons=[[Button.inline("❌ Cancelar", b"ow:flac")]],
        parse_mode="md")


# ─── Mensagens de texto / links ───────────────────────────────
@bot.on(events.NewMessage())
async def h_text(event):
    if not event.text or event.text.startswith("/"):
        return
    uid  = event.sender_id
    if not await _gate(event, is_cb=False):
        return
    text = event.text.strip()
    st   = nav(uid)
    await _register_user(event)

    # ARL pessoal
    if st.step == "wait_arl":
        msg  = await event.respond("🔍 Verificando ARL…")
        info = await asyncio.get_event_loop().run_in_executor(
            _executor, UserARLManager.validate_arl, text)
        if info is None:
            return await msg.edit(
                "❌ **ARL inválida ou expirada.**",
                buttons=[[Button.inline("❌ Cancelar", b"my_arl")]],
                parse_mode="md")
        await user_arl.save(uid, text, name=info.get("name", ""),
                             country=info.get("country", ""),
                             plan=info.get("plan", ""))
        st.step = "idle"
        return await msg.edit(
            f"✅ **ARL configurada!**\n\n"
            f"👤 {info.get('name','—')} | 🌍 {info.get('country','—')}\n"
            f"🎵 Plano: {info.get('plan','—')}",
            buttons=[[Button.inline("🏠 Menu", b"mn")]],
            parse_mode="md")

    # ARL admin
    if st.step == "wait_arl_add" and uid == OWNER_ID:
        msg = await event.respond("🔍 Validando ARL…")
        if len(text) < 100 or not re.match(r"^[a-f0-9]+$", text):
            return await msg.edit("❌ Token inválido.",
                buttons=[[Button.inline("◀️", b"ow:panel")]])
        if text in pool.arls():
            return await msg.edit("⚠️ ARL já existe.",
                buttons=[[Button.inline("◀️", b"ow:panel")]])
        ok = await asyncio.get_event_loop().run_in_executor(
            _executor, pool.add, text)
        if ok:
            _write_arls(pool.arls())
            st.step = "idle"
            return await msg.edit(
                f"✅ ARL adicionada!\n\n{pool.status()}",
                buttons=owner_panel_btns(), parse_mode="md")
        return await msg.edit("❌ ARL expirada.",
            buttons=[[Button.inline("◀️", b"ow:panel")]])

    # ── Passos do painel admin ────────────────────────────────
    if uid == OWNER_ID:

        # Definir qualidade: aguarda ID do usuário
        if st.step == "wait_quality_uid":
            try:
                target = int(text.strip())
            except ValueError:
                return await event.respond("❌ ID inválido. Envie apenas o número.",
                    buttons=[[Button.inline("❌ Cancelar", b"ow:quality")]])
            st.pending["quality_target"] = target
            st.step = "wait_quality_pick"
            return await event.respond(
                f"🎚 Escolha a qualidade para `{target}`:",
                parse_mode="md", buttons=[
                    [Button.inline("🎵 FLAC",     f"ow:quality:pick:{target}:9".encode())],
                    [Button.inline("🎵 MP3 320",  f"ow:quality:pick:{target}:3".encode())],
                    [Button.inline("🎵 MP3 128",  f"ow:quality:pick:{target}:1".encode())],
                    [Button.inline("❌ Cancelar", b"ow:quality")],
                ])

        # Remover restrição de qualidade
        if st.step == "wait_quality_del_uid":
            try:
                target = int(text.strip())
            except ValueError:
                return await event.respond("❌ ID inválido.",
                    buttons=[[Button.inline("❌ Cancelar", b"ow:quality")]])
            admin_cfg.set_user_quality(target, None)
            st.step = "idle"
            return await event.respond(
                f"✅ Restrição de qualidade de `{target}` removida.",
                parse_mode="md",
                buttons=[[Button.inline("◀️ Qualidade", b"ow:quality"),
                          Button.inline("🏠 Menu",      b"mn")]])

        # Alternar visibilidade ARL
        if st.step == "wait_arlvis_uid":
            try:
                target = int(text.strip())
            except ValueError:
                return await event.respond("❌ ID inválido.",
                    buttons=[[Button.inline("❌ Cancelar", b"ow:panel")]])
            current = admin_cfg.arl_info_visible(target)
            admin_cfg.set_arl_info_visible(target, not current)
            st.step = "idle"
            novo = "✅ visível" if not current else "🚫 oculto"
            return await event.respond(
                f"👁 Info ARL de `{target}` agora está **{novo}**.",
                parse_mode="md",
                buttons=[[Button.inline("◀️ Painel", b"ow:panel"),
                          Button.inline("🏠 Menu",   b"mn")]])

        # ── FLAC Whitelist ────────────────────────────────────
        def _parse_int(t):
            try:
                return int(t.strip().lstrip("@"))
            except ValueError:
                return None

        async def _resolve_target(t: str) -> int | None:
            t = t.strip()
            n = _parse_int(t)
            if n is not None:
                return n
            # tenta resolver @username
            try:
                ent = await bot.get_entity(t if t.startswith("@") else "@" + t)
                return int(getattr(ent, "id", 0)) or None
            except Exception:
                return None

        if st.step == "wait_flac_add":
            # Se for encaminhada, pega o uid do remetente original
            target = None
            try:
                if event.forward and getattr(event.forward, "sender_id", None):
                    target = int(event.forward.sender_id)
            except Exception:
                pass
            if target is None:
                target = await _resolve_target(text)
            if target is None:
                return await event.respond(
                    "❌ Não consegui identificar o usuário.\n"
                    "Envie ID numérico, @username ou encaminhe uma mensagem dele.",
                    buttons=[[Button.inline("❌ Cancelar", b"ow:flac")]],
                    parse_mode="md")
            flac_wl.add(target)
            st.step = "idle"
            return await event.respond(
                f"✅ Usuário `{target}` liberado para baixar em **FLAC**.",
                parse_mode="md",
                buttons=[[Button.inline("🎼 FLAC", b"ow:flac"),
                          Button.inline("🏠 Menu", b"mn")]])

        if st.step == "wait_flac_rm":
            target = await _resolve_target(text)
            if target is None:
                return await event.respond("❌ ID inválido.",
                    buttons=[[Button.inline("❌ Cancelar", b"ow:flac")]])
            ok2 = flac_wl.remove(target)
            st.step = "idle"
            return await event.respond(
                (f"✅ Usuário `{target}` removido da whitelist FLAC."
                 if ok2 else f"ℹ️ `{target}` não estava na whitelist."),
                parse_mode="md",
                buttons=[[Button.inline("🎼 FLAC", b"ow:flac"),
                          Button.inline("🏠 Menu", b"mn")]])


    ok, wait = rate.check(uid)
    if not ok:
        return await event.respond(
            f"⏳ Muitas buscas. Aguarde **{wait}s**.", parse_mode="md")

    # Link Deezer (qualquer formato; playlists são bloqueadas)
    dz_detected = detect_dz_url(text)
    if dz_detected:
        tipo, iid = dz_detected
        if tipo == "__playlist__":
            return await event.respond(
                "🚫 **Links de playlist não são aceitos.**\n\n"
                "Envie um link de **álbum**, **faixa** ou **artista**.",
                parse_mode="md")
        msg = await event.respond("🟢 Link Deezer detectado…")
        asyncio.create_task(_handle_dz_link(msg, uid, tipo, iid))
        return

    # Busca por nome — liberada para todos em DM
    st.query = text
    await event.respond(
        f"🔍 Buscar: **{text}**\n\nEscolha o tipo:",
        buttons=search_type_btns(), parse_mode="md")

async def _handle_dz_link(msg, uid: int, tipo: str, iid: str):
    loop = asyncio.get_event_loop()
    st   = nav(uid)

    # Apaga card anterior
    if st.card_msg:
        try:
            await st.card_msg.delete()
        except Exception:
            pass
        st.card_msg = None

    async def _finish(caption: str, btns: list, cover: bytes | None):
        await msg.delete()
        _chat, _topic = _target_for(uid)
        card = await _send_card(_chat, cover, caption, btns, reply_to=_topic)
        st.card_msg     = card
        st.card_caption = caption
        st.card_btns    = btns
        st.card_cover   = cover

    try:
        if tipo == "track":
            info  = await loop.run_in_executor(
                _executor, lambda: _api(f"track/{iid}"))
            cover = await _fetch_cover(
                (info.get("album") or {}).get("cover_xl"))
            st.pending = {
                "type": "track", "name": info.get("title", "Faixa"),
                "dz_url": dl_dz_url("track", iid),
                "cover_url": (info.get("album") or {}).get("cover_xl"),
                "artist": info.get("artist", {}).get("name", ""),
            }
            await _finish(card_track(info), track_btns(iid), cover)
        elif tipo == "album":
            info  = await loop.run_in_executor(
                _executor, lambda: _api(f"album/{iid}"))
            cover = await _fetch_cover(info.get("cover_xl"))
            st.pending = {
                "type": "album", "name": info.get("title", "Álbum"),
                "dz_url": dl_dz_url("album", iid),
                "cover_url": info.get("cover_xl"),
                "artist": info.get("artist", {}).get("name", ""),
            }
            await _finish(card_album(info), album_btns(iid), cover)
        elif tipo == "playlist":
            info  = await loop.run_in_executor(
                _executor, lambda: _api(f"playlist/{iid}"))
            cover = await _fetch_cover(info.get("picture_xl"))
            st.pending = {
                "type": "playlist", "name": info.get("title", "Playlist"),
                "dz_url": dl_dz_url("playlist", iid),
                "cover_url": info.get("picture_xl"),
                "artist": "",
            }
            await _finish(card_playlist(info), playlist_btns(iid), cover)
        elif tipo == "artist":
            info  = await loop.run_in_executor(
                _executor, lambda: _api(f"artist/{iid}"))
            cover = await _fetch_cover(info.get("picture_xl"))
            await _finish(card_artist(info), artist_btns(iid), cover)
    except Exception as e:
        await msg.edit(friendly_error(e, f"dz link {tipo}/{iid}"),
            buttons=[[Button.inline("🏠", b"mn")]], parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# DOWNLOAD — helpers
# ═══════════════════════════════════════════════════════════════
SETTINGS = loadSettings()
SETTINGS.update({
    "maxBitrate": "1",
    "downloadLocation": str(DOWNLOAD_DIR),
    "createArtistFolder": False, "createAlbumFolder": True,
    "createPlaylistFolder": True, "maxConcurrentDownloads": 1,
    "overwriteFile": "y",
})
for _k, _v in {
    "title": True, "artist": True, "album": True, "cover": True,
    "trackNumber": True, "discNumber": True, "albumArtist": True,
    "genre": True, "year": True, "length": True, "saveID3v1": True,
    "padTracks": True, "illegalCharacterReplacer": "_",
}.items():
    SETTINGS["tags"][_k] = _v

class _Tracker:
    def __init__(self):
        self.downloaded = []
        self.failed = []

    def send(self, k, d=None):
        if isinstance(d, dict) and k == "updateQueue":
            (self.downloaded if d.get("downloaded") else
             self.failed if d.get("failed") else []).append(d)

def _run_dl(dz, obj, s, t):
    try:
        Downloader(dz, obj, s, t).start()
    except TypeError:
        Downloader(dz, obj, s).start()

def _dl_with_dz(url: str, dest: Path, dz: Deezer,
                bitrate: str = "1") -> _Tracker:
    s = dict(SETTINGS)
    s["downloadLocation"] = str(dest)
    s["maxBitrate"] = bitrate
    t   = _Tracker()
    obj = generateDownloadObject(dz, url, s["maxBitrate"])
    if obj is None:
        raise RuntimeError("generateDownloadObject retornou None")
    if isinstance(obj, list):
        if not obj:
            raise RuntimeError("Lista vazia")
        for o in obj:
            _run_dl(dz, o, s, t)
    else:
        _run_dl(dz, obj, s, t)
    time.sleep(1)
    return t

def _choose_dz(uid: int) -> list[Deezer]:
    sessions = []
    p = user_arl.open_session(uid)
    if p:
        sessions.append(p)
    sessions.extend(s["dz"] for s in pool.all())
    return sessions

def _sync_dz_download(url: str, dest: Path, uid: int,
                      bitrate: str = "1") -> _Tracker:
    last_err = None
    for dz in _choose_dz(uid):
        for attempt in range(1, 4):
            try:
                t = _dl_with_dz(url, dest, dz, bitrate)
                # Aceita .mp3 ou .flac
                found = list(dest.rglob("*.mp3")) + list(dest.rglob("*.flac"))
                if found:
                    return t
                raise RuntimeError("Nenhum arquivo de áudio gerado")
            except Exception as e:
                last_err = e
                if any(k in str(e).lower()
                       for k in ("unauthorized", "403", "invalid arl")):
                    break
                time.sleep(4 * attempt)
    raise last_err or RuntimeError("Todas as ARLs falharam")

def _audio_sort_key(f: Path):
    try:
        tags = ID3(str(f))
        t = str(tags.get("TRCK", "0")).split("/")[0].strip()
        d = str(tags.get("TPOS", "1")).split("/")[0].strip()
        return (int(d) if d.isdigit() else 1,
                int(t) if t.isdigit() else 0)
    except Exception:
        return (999, 999)

def find_audio_files(path: Path) -> list[Path]:
    files = list(path.rglob("*.mp3")) + list(path.rglob("*.flac"))
    return sorted(files, key=_audio_sort_key)

def get_audio_meta(f: Path) -> tuple[str, str, int]:
    """Extrai título, artista e duração. Suporta MP3 e FLAC."""
    try:
        sfx = f.suffix.lower()
        if sfx == ".flac":
            from mutagen.flac import FLAC as _FLAC
            audio  = _FLAC(str(f))
            title  = (audio.get("title")  or [f.stem])[0]
            artist = (audio.get("artist") or [""])[0]
            dur    = int(audio.info.length)
        else:                               # .mp3
            tags   = ID3(str(f))
            t_tag  = tags.get("TIT2")
            a_tag  = tags.get("TPE1")
            title  = t_tag.text[0] if (t_tag and t_tag.text) else f.stem
            artist = a_tag.text[0] if (a_tag and a_tag.text) else ""
            dur    = int(MP3(str(f)).info.length)
        return title, artist, dur
    except Exception as ex:
        log.debug(f"get_audio_meta({f.name}): {ex}")
        return f.stem, "", 0


def _embed_cover_ffmpeg(mp3: Path, cover: bytes) -> bool:
    tc = to = None
    try:
        fd, tc = tempfile.mkstemp(suffix=".jpg")
        with os.fdopen(fd, "wb") as f:
            f.write(cover)
        to = mp3.with_suffix(".tmp" + mp3.suffix)
        cmd = [FFMPEG_BIN, "-y", "-i", str(mp3), "-i", tc,
               "-map", "0:a", "-map", "1:0", "-c:a", "copy",
               "-c:v", "mjpeg", "-id3v2_version", "3",
               "-metadata:s:v", "title=Album cover",
               "-metadata:s:v", "comment=Cover (front)", str(to)]
        r = _subprocess.run(cmd, stdout=_subprocess.DEVNULL,
                            stderr=_subprocess.PIPE, timeout=60)
        if r.returncode == 0:
            to.replace(mp3)
            return True
    except Exception:
        pass
    finally:
        for f in (tc, to):
            if f:
                try:
                    Path(str(f)).unlink(missing_ok=True)
                except Exception:
                    pass
    return False

async def _embed_covers_album(files: list[Path], cover: bytes):
    loop = asyncio.get_event_loop()
    await asyncio.gather(
        *[loop.run_in_executor(_executor, _embed_cover_ffmpeg, m, cover)
          for m in files],
        return_exceptions=True)

def make_zip(dest: Path, name: str, files: list[Path]) -> Path:
    zp = dest.parent / f"{safe(name)}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.relative_to(dest))
    return zp

async def _send_audio(uid: int, f: Path,
                      cover: bytes | None, also_ch=False):
    """Envia áudio para o destino do usuário (chat+tópico)."""
    title, art, dur = get_audio_meta(f)
    attrs = [DocumentAttributeAudio(
        duration=dur, title=title, performer=art, voice=False)]
    chat, topic = _target_for(uid)
    extra: dict = {}
    if topic:
        extra["reply_to"] = topic
    async def _sf(c, **xt):
        await bot.send_file(c, str(f),
                            attributes=attrs, thumb=_thumb(cover), **xt)
    tasks = [_sf(chat, **extra)]
    if also_ch and CHANNEL_ID:
        tasks.append(_sf(CHANNEL_ID))
    await asyncio.gather(*tasks, return_exceptions=True)

# ═══════════════════════════════════════════════════════════════
# TASK PRINCIPAL DE DOWNLOAD
# ═══════════════════════════════════════════════════════════════
_global_dl = asyncio.Semaphore(MAX_GLOBAL_DL)

async def _dl_task_dz(uid: int, modo: str, bitrate: str,
                      pending: dict, card_msg):
    """
    Download principal.
    Modo individual (f): busca a lista de faixas da API,
    baixa e envia CADA faixa na ordem certa sem esperar as demais.
    Modo ZIP (z): baixa tudo, compacta, envia.
    """
    async with dl_lock(uid):
        async with _global_dl:
            nome     = pending["name"]
            tipo     = pending["type"]
            dz_url   = pending["dz_url"]
            iid      = dz_url.split("/")[-1]
            tipo_s   = {"album": "al", "playlist": "pl", "track": "tr"}.get(tipo, "tr")
            st       = nav(uid)
            orig_cap = st.card_caption
            qual_lbl = QUALITY_MAP.get(bitrate, ("?", "?"))[1]

            dest = DOWNLOAD_DIR / f"{uid}_{int(time.time())}"
            dest.mkdir(parents=True, exist_ok=True)

            async def _upd(status: str, btns=None):
                await _edit_card(card_msg,
                                 f"{orig_cap}\n\n{status}",
                                 btns or cancel_btn(uid))

            total = 0

            try:
                cover = await _fetch_cover(pending.get("cover_url"))
                loop  = asyncio.get_event_loop()

                await _upd(f"📥 **Iniciando…**\n🎧 {qual_lbl}")

                # ── Faixa única ──────────────────────────────────────────
                if tipo == "track":
                    await _upd(f"📥 **Baixando…**\n🎧 {qual_lbl}")
                    await loop.run_in_executor(
                        _executor, _sync_dz_download, dz_url, dest, uid, bitrate)

                    files = find_audio_files(dest)
                    if not files:
                        raise RuntimeError("Nenhum arquivo de áudio gerado")

                    f = files[0]
                    if cover and f.suffix.lower() == ".mp3":
                        await loop.run_in_executor(
                            _executor, _embed_cover_ffmpeg, f, cover)

                    await _upd(f"📤 **Enviando…**\n🎧 {qual_lbl}")
                    await _send_audio(uid, f, cover, also_ch=True)
                    total = 1

                # ── Álbum / Playlist ─────────────────────────────────────
                else:
                    # Obtém lista de faixas na ordem correta da API
                    await _upd(f"📋 **Obtendo lista de faixas…**\n🎧 {qual_lbl}")
                    ep     = (f"album/{iid}/tracks"
                              if tipo == "album"
                              else f"playlist/{iid}/tracks")
                    resp   = await loop.run_in_executor(_executor, lambda: _api(ep))
                    tracks = resp.get("data", [])
                    total  = len(tracks)
                    if total == 0:
                        raise RuntimeError("Nenhuma faixa encontrada na lista")

                    # ── ZIP ──────────────────────────────────────────────
                    if modo == "z":
                        await _upd(
                            f"📥 **Baixando…**\n"
                            f"🎧 {qual_lbl} — {total} faixa(s)")
                        await loop.run_in_executor(
                            _executor, _sync_dz_download,
                            dz_url, dest, uid, bitrate)

                        audio_files = find_audio_files(dest)
                        if not audio_files:
                            raise RuntimeError("Nenhum arquivo de áudio")

                        if cover:
                            await _upd(f"🎨 **Incorporando capas…**\n🎧 {qual_lbl}")
                            await _embed_covers_album(audio_files, cover)

                        await _upd(
                            f"🗜️ **Compactando {len(audio_files)} faixas…**\n"
                            f"🎧 {qual_lbl}")
                        zp = await loop.run_in_executor(
                            _executor, make_zip, dest, nome, audio_files)

                        await _upd(f"📤 **Enviando ZIP…**\n🎧 {qual_lbl}")
                        await bot.send_file(uid, str(zp))
                        if CHANNEL_ID:
                            try:
                                await bot.send_file(CHANNEL_ID, str(zp))
                            except Exception:
                                pass
                        total = len(audio_files)

                    # ── Arquivos individuais: streaming faixa a faixa ────
                    else:
                        sent = 0
                        for i, track in enumerate(tracks, 1):
                            if _cancel_flags.get(uid):
                                raise asyncio.CancelledError()

                            tid = track.get("id")
                            if not tid:
                                continue

                            t_title = track.get("title", f"Faixa {i}")
                            t_url   = dl_dz_url("track", tid)
                            # ✅ Corrigido: usa a pasta dest diretamente
                            # O deemix já nomeia os arquivos corretamente
                            # sem criar subpastas por faixa
                            t_dir   = dest

                            # 1) Baixa a faixa
                            await _upd(
                                f"📥 **Baixando {i}/{total}…**\n"
                                f"🎵 {t_title[:40]}\n"
                                f"🎧 {qual_lbl}")

                            try:
                                await loop.run_in_executor(
                                    _executor, _sync_dz_download,
                                    t_url, t_dir, uid, bitrate)

                                # Pega somente o arquivo mais recente
                                # (recém-baixado) para enviar
                                all_files = find_audio_files(t_dir)
                                # Ordena por tempo de modificação desc
                                all_files_ts = sorted(
                                    all_files,
                                    key=lambda p: p.stat().st_mtime,
                                    reverse=True
                                )
                                # Arquivo com nome contendo o tid ou o mais novo
                                f = None
                                for af in all_files_ts:
                                    if str(tid) in af.name or not f:
                                        f = af
                                        break
                                if not f:
                                    log.warning(f"Faixa {i} '{t_title}' sem arquivo — pulando")
                                    continue

                                # 2) Embed capa (só MP3; FLAC já traz embutido)
                                if cover and f.suffix.lower() == ".mp3":
                                    await loop.run_in_executor(
                                        _executor, _embed_cover_ffmpeg, f, cover)

                                # 3) Envia imediatamente
                                await _upd(
                                    f"📤 **Enviando {i}/{total}…**\n"
                                    f"🎵 {t_title[:40]}\n"
                                    f"🎧 {qual_lbl}")

                                await _send_audio(uid, f, cover, also_ch=True)
                                sent += 1

                            except asyncio.CancelledError:
                                raise
                            except Exception as e:
                                log.error(f"Faixa {i} '{t_title}': {e}")

                        total = sent

                users_reg.add_download(uid)

                await _edit_card(
                    card_msg,
                    f"{orig_cap}\n\n"
                    f"✅ **Concluído!**\n"
                    f"🎧 {qual_lbl} — {total} faixa(s)",
                    [[Button.inline("🔄 Baixar novamente",
                                    f"dl:{tipo_s}:{iid}".encode())],
                     [Button.inline("🏠 Menu", b"mn")]])

            except asyncio.CancelledError:
                await _edit_card(
                    card_msg,
                    f"{orig_cap}\n\n❌ **Download cancelado.**",
                    [[Button.inline("🔄 Tentar novamente",
                                    f"dl:{tipo_s}:{iid}".encode())],
                     [Button.inline("🏠 Menu", b"mn")]])

            except Exception as e:
                nav(uid).pending = pending
                err = friendly_error(e, f"dz '{nome}'")
                await _edit_card(
                    card_msg,
                    f"{orig_cap}\n\n{err}",
                    [[Button.inline("🔄 Tentar novamente",
                                    f"dl:{tipo_s}:{iid}".encode())],
                     [Button.inline("🏠 Menu", b"mn")]])

            finally:
                _dl_tasks.pop(uid, None)
                _cancel_flags.pop(uid, None)
                shutil.rmtree(dest, ignore_errors=True)


# ═══════════════════════════════════════════════════════════════
# EXPLORAR
# ═══════════════════════════════════════════════════════════════
EXPLORE_SECTIONS = [
    ("💿 Top Álbuns",  "exp:albums"),
    ("🆕 Lançamentos",    "exp:releases"),
    ("📰 Editorial",   "exp:editorial"),
]
EXPLORE_PAGE_SIZE = 8
_explore_cache: dict[str, tuple[float, list]] = {}
_explore_page:  dict[int, tuple[str, int]]    = {}

_SECTION_META = {
    "tracks":    {"endpoint": "chart/0/tracks",    "tipo": "track",
                  "titulo": "🔥 **Top Músicas**"},
    "albums":    {"endpoint": "chart/0/albums",    "tipo": "album",
                  "titulo": "💿 **Top Álbuns**"},
    "artists":   {"endpoint": "chart/0/artists",   "tipo": "artist",
                  "titulo": "👤 **Top Artistas**"},
    "playlists": {"endpoint": "chart/0/playlists", "tipo": "playlist",
                  "titulo": "📋 **Top Playlists**"},
    "releases":  {"endpoint": "editorial/0/releases", "tipo": "album",
                  "titulo": "🆕 **Lançamentos**"},
    "radios":    {"endpoint": "radio",             "tipo": "radio",
                  "titulo": "📻 **Rádios**"},
    "editorial": {"endpoint": "editorial",         "tipo": "editorial",
                  "titulo": "📰 **Editorial**"},
}

def _explore_menu_btns() -> list:
    rows = [[Button.inline(lbl, data.encode())]
            for lbl, data in EXPLORE_SECTIONS]
    rows.append([Button.inline("🏠 Menu", b"mn")])
    return rows

def _explore_page_btns(section: str, page: int,
                       items: list, tipo: str) -> list:
    total_pages = max(1, math.ceil(len(items) / EXPLORE_PAGE_SIZE))
    start = page * EXPLORE_PAGE_SIZE
    end   = min(start + EXPLORE_PAGE_SIZE, len(items))
    rows  = []
    for item in items[start:end]:
        if tipo == "track":
            name = f"🎵 {item.get('title','?')[:30]} — {item.get('artist',{}).get('name','?')[:15]}"
            cb   = f"sel:tr:{item['id']}".encode()
        elif tipo == "album":
            name = f"💿 {item.get('title','?')[:30]} — {item.get('artist',{}).get('name','?')[:15]}"
            cb   = f"sel:al:{item['id']}".encode()
        elif tipo == "artist":
            name = f"👤 {item.get('name','?')[:40]}"
            cb   = f"sel:ar:{item['id']}".encode()
        elif tipo == "playlist":
            name = f"📋 {item.get('title','?')[:40]}"
            cb   = f"sel:pl:{item['id']}".encode()
        elif tipo == "radio":
            name = f"📻 {item.get('title','?')[:40]}"
            cb   = f"exprad:{item['id']}".encode()
        elif tipo == "editorial":
            name = f"📰 {item.get('title', item.get('name','?'))[:40]}"
            cb   = f"expedit:{item['id']}".encode()
        else:
            name = str(item.get("title", item.get("name", "?")))[:40]
            cb   = b"noop"
        rows.append([Button.inline(name, cb)])
    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀️", f"exppg:{section}:{page-1}".encode()))
    nav_row.append(Button.inline(f"📄 {page+1}/{total_pages}", b"noop"))
    if page + 1 < total_pages:
        nav_row.append(Button.inline("▶️", f"exppg:{section}:{page+1}".encode()))
    rows.append(nav_row)
    rows.append([Button.inline("◀️ Explorar", b"explore"),
                 Button.inline("🏠 Menu",      b"mn")])
    return rows

async def _get_explore_data(section: str) -> tuple[list, str, str]:
    now = time.time()
    if section in _explore_cache:
        ts, cached = _explore_cache[section]
        if now - ts < 1800:
            meta = _SECTION_META[section]
            return cached, meta["tipo"], meta["titulo"]
    meta = _SECTION_META[section]
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(
        _executor, lambda: _api(meta["endpoint"]))
    items = (data.get("data", []) if isinstance(data, dict)
             else data if isinstance(data, list) else [])
    _explore_cache[section] = (now, items)
    return items, meta["tipo"], meta["titulo"]

@bot.on(events.CallbackQuery(data=b"explore"))
async def h_explore(event):
    if not await _gate(event):
        return
    await event.answer()
    try:
        await event.edit("🌐 **Explorar**\n\nEscolha uma seção:",
            buttons=_explore_menu_btns(), parse_mode="md")
    except Exception:
        await bot.send_message(event.sender_id,
            "🌐 **Explorar**\n\nEscolha uma seção:",
            buttons=_explore_menu_btns(), parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"exp:(\w+)"))
async def h_explore_section(event):
    if not await _gate(event):
        return
    await event.answer()
    uid     = event.sender_id
    section = event.pattern_match.group(1).decode()
    if section not in _SECTION_META:
        return await event.edit("❌ Seção inválida.",
            buttons=[[Button.inline("◀️ Explorar", b"explore")]],
            parse_mode="md")
    await event.edit("🔍 Carregando…", parse_mode="md")
    try:
        items, tipo, titulo = await _get_explore_data(section)
    except Exception as e:
        return await event.edit(friendly_error(e, f"explore {section}"),
            buttons=[[Button.inline("◀️ Explorar", b"explore"),
                      Button.inline("🏠 Menu",      b"mn")]],
            parse_mode="md")
    if not items:
        return await event.edit("😔 Nenhum resultado encontrado.",
            buttons=[[Button.inline("◀️ Explorar", b"explore"),
                      Button.inline("🏠 Menu",      b"mn")]],
            parse_mode="md")
    _explore_page[uid] = (section, 0)
    nav(uid).explore_history.append(("explore_menu", 0))
    btns = _explore_page_btns(section, 0, items, tipo)
    try:
        await event.edit(titulo + "\n\nEscolha um item:",
            buttons=btns, parse_mode="md")
    except Exception:
        await bot.send_message(uid, titulo + "\n\nEscolha um item:",
            buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"exppg:(\w+):(\d+)"))
async def h_explore_page(event):
    if not await _gate(event):
        return
    await event.answer()
    uid     = event.sender_id
    section = event.pattern_match.group(1).decode()
    page    = int(event.pattern_match.group(2))
    if section not in _SECTION_META:
        return
    _explore_page[uid] = (section, page)
    try:
        items, tipo, titulo = await _get_explore_data(section)
    except Exception as e:
        return await event.edit(friendly_error(e, "explore page"),
            buttons=[[Button.inline("◀️ Explorar", b"explore"),
                      Button.inline("🏠 Menu",      b"mn")]],
            parse_mode="md")
    btns = _explore_page_btns(section, page, items, tipo)
    try:
        await event.edit(titulo + "\n\nEscolha um item:",
            buttons=btns, parse_mode="md")
    except Exception:
        pass

@bot.on(events.CallbackQuery(pattern=rb"exprad:(\d+)"))
async def h_explore_radio(event):
    if not await _gate(event):
        return
    await event.answer()
    uid = event.sender_id
    rid = event.pattern_match.group(1).decode()
    await event.edit("🔍 Carregando faixas da rádio…")
    pg = DeezerPager("📻 **Rádio** — Faixas",
                     f"{DZ}/radio/{rid}/tracks", {}, "track")
    try:
        await pg.get_page(0)
    except Exception as e:
        return await event.edit(friendly_error(e, f"radio {rid}"),
            buttons=[[Button.inline("◀️ Explorar", b"explore"),
                      Button.inline("🏠 Menu",      b"mn")]],
            parse_mode="md")
    if pg.total == 0:
        return await event.edit("😔 Nenhuma faixa encontrada.",
            buttons=[[Button.inline("◀️ Explorar", b"explore"),
                      Button.inline("🏠 Menu",      b"mn")]],
            parse_mode="md")
    st = nav(uid)
    st.stack.clear()
    st.push(pg)
    btns = await pager_btns(uid)
    try:
        await event.edit(pg.title, buttons=btns, parse_mode="md")
    except Exception:
        await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

@bot.on(events.CallbackQuery(pattern=rb"expedit:(\d+)"))
async def h_explore_editorial(event):
    if not await _gate(event):
        return
    await event.answer()
    uid = event.sender_id
    eid = event.pattern_match.group(1).decode()
    st  = nav(uid)
    if uid in _explore_page:
        st.explore_history.append(_explore_page[uid])
    await event.edit("🔍 Carregando editorial…")
    pg = DeezerPager("📰 **Editorial** — Seleção",
                     f"{DZ}/editorial/{eid}/releases", {}, "album")
    try:
        await pg.get_page(0)
    except Exception:
        pg = DeezerPager("📰 **Editorial** — Seleção",
                         f"{DZ}/editorial/{eid}/charts", {}, "album")
        try:
            await pg.get_page(0)
        except Exception as e:
            return await event.edit(friendly_error(e, f"editorial {eid}"),
                buttons=[[Button.inline("◀️ Explorar", b"explore"),
                          Button.inline("🏠 Menu",      b"mn")]],
                parse_mode="md")
    if pg.total == 0:
        return await event.edit("😔 Nenhum conteúdo encontrado.",
            buttons=[[Button.inline("◀️ Explorar", b"explore"),
                      Button.inline("🏠 Menu",      b"mn")]],
            parse_mode="md")
    st.stack.clear()
    st.push(pg)
    btns = await pager_btns(uid)
    try:
        await event.edit(pg.title, buttons=btns, parse_mode="md")
    except Exception:
        await bot.send_message(uid, pg.title, buttons=btns, parse_mode="md")

# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════
async def main():
    await bot.start(bot_token=BOT_TOKEN)
    log.info(
        f"\n{'═'*52}\n"
        f"  🎵 Deezer Bot — v13 DM-only PRO (Silva Edition)\n"
        f"  💬 Modo: APENAS DMs (sem grupos)\n"
        f"  🎶 Todos: MP3 128 | 💎 Premium: + MP3 320 | 🎼 FLAC: whitelist\n"
        f"  🟢 Pool Deezer   : {pool.count()} sessão(ões)\n"
        f"  🟢 ARLs pessoais : {user_arl.count()}\n"
        f"  🎼 FLAC liberados: {len(flac_wl.list())}\n"
        f"  👥 Usuários reg. : {users_reg.count()}\n"
        f"  ⚙️ Workers DL/UP : {MAX_GLOBAL_DL}/{MAX_SEND_PARA}\n"
        f"{'═'*52}"
    )
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
