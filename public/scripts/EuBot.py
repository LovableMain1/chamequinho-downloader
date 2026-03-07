#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SILVA IPTV PANEL MANAGER v6.0 PRO
Bot Telegram profissional para gerenciamento de painel IPTV/P2P
Owner: Edivaldo Silva | @Edkd1 | ID: 2061557102
"""

from telethon import TelegramClient, events, Button
import requests
from bs4 import BeautifulSoup
import math
import time
import re
from urllib.parse import urljoin

# ══════════════════════════════════════════════
# CONFIGURACAO
# ══════════════════════════════════════════════

API_ID = 29214781
API_HASH = "9fc77b4f32302f4d4081a4839cc7ae1f"
BOT_TOKEN = "8618840827:AAEQx9qnUiDpjqzlMAoyjIxxGXbM_I71wQw"

PAINEL_URL = "https://vendedorp2p.com"
PAGE_SIZE = 10
SESSION_TIMEOUT = 3600
CACHE_TTL = 60

OWNER_NAME = "Edivaldo Silva"
OWNER_ID = 2061557102
OWNER_USERNAME = "@Edkd1"
BOT_VERSION = "6.0 PRO"

E = {
    "ok": "✅", "err": "❌", "warn": "⚠️", "load": "⏳",
    "user": "👤", "pass": "🔑", "credit": "💰",
    "tv": "📺", "p2p": "🔗", "rev": "👥", "online": "🟢",
    "offline": "🔴", "search": "🔎", "fast": "⚡", "create": "➕",
    "test": "🧪", "log": "📜", "tool": "⚙️", "exit": "🚪",
    "dash": "📊", "back": "🔙", "left": "⬅️", "right": "➡️",
    "conn": "🌐", "cancel": "❎", "edit": "✏️", "del": "🗑️",
    "lock": "🔐", "info": "ℹ️", "time": "🕐",
    "device": "📱", "ip": "🌍", "refresh": "🔄",
    "star": "⭐", "link": "🔗", "dns": "🌐", "port": "🚪",
    "crown": "👑", "bolt": "⚡", "fire": "🔥", "rocket": "🚀",
    "check": "☑️", "copy": "📋", "key": "🗝️",
}

LINE = "━" * 32
THIN = "─" * 30


# ══════════════════════════════════════════════
# SESSION MANAGER
# ══════════════════════════════════════════════

class SessionManager:
    def __init__(self):
        self._sessions = {}
        self._states = {}
        self._cache = {}
        self._pagination = {}

    def get_session(self, uid):
        entry = self._sessions.get(uid)
        if not entry:
            return None
        if time.time() - entry["login_time"] > SESSION_TIMEOUT:
            self.logout(uid)
            return None
        return entry["session"]

    def get_username(self, uid):
        entry = self._sessions.get(uid)
        return entry["username"] if entry else "Conta"

    def set_session(self, uid, session, username):
        self._sessions[uid] = {"session": session, "username": username, "login_time": time.time()}

    def logout(self, uid):
        for store in (self._sessions, self._states, self._cache, self._pagination):
            store.pop(uid, None)

    def set_state(self, uid, step, data=None):
        self._states[uid] = {"step": step, "data": data or {}}

    def get_state(self, uid):
        return self._states.get(uid)

    def clear_state(self, uid):
        self._states.pop(uid, None)

    def get_cache(self, uid, key):
        entry = self._cache.get(uid, {}).get(key)
        if entry and time.time() - entry["time"] < CACHE_TTL:
            return entry["data"]
        return None

    def set_cache(self, uid, key, data):
        self._cache.setdefault(uid, {})[key] = {"data": data, "time": time.time()}

    def clear_cache(self, uid):
        self._cache.pop(uid, None)

    def set_page_data(self, uid, items, list_type):
        self._pagination[uid] = {"items": items, "type": list_type}

    def get_page_data(self, uid):
        return self._pagination.get(uid)


sm = SessionManager()


# ══════════════════════════════════════════════
# API DO PAINEL
# ══════════════════════════════════════════════

class API:
    @staticmethod
    def _url(path):
        return urljoin(PAINEL_URL, path)

    @staticmethod
    def _csrf(session, url):
        try:
            soup = BeautifulSoup(session.get(url, timeout=10).text, "html.parser")
            tag = soup.find("input", {"name": "csrf_token"})
            return tag["value"] if tag else ""
        except Exception:
            return ""

    @staticmethod
    def _parse_response(html_text):
        """Extrai dados da resposta HTML do painel."""
        info = {}
        try:
            soup = BeautifulSoup(html_text, "html.parser")

            # Alertas de sucesso
            for cls in ["alert-success", "alert", "success", "result"]:
                div = soup.find("div", class_=re.compile(cls, re.I))
                if div:
                    info["message"] = div.get_text(strip=True)[:200]
                    break

            # Codigo/textarea
            for tag in soup.find_all(["code", "pre", "textarea"]):
                text = tag.get_text(strip=True)
                if text:
                    info["raw_data"] = text[:500]

            # Inputs com valores
            for inp in soup.find_all("input"):
                name = inp.get("name", inp.get("id", ""))
                val = inp.get("value", "")
                if val and name and name != "csrf_token":
                    info[name] = val

            # URLs de acesso (m3u, player_api, etc)
            url_patterns = re.findall(
                r'(https?://[^\s<>"\']+(?:\.m3u|/get\.php|/player_api\.php|/c/|/live/)[^\s<>"\']*)',
                html_text
            )
            if url_patterns:
                info["urls"] = list(set(url_patterns))

            # DNS/Host/Port
            dns = re.search(r'(?:dns|host|server)[:\s]+([a-zA-Z0-9._-]+\.[a-z]{2,})', html_text, re.I)
            if dns:
                info["dns"] = dns.group(1)
            port = re.search(r'(?:port|porta)[:\s]+(\d{2,5})', html_text, re.I)
            if port:
                info["port"] = port.group(1)

            # Username/Password extraidos
            user = re.search(r'(?:username|user)[:\s]+([^\s<>"\']+)', html_text, re.I)
            if user and "username" not in info:
                info["username"] = user.group(1)
            pw = re.search(r'(?:password|pass|senha)[:\s]+([^\s<>"\']+)', html_text, re.I)
            if pw and "password" not in info:
                info["password"] = pw.group(1)

            # Expiracao
            exp = re.search(r'(?:exp|expir|validade)[:\s]+([\d]{4}-[\d]{2}-[\d]{2})', html_text, re.I)
            if exp:
                info["exp_date"] = exp.group(1)

            # Dados de tabelas
            for table in soup.find_all("table"):
                for row in table.find_all("tr"):
                    cells = row.find_all(["td", "th"])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True).lower()
                        val = cells[1].get_text(strip=True)
                        if val and key:
                            clean = re.sub(r'[^a-z_]', '', key.replace(' ', '_'))
                            if clean and clean not in info:
                                info[clean] = val

        except Exception:
            pass
        return info

    @staticmethod
    def login(username, password):
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 13)"})
        try:
            r = s.get(API._url("/login/"), timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            csrf = soup.find("input", {"name": "csrf_token"})
            if not csrf:
                return None, "CSRF nao encontrado"
            s.post(API._url("/login/"), data={
                "try_login": "1", "csrf_token": csrf["value"],
                "username": username, "password": password
            }, timeout=15)
            dash = s.get(API._url("/dashboard/api?get_info&month=0"), timeout=10)
            if dash.status_code != 200:
                return None, "Credenciais invalidas"
            return s, dash.json()
        except requests.Timeout:
            return None, "Timeout"
        except Exception as e:
            return None, str(e)[:80]

    @staticmethod
    def dashboard(s):
        try:
            return s.get(API._url("/dashboard/api?get_info&month=0"), timeout=10).json()
        except Exception:
            return None

    @staticmethod
    def stats(s):
        try:
            return s.get(API._url("/dashboard/api/?get_stats"), timeout=10).json()
        except Exception:
            return None

    @staticmethod
    def sales(s):
        try:
            return s.get(API._url("/dashboard/api/?get_sales"), timeout=10).json()
        except Exception:
            return None

    @staticmethod
    def credits(s):
        try:
            return s.post(API._url("/api/get_credits/"), timeout=10).json()
        except Exception:
            return None

    @staticmethod
    def iptv_clients(s):
        try:
            return s.get(API._url("/clients/api/?get_clients"), timeout=15).json().get("clients", [])
        except Exception:
            return []

    @staticmethod
    def p2p_clients(s):
        try:
            return s.get(API._url("/p2p/api/?get_clients"), timeout=15).json().get("clients", [])
        except Exception:
            return []

    @staticmethod
    def search(s, q):
        try:
            return s.get(API._url(f"/clients/api/?search_client={q}"), timeout=10).json().get("clients", [])
        except Exception:
            return []

    @staticmethod
    def create_iptv(s, user, pw, bouquet, exp):
        try:
            url = API._url("/clients/create/")
            csrf = API._csrf(s, url)
            r = s.post(url, data={
                "csrf_token": csrf, "username": user, "password": pw,
                "bouquet": bouquet, "exp_date": exp, "create_client": "1"
            }, timeout=15)
            parsed = API._parse_response(r.text)
            parsed["_input_username"] = user
            parsed["_input_password"] = pw
            parsed["_input_bouquet"] = bouquet
            parsed["_input_exp"] = exp
            ok = r.status_code == 200 and "error" not in r.text.lower()[:200]
            return ok, parsed
        except Exception as e:
            return False, {"error": str(e)[:80]}

    @staticmethod
    def create_p2p(s, user, pw, exp):
        try:
            url = API._url("/p2p/create/")
            csrf = API._csrf(s, url)
            r = s.post(url, data={
                "csrf_token": csrf, "username": user, "password": pw,
                "exp_date": exp, "create_client": "1"
            }, timeout=15)
            parsed = API._parse_response(r.text)
            parsed["_input_username"] = user
            parsed["_input_password"] = pw
            parsed["_input_exp"] = exp
            ok = r.status_code == 200 and "error" not in r.text.lower()[:200]
            return ok, parsed
        except Exception as e:
            return False, {"error": str(e)[:80]}

    @staticmethod
    def create_reseller(s, user, pw, creds):
        try:
            url = API._url("/resellers/create/")
            csrf = API._csrf(s, url)
            r = s.post(url, data={
                "csrf_token": csrf, "username": user, "password": pw,
                "credits": creds, "create_reseller": "1"
            }, timeout=15)
            parsed = API._parse_response(r.text)
            parsed["_input_username"] = user
            parsed["_input_password"] = pw
            parsed["_input_credits"] = creds
            ok = r.status_code == 200 and "error" not in r.text.lower()[:200]
            return ok, parsed
        except Exception as e:
            return False, {"error": str(e)[:80]}

    @staticmethod
    def edit_client(s, ctype, cid, data_dict):
        try:
            path = f"/clients/edit/{cid}" if ctype == "iptv" else f"/p2p/edit/{cid}"
            url = API._url(path)
            csrf = API._csrf(s, url)
            data_dict.update({"csrf_token": csrf, "edit_client": "1"})
            return s.post(url, data=data_dict, timeout=10).status_code == 200
        except Exception:
            return False

    @staticmethod
    def delete_client(s, ctype, cid):
        try:
            path = f"/clients/delete/{cid}" if ctype == "iptv" else f"/p2p/delete/{cid}"
            return s.get(API._url(path), timeout=10).status_code == 200
        except Exception:
            return False

    @staticmethod
    def delete_reseller(s, rid):
        try:
            return s.get(API._url(f"/resellers/delete/{rid}"), timeout=10).status_code == 200
        except Exception:
            return False

    @staticmethod
    def resellers(s):
        try:
            return s.get(API._url("/clients/api/?get_allowed_resellers"), timeout=10).json().get("resellers", [])
        except Exception:
            return []

    @staticmethod
    def connections(s):
        try:
            return s.get(API._url("/connections/api/?get_connections"), timeout=10).json().get("connections", [])
        except Exception:
            return []

    @staticmethod
    def fast_message(s, cid):
        try:
            return s.get(API._url(f"/clients/api/?fast_message&client_id={cid}"), timeout=10).status_code == 200
        except Exception:
            return False

    @staticmethod
    def test(s, ttype):
        urls = {
            "iptv1": "/test/fast_client/1", "iptv2": "/test/fast_client/2",
            "p2p1": "/test/fast_p2p/1", "p2p2": "/test/fast_p2p/2",
        }
        labels = {"iptv1": "IPTV 24h", "iptv2": "IPTV 48h", "p2p1": "P2P 24h", "p2p2": "P2P 48h"}
        try:
            r = s.get(API._url(urls[ttype]), timeout=15)
            parsed = API._parse_response(r.text)
            parsed["_test_type"] = labels.get(ttype, ttype)

            # Tentar JSON
            try:
                j = r.json()
                if isinstance(j, dict):
                    for k, v in j.items():
                        if k not in parsed:
                            parsed[k] = v
            except Exception:
                pass

            # Fallback: texto limpo
            if len(parsed) <= 1:
                soup = BeautifulSoup(r.text, "html.parser")
                for tag in soup(["script", "style", "nav", "header", "footer"]):
                    tag.decompose()
                clean = soup.get_text(separator="\n", strip=True)
                lines = [l.strip() for l in clean.split("\n") if l.strip() and len(l.strip()) > 2]
                parsed["_raw_lines"] = lines[:20]

            return parsed
        except Exception as e:
            return {"error": str(e)[:80]}

    @staticmethod
    def logs(s, ltype):
        urls = {"login": "/logs/login/", "clients": "/logs/clients/",
                "resellers": "/logs/resellers/", "sales": "/logs/sales/"}
        try:
            soup = BeautifulSoup(s.get(API._url(urls[ltype]), timeout=10).text, "html.parser")
            table = soup.find("table")
            if not table:
                return []
            results = []
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            for tr in table.find_all("tr")[1:]:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if cells:
                    if headers and len(headers) == len(cells):
                        results.append(dict(zip(headers, cells)))
                    else:
                        results.append({"data": " | ".join(cells)})
            return results
        except Exception:
            return []


# ══════════════════════════════════════════════
# FORMATADOR DE RESULTADOS
# ══════════════════════════════════════════════

def format_result(info, title, emoji):
    """Formata dados criados/teste de forma limpa e profissional."""
    t = f"{emoji} **{title}**\n{LINE}\n\n"

    # Campos de entrada do usuario
    input_map = {
        "_input_username": f"{E['user']} Usuario",
        "_input_password": f"{E['pass']} Senha",
        "_input_bouquet": f"{E['tv']} Bouquet",
        "_input_exp": f"{E['time']} Expiracao",
        "_input_credits": f"{E['credit']} Creditos",
    }
    has_input = False
    for key, label in input_map.items():
        if key in info:
            t += f"{label}: `{info[key]}`\n"
            has_input = True

    # Campos extraidos do painel
    extract_map = {
        "username": f"{E['user']} Usuario",
        "password": f"{E['pass']} Senha",
        "dns": f"{E['dns']} DNS/Host",
        "port": f"{E['port']} Porta",
        "exp_date": f"{E['time']} Expiracao",
    }
    has_ext = False
    for key, label in extract_map.items():
        if key in info and not key.startswith("_input"):
            val = info[key]
            if val and str(val).strip():
                if not has_ext and has_input:
                    t += f"\n{THIN}\n{E['info']} **Dados do Painel:**\n\n"
                t += f"{label}: `{val}`\n"
                has_ext = True

    # URLs
    if "urls" in info and info["urls"]:
        t += f"\n{E['link']} **URLs de Acesso:**\n"
        for url in info["urls"][:5]:
            t += f"```\n{url}\n```\n"

    # Raw lines
    if "_raw_lines" in info and info["_raw_lines"]:
        t += f"\n{E['info']} **Informacoes:**\n"
        for line in info["_raw_lines"][:10]:
            if line and not line.isspace():
                t += f"  - {line}\n"

    # Raw data
    if "raw_data" in info:
        t += f"\n{E['copy']} **Dados:**\n```\n{info['raw_data'][:400]}\n```\n"

    # Campos extras
    skip = set(list(input_map.keys()) + list(extract_map.keys()) +
               ["urls", "_raw_lines", "raw_data", "message", "error", "_test_type", "csrf_token"])
    extra = {k: v for k, v in info.items() if k not in skip and v and str(v).strip()}
    if extra:
        t += f"\n{E['info']} **Detalhes:**\n"
        for k, v in list(extra.items())[:10]:
            t += f"  {k.replace('_',' ').title()}: `{v}`\n"

    if "message" in info:
        t += f"\n{E['check']} {info['message']}\n"

    t += f"\n{LINE}"
    return t


# ══════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════

class UI:
    @staticmethod
    def dash_text(username, creds, dash):
        cr = creds.get("credits", "N/A") if creds else "N/A"
        iptv = dash.get("iptv", {}) if dash else {}
        p2p = dash.get("p2p", {}) if dash else {}
        return (
            f"{E['rocket']} **SILVA IPTV** `v{BOT_VERSION}`\n{LINE}\n\n"
            f"{E['user']} **Conta:** `{username}`\n"
            f"{E['credit']} **Creditos:** `{cr}`\n\n"
            f"{E['tv']} **IPTV** - Ativos: `{iptv.get('active_clients_count', 0)}` "
            f"| Online: `{iptv.get('online_clients_count', 0)}`\n"
            f"{E['p2p']} **P2P** - Ativos: `{p2p.get('active_clients_count', 0)}` "
            f"| Online: `{p2p.get('online_clients_count', 0)}`\n\n"
            f"{LINE}\n{E['crown']} {OWNER_USERNAME}"
        )

    @staticmethod
    def main_menu():
        return [
            [Button.inline(f"{E['dash']} Dashboard", b"dash"), Button.inline(f"{E['tv']} IPTV", b"iptv_list")],
            [Button.inline(f"{E['p2p']} P2P", b"p2p_list"), Button.inline(f"{E['rev']} Revendedores", b"resellers")],
            [Button.inline(f"{E['conn']} Conexoes", b"connections"), Button.inline(f"{E['search']} Buscar", b"search")],
            [Button.inline(f"{E['create']} Criar IPTV", b"create_iptv"), Button.inline(f"{E['create']} Criar P2P", b"create_p2p")],
            [Button.inline(f"{E['rev']} Criar Revenda", b"create_rev"), Button.inline(f"{E['test']} Teste", b"tests")],
            [Button.inline(f"{E['fast']} Fast Msg", b"fast_msg"), Button.inline(f"{E['log']} Logs", b"logs")],
            [Button.inline(f"{E['tool']} Ferramentas", b"tools"), Button.inline(f"{E['exit']} Sair", b"logout")],
        ]

    @staticmethod
    def back(cb=b"menu"):
        return [[Button.inline(f"{E['back']} Voltar", cb)]]

    @staticmethod
    def cancel():
        return [[Button.inline(f"{E['cancel']} Cancelar", b"menu")]]

    @staticmethod
    def confirm(yes_cb):
        return [[Button.inline(f"{E['ok']} Confirmar", yes_cb), Button.inline(f"{E['cancel']} Cancelar", b"menu")]]

    @staticmethod
    def client_list(clients, page, emoji, title, prefix=None):
        total = len(clients)
        pages = max(1, math.ceil(total / PAGE_SIZE))
        page = max(0, min(page, pages - 1))
        start = page * PAGE_SIZE
        items = clients[start:start + PAGE_SIZE]
        if prefix is None:
            prefix = re.sub(r'[^a-z]', '', title.lower())[:8]

        if not items:
            return f"{emoji} **{title}**\n\n{E['warn']} Lista vazia.", UI.back()

        lines = [f"{emoji} **{title}** - `{total}` total\n{LINE}\n"]
        for i, c in enumerate(items):
            num = start + i + 1
            s = E["online"] if c.get("online") else E["offline"]
            uname = c.get("username", "N/A")
            exp = c.get("exp_date", "")
            exp_str = f" | {E['time']} `{exp}`" if exp else ""
            lines.append(f"`{num}.` {s} `{uname}`{exp_str}")
        lines.append(f"\n{THIN}\nPag **{page + 1}/{pages}**")

        btns = [[Button.inline(f"{E['info']} {c.get('username', '?')[:15]}",
                 f"det_{prefix[:6]}_{c.get('id', '')}".encode())] for c in items]

        nav = []
        if page > 0:
            nav.append(Button.inline(f"{E['left']}", f"{prefix}_pg_{page - 1}".encode()))
        nav.append(Button.inline(f"{page + 1}/{pages}", b"noop"))
        if page < pages - 1:
            nav.append(Button.inline(f"{E['right']}", f"{prefix}_pg_{page + 1}".encode()))
        btns.append(nav)
        btns.append([Button.inline(f"{E['back']} Menu", b"menu")])
        return "\n".join(lines), btns


# ══════════════════════════════════════════════
# BOT
# ══════════════════════════════════════════════

bot = TelegramClient("silva_iptv_bot", API_ID, API_HASH).start(bot_token=BOT_TOKEN)


@bot.on(events.NewMessage(pattern="/start"))
async def cmd_start(event):
    if not event.is_private:
        return
    uid = event.sender_id
    sm.logout(uid)
    sm.set_state(uid, "login_user")
    try:
        await event.delete()
    except Exception:
        pass
    await event.respond(
        f"{E['lock']} **SILVA IPTV MANAGER** `v{BOT_VERSION}`\n{LINE}\n\n"
        f"Bem-vindo ao painel profissional.\n\n"
        f"{E['user']} Digite seu **usuario** do painel:",
        buttons=UI.cancel(), parse_mode="md"
    )
    raise events.StopPropagation


@bot.on(events.NewMessage)
async def on_text(event):
    if not event.is_private:
        return
    uid = event.sender_id
    txt = event.raw_text.strip()
    if txt.startswith("/"):
        return
    state = sm.get_state(uid)
    if not state:
        return
    step, data = state["step"], state["data"]

    async def _del():
        try:
            await event.delete()
        except Exception:
            pass

    # LOGIN
    if step == "login_user":
        data["username"] = txt
        sm.set_state(uid, "login_pass", data)
        await _del()
        await event.respond(f"{E['pass']} Digite sua **senha:**", buttons=UI.cancel(), parse_mode="md")
        return

    if step == "login_pass":
        await _del()
        msg = await event.respond(f"{E['load']} Autenticando...", parse_mode="md")
        s, result = API.login(data["username"], txt)
        if not s:
            sm.clear_state(uid)
            await msg.edit(f"{E['err']} **Falha:** `{result}`\n\nUse /start", parse_mode="md")
            return
        sm.set_session(uid, s, data["username"])
        sm.clear_state(uid)
        cr = API.credits(s)
        await msg.edit(UI.dash_text(data["username"], cr, result), buttons=UI.main_menu(), parse_mode="md")
        return

    # BUSCA
    if step == "search_term":
        s = sm.get_session(uid)
        if not s:
            return
        sm.clear_state(uid)
        await _del()
        msg = await event.respond(f"{E['load']} Buscando `{txt}`...", parse_mode="md")
        clients = API.search(s, txt)
        if not clients:
            await msg.edit(f"{E['search']} Nenhum resultado para `{txt}`", buttons=UI.back(), parse_mode="md")
            return
        sm.set_page_data(uid, clients, "search")
        t, b = UI.client_list(clients, 0, E["search"], "Resultados", "search")
        await msg.edit(t, buttons=b, parse_mode="md")
        return

    # FAST MSG
    if step == "fast_msg_id":
        s = sm.get_session(uid)
        if not s:
            return
        sm.clear_state(uid)
        await _del()
        msg = await event.respond(f"{E['load']} Enviando...", parse_mode="md")
        ok = API.fast_message(s, txt)
        r = "enviada" if ok else "falhou"
        await msg.edit(f"{E['ok'] if ok else E['err']} Fast Message **{r}** - ID `{txt}`", buttons=UI.back(), parse_mode="md")
        return

    # CRIAR IPTV
    if step == "ci_user":
        data["username"] = txt
        sm.set_state(uid, "ci_pass", data)
        await _del()
        await event.respond(f"{E['pass']} **Senha** do cliente:", buttons=UI.cancel(), parse_mode="md")
        return
    if step == "ci_pass":
        data["password"] = txt
        sm.set_state(uid, "ci_bouquet", data)
        await _del()
        await event.respond(f"{E['tv']} **Bouquet** (ex: `1,2,3`):", buttons=UI.cancel(), parse_mode="md")
        return
    if step == "ci_bouquet":
        data["bouquet"] = txt
        sm.set_state(uid, "ci_exp", data)
        await _del()
        await event.respond(f"{E['time']} **Expiracao** (ex: `2025-12-31`):", buttons=UI.cancel(), parse_mode="md")
        return
    if step == "ci_exp":
        data["expiry"] = txt
        sm.set_state(uid, "ci_confirm", data)
        await _del()
        await event.respond(
            f"{E['create']} **Confirmar IPTV**\n{LINE}\n\n"
            f"{E['user']} `{data['username']}`\n{E['pass']} `{data['password']}`\n"
            f"{E['tv']} `{data['bouquet']}`\n{E['time']} `{data['expiry']}`",
            buttons=UI.confirm(b"ok_iptv"), parse_mode="md"
        )
        return

    # CRIAR P2P
    if step == "cp_user":
        data["username"] = txt
        sm.set_state(uid, "cp_pass", data)
        await _del()
        await event.respond(f"{E['pass']} **Senha:**", buttons=UI.cancel(), parse_mode="md")
        return
    if step == "cp_pass":
        data["password"] = txt
        sm.set_state(uid, "cp_exp", data)
        await _del()
        await event.respond(f"{E['time']} **Expiracao** (ex: `2025-12-31`):", buttons=UI.cancel(), parse_mode="md")
        return
    if step == "cp_exp":
        data["expiry"] = txt
        sm.set_state(uid, "cp_confirm", data)
        await _del()
        await event.respond(
            f"{E['create']} **Confirmar P2P**\n{LINE}\n\n"
            f"{E['user']} `{data['username']}`\n{E['pass']} `{data['password']}`\n"
            f"{E['time']} `{data['expiry']}`",
            buttons=UI.confirm(b"ok_p2p"), parse_mode="md"
        )
        return

    # CRIAR REVENDEDOR
    if step == "cr_user":
        data["username"] = txt
        sm.set_state(uid, "cr_pass", data)
        await _del()
        await event.respond(f"{E['pass']} **Senha:**", buttons=UI.cancel(), parse_mode="md")
        return
    if step == "cr_pass":
        data["password"] = txt
        sm.set_state(uid, "cr_credits", data)
        await _del()
        await event.respond(f"{E['credit']} **Creditos:**", buttons=UI.cancel(), parse_mode="md")
        return
    if step == "cr_credits":
        data["credits"] = txt
        sm.set_state(uid, "cr_confirm", data)
        await _del()
        await event.respond(
            f"{E['create']} **Confirmar Revendedor**\n{LINE}\n\n"
            f"{E['user']} `{data['username']}`\n{E['pass']} `{data['password']}`\n"
            f"{E['credit']} `{data['credits']}`",
            buttons=UI.confirm(b"ok_rev"), parse_mode="md"
        )
        return

    # EDITAR SENHA
    if step == "edit_pw":
        sm.clear_state(uid)
        await _del()
        s = sm.get_session(uid)
        if not s:
            return
        msg = await event.respond(f"{E['load']} Alterando...", parse_mode="md")
        ok = API.edit_client(s, data["type"], data["id"], {"password": txt})
        sm.clear_cache(uid)
        await msg.edit(f"{E['ok'] if ok else E['err']} {'Senha alterada!' if ok else 'Falha.'}", buttons=UI.back(), parse_mode="md")
        return


# ══════════════════════════════════════════════
# CALLBACKS
# ══════════════════════════════════════════════

@bot.on(events.CallbackQuery)
async def on_cb(event):
    uid = event.sender_id
    d = event.data.decode()

    if d == "noop":
        await event.answer()
        return

    if d == "menu":
        s = sm.get_session(uid)
        if not s:
            await event.answer("Sessao expirada. /start", alert=True)
            return
        sm.clear_state(uid)
        dash = API.dashboard(s)
        if not dash:
            sm.logout(uid)
            await event.answer("Sessao expirada", alert=True)
            return
        cr = API.credits(s)
        await event.edit(UI.dash_text(sm.get_username(uid), cr, dash), buttons=UI.main_menu(), parse_mode="md")
        return

    if d == "logout":
        sm.logout(uid)
        await event.edit(f"{E['exit']} **Desconectado**\n\nUse /start\n\n{E['crown']} {OWNER_USERNAME}", parse_mode="md")
        return

    s = sm.get_session(uid)
    if not s:
        await event.answer("Sessao expirada. /start", alert=True)
        return

    # DASHBOARD
    if d == "dash":
        await event.answer(E["load"])
        dash = API.dashboard(s)
        cr = API.credits(s)
        stats = API.stats(s)
        sl = API.sales(s)
        un = sm.get_username(uid)
        iptv = dash.get("iptv", {}) if dash else {}
        p2p = dash.get("p2p", {}) if dash else {}
        t = (
            f"{E['dash']} **DASHBOARD**\n{LINE}\n\n"
            f"{E['user']} `{un}` | {E['credit']} `{cr.get('credits', 'N/A') if cr else 'N/A'}`\n\n"
            f"{E['tv']} **IPTV** - Ativos: `{iptv.get('active_clients_count', 0)}` | Online: `{iptv.get('online_clients_count', 0)}`\n"
            f"{E['p2p']} **P2P** - Ativos: `{p2p.get('active_clients_count', 0)}` | Online: `{p2p.get('online_clients_count', 0)}`\n"
        )
        if stats and isinstance(stats, dict):
            t += f"\n{THIN}\n{E['dash']} **Estatisticas**\n"
            for k, v in stats.items():
                if isinstance(v, (str, int, float)):
                    t += f"   {str(k).replace('_',' ').title()}: `{v}`\n"
        if sl and isinstance(sl, dict):
            t += f"\n{E['credit']} **Vendas**\n"
            for k, v in sl.items():
                if isinstance(v, (str, int, float)):
                    t += f"   {str(k).replace('_',' ').title()}: `{v}`\n"
        t += f"\n{LINE}"
        await event.edit(t, buttons=[
            [Button.inline(f"{E['refresh']} Atualizar", b"dash")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # LISTAS
    if d == "iptv_list":
        await event.answer(E["load"])
        cl = sm.get_cache(uid, "iptv") or API.iptv_clients(s)
        sm.set_cache(uid, "iptv", cl)
        sm.set_page_data(uid, cl, "iptv")
        t, b = UI.client_list(cl, 0, E["tv"], "Clientes IPTV", "iptv")
        await event.edit(t, buttons=b, parse_mode="md")
        return

    if d == "p2p_list":
        await event.answer(E["load"])
        cl = sm.get_cache(uid, "p2p") or API.p2p_clients(s)
        sm.set_cache(uid, "p2p", cl)
        sm.set_page_data(uid, cl, "p2p")
        t, b = UI.client_list(cl, 0, E["p2p"], "Clientes P2P", "p2p")
        await event.edit(t, buttons=b, parse_mode="md")
        return

    # PAGINACAO
    if "_pg_" in d:
        parts = d.rsplit("_pg_", 1)
        try:
            page = int(parts[1])
        except ValueError:
            return
        pd = sm.get_page_data(uid)
        if not pd:
            await event.answer("Expirado", alert=True)
            return
        em = {"iptv": E["tv"], "p2p": E["p2p"], "search": E["search"], "resellers": E["rev"]}
        nm = {"iptv": "Clientes IPTV", "p2p": "Clientes P2P", "search": "Resultados", "resellers": "Revendedores"}
        pt = pd["type"]
        t, b = UI.client_list(pd["items"], page, em.get(pt, E["info"]), nm.get(pt, "Lista"), pt)
        await event.edit(t, buttons=b, parse_mode="md")
        return

    # DETALHE
    if d.startswith("det_"):
        parts = d.split("_", 2)
        if len(parts) < 3:
            return
        cpfx, cid = parts[1], parts[2]
        pd = sm.get_page_data(uid)
        if not pd:
            await event.answer("Expirado", alert=True)
            return
        c = next((x for x in pd["items"] if str(x.get("id", "")) == cid), None)
        if not c:
            await event.answer("Nao encontrado", alert=True)
            return
        st = f"{E['online']} Online" if c.get("online") else f"{E['offline']} Offline"
        t = (
            f"{E['info']} **Detalhes**\n{LINE}\n\n"
            f"{E['user']} `{c.get('username', 'N/A')}`\n"
            f"Status: {st}\n"
            f"{E['time']} Exp: `{c.get('exp_date', 'N/A')}`\n"
            f"Criado: `{c.get('created_at', 'N/A')}`\n"
            f"Max conn: `{c.get('max_connections', 'N/A')}`\n"
            f"ID: `{cid}`\n\n{LINE}"
        )
        tk = "iptv" if "iptv" in cpfx else "p2p"
        await event.edit(t, buttons=[
            [Button.inline(f"{E['edit']} Senha", f"epw_{tk}_{cid}".encode()),
             Button.inline(f"{E['fast']} Fast Msg", f"fm_{cid}".encode())],
            [Button.inline(f"{E['del']} Remover", f"dc_{tk}_{cid}".encode())],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # EDITAR SENHA
    if d.startswith("epw_"):
        _, ct, cid = d.split("_", 2)
        sm.set_state(uid, "edit_pw", {"type": ct, "id": cid})
        await event.edit(f"{E['edit']} **Nova senha** para ID `{cid}`:", buttons=UI.cancel(), parse_mode="md")
        return

    # FAST MSG DIRETO
    if d.startswith("fm_"):
        cid = d[3:]
        ok = API.fast_message(s, cid)
        await event.answer(f"{E['ok']} Enviada!" if ok else f"{E['err']} Falha", alert=True)
        return

    # REMOVER
    if d.startswith("dc_"):
        _, ct, cid = d.split("_", 2)
        await event.edit(
            f"{E['del']} **Remover ID `{cid}`?**\n\n{E['warn']} Irreversivel!",
            buttons=UI.confirm(f"xd_{ct}_{cid}".encode()), parse_mode="md"
        )
        return

    if d.startswith("xd_"):
        _, ct, cid = d.split("_", 2)
        ok = API.delete_client(s, ct, cid)
        sm.clear_cache(uid)
        await event.edit(f"{E['ok'] if ok else E['err']} {'Removido!' if ok else 'Falha.'}\n\nID: `{cid}`",
                         buttons=UI.back(), parse_mode="md")
        return

    # REVENDEDORES
    if d == "resellers":
        await event.answer(E["load"])
        rl = API.resellers(s)
        if not rl:
            await event.edit(f"{E['rev']} **Revendedores**\n\n{E['warn']} Vazio.", buttons=UI.back(), parse_mode="md")
            return
        sm.set_page_data(uid, rl, "resellers")
        t, b = UI.client_list(rl, 0, E["rev"], "Revendedores", "resellers")
        await event.edit(t, buttons=b, parse_mode="md")
        return

    # CONEXOES
    if d == "connections":
        await event.answer(E["load"])
        cn = API.connections(s)
        if not cn:
            await event.edit(f"{E['conn']} **Conexoes**\n\n{E['warn']} Nenhuma ativa.", buttons=[
                [Button.inline(f"{E['refresh']} Atualizar", b"connections")],
                [Button.inline(f"{E['back']} Menu", b"menu")],
            ], parse_mode="md")
            return
        lines = [f"{E['conn']} **CONEXOES** - `{len(cn)}`\n{LINE}\n"]
        for i, c in enumerate(cn[:20]):
            lines.append(
                f"`{i+1}.` {E['online']} `{c.get('username', '?')}`\n"
                f"     {E['ip']} `{c.get('ip', '?')}` | {E['device']} `{c.get('device', '?')}` | {E['time']} `{c.get('duration', '?')}`"
            )
        if len(cn) > 20:
            lines.append(f"\n{E['warn']} +{len(cn)-20} conexoes")
        lines.append(f"\n{LINE}")
        await event.edit("\n".join(lines), buttons=[
            [Button.inline(f"{E['refresh']} Atualizar", b"connections")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # BUSCAR
    if d == "search":
        sm.set_state(uid, "search_term")
        await event.edit(f"{E['search']} **Buscar**\n\nDigite o **username:**", buttons=UI.cancel(), parse_mode="md")
        return

    # FAST MSG
    if d == "fast_msg":
        sm.set_state(uid, "fast_msg_id")
        await event.edit(f"{E['fast']} **Fast Message**\n\nDigite o **ID:**", buttons=UI.cancel(), parse_mode="md")
        return

    # CRIAR IPTV
    if d == "create_iptv":
        sm.set_state(uid, "ci_user", {})
        await event.edit(f"{E['create']} **Criar IPTV**\n{LINE}\n\n{E['user']} **Username:**", buttons=UI.cancel(), parse_mode="md")
        return

    if d == "ok_iptv":
        st = sm.get_state(uid)
        if not st or st["step"] != "ci_confirm":
            return
        dd = st["data"]
        sm.clear_state(uid)
        await event.edit(f"{E['load']} Criando IPTV...", parse_mode="md")
        ok, info = API.create_iptv(s, dd["username"], dd["password"], dd["bouquet"], dd["expiry"])
        sm.clear_cache(uid)
        if ok:
            text = format_result(info, "Cliente IPTV Criado", E["ok"])
        else:
            err = info.get("error", info.get("message", "Erro desconhecido"))
            text = f"{E['err']} **Falha IPTV**\n\n`{dd['username']}` - `{err}`"
        await event.edit(text, buttons=[
            [Button.inline(f"{E['create']} Criar Outro", b"create_iptv")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # CRIAR P2P
    if d == "create_p2p":
        sm.set_state(uid, "cp_user", {})
        await event.edit(f"{E['create']} **Criar P2P**\n{LINE}\n\n{E['user']} **Username:**", buttons=UI.cancel(), parse_mode="md")
        return

    if d == "ok_p2p":
        st = sm.get_state(uid)
        if not st or st["step"] != "cp_confirm":
            return
        dd = st["data"]
        sm.clear_state(uid)
        await event.edit(f"{E['load']} Criando P2P...", parse_mode="md")
        ok, info = API.create_p2p(s, dd["username"], dd["password"], dd["expiry"])
        sm.clear_cache(uid)
        if ok:
            text = format_result(info, "Cliente P2P Criado", E["ok"])
        else:
            err = info.get("error", info.get("message", "Erro desconhecido"))
            text = f"{E['err']} **Falha P2P**\n\n`{dd['username']}` - `{err}`"
        await event.edit(text, buttons=[
            [Button.inline(f"{E['create']} Criar Outro", b"create_p2p")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # CRIAR REVENDEDOR
    if d == "create_rev":
        sm.set_state(uid, "cr_user", {})
        await event.edit(f"{E['create']} **Criar Revendedor**\n{LINE}\n\n{E['user']} **Username:**", buttons=UI.cancel(), parse_mode="md")
        return

    if d == "ok_rev":
        st = sm.get_state(uid)
        if not st or st["step"] != "cr_confirm":
            return
        dd = st["data"]
        sm.clear_state(uid)
        await event.edit(f"{E['load']} Criando revendedor...", parse_mode="md")
        ok, info = API.create_reseller(s, dd["username"], dd["password"], dd["credits"])
        sm.clear_cache(uid)
        if ok:
            text = format_result(info, "Revendedor Criado", E["ok"])
        else:
            err = info.get("error", info.get("message", "Erro desconhecido"))
            text = f"{E['err']} **Falha**\n\n`{dd['username']}` - `{err}`"
        await event.edit(text, buttons=[
            [Button.inline(f"{E['create']} Criar Outro", b"create_rev")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # TESTES
    if d == "tests":
        await event.edit(f"{E['test']} **Teste Rapido**\n{LINE}\n\nSelecione:", buttons=[
            [Button.inline(f"{E['tv']} IPTV 24h", b"t_iptv1"), Button.inline(f"{E['tv']} IPTV 48h", b"t_iptv2")],
            [Button.inline(f"{E['p2p']} P2P 24h", b"t_p2p1"), Button.inline(f"{E['p2p']} P2P 48h", b"t_p2p2")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    if d.startswith("t_"):
        tt = d[2:]
        await event.answer(f"{E['load']}")
        await event.edit(f"{E['load']} Gerando teste...", parse_mode="md")
        info = API.test(s, tt)
        if info and "error" not in info:
            label = info.pop("_test_type", tt.upper())
            text = format_result(info, f"Teste {label} Criado", E["ok"])
        elif info and "error" in info:
            text = f"{E['err']} **Falha:** `{info['error']}`"
        else:
            text = f"{E['err']} **Falha** - Sem resposta do painel."
        await event.edit(text, buttons=[
            [Button.inline(f"{E['test']} Outro Teste", b"tests")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # LOGS
    if d == "logs":
        await event.edit(f"{E['log']} **Logs**\n{LINE}\n\nSelecione:", buttons=[
            [Button.inline(f"{E['user']} Login", b"l_login"), Button.inline(f"{E['tv']} Clientes", b"l_clients")],
            [Button.inline(f"{E['rev']} Revendedores", b"l_resellers"), Button.inline(f"{E['credit']} Vendas", b"l_sales")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    if d.startswith("l_"):
        lt = d[2:]
        await event.answer(E["load"])
        logs = API.logs(s, lt)
        nm = {"login": "Login", "clients": "Clientes", "resellers": "Revendedores", "sales": "Vendas"}
        title = nm.get(lt, "Logs")
        if not logs:
            await event.edit(f"{E['log']} **{title}**\n\n{E['warn']} Vazio.", buttons=[
                [Button.inline(f"{E['back']} Logs", b"logs"), Button.inline(f"{E['back']} Menu", b"menu")],
            ], parse_mode="md")
            return
        lines = [f"{E['log']} **{title}**\n{LINE}\n"]
        for i, entry in enumerate(logs[:25]):
            if isinstance(entry, dict):
                if "data" in entry:
                    lines.append(f"`{i+1}.` {entry['data']}")
                else:
                    parts = [f"**{k}:** `{v}`" for k, v in entry.items() if v]
                    lines.append(f"`{i+1}.` {' | '.join(parts)}")
            else:
                lines.append(f"`{i+1}.` {entry}")
        lines.append(f"\n{THIN}\n**{min(25,len(logs))}/{len(logs)}** registros")
        await event.edit("\n".join(lines), buttons=[
            [Button.inline(f"{E['refresh']} Atualizar", d.encode())],
            [Button.inline(f"{E['back']} Logs", b"logs"), Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    # FERRAMENTAS
    if d == "tools":
        await event.edit(f"{E['tool']} **Ferramentas**\n{LINE}", buttons=[
            [Button.inline(f"{E['refresh']} Limpar Cache", b"clr_cache"), Button.inline(f"{E['dash']} Stats", b"dash")],
            [Button.inline(f"{E['conn']} Conexoes", b"connections")],
            [Button.inline(f"{E['back']} Menu", b"menu")],
        ], parse_mode="md")
        return

    if d == "clr_cache":
        sm.clear_cache(uid)
        await event.answer(f"{E['ok']} Cache limpo!", alert=True)
        return

    await event.answer()


# ══════════════════════════════════════════════
print("=" * 48)
print("  SILVA IPTV PANEL MANAGER v6.0 PRO - ONLINE")
print(f"  Owner: {OWNER_NAME} | {OWNER_USERNAME}")
print("=" * 48)

bot.run_until_disconnected()
