#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════╗
║  USERBOT SILVA + @InforUser_Bot  PRO     ║
║  Sistema de Automação de Mensagens       ║
║  Consulta URL + Inline Search + AutoMs   ║
║  Paginação Avançada + Markdown           ║
║  👤 Dono: Edivaldo Silva                 ║
║  🆔 ID: 2061557102                       ║
╚══════════════════════════════════════════╝
"""

import os
import re
import sys
import json
import math
import random
import socket
import asyncio
import hashlib
import requests
from io import StringIO
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from requests.sessions import Session

from telethon import TelegramClient, events, Button
from telethon.tl.types import InputBotInlineResult, InputBotInlineMessageText
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.errors import UserNotParticipantError

# ══════════════════════════════════════
# CONFIGURAÇÕES
# ══════════════════════════════════════

API_ID = 29214781
API_HASH = "9fc77b4f32302f4d4081a4839cc7ae1f"
PHONE = "+5588998225077"
BOT_TOKEN = "8618840827:AAEQx9qnUiDpjqzlMAoyjIxxGXbM_I71wQw"
OWNER_ID = 2061557102  # Edivaldo Silva
OWNER_CONTACT = "@Edkd1"

CANAL_RESULTADOS_ID = -1003774905088
BASE_DIR = "/sdcard/EuBot"
GRUPOS_FILE = os.path.join(BASE_DIR, "grupos_permitidos.txt")
AUTOMS_FILE = os.path.join(BASE_DIR, "automs.json")
USERS_FILE = os.path.join(BASE_DIR, "usuarios.json")
AUTOREPLY_FILE = os.path.join(BASE_DIR, "autoreply.json")
MSGS_PRONTAS_FILE = os.path.join(BASE_DIR, "msgs_prontas.json")
ITEMS_PER_PAGE = 5

# ══════════════════════════════════════
# CLIENTES TELETHON
# ══════════════════════════════════════

userbot = TelegramClient("userbot_silva_session", API_ID, API_HASH)
bot = TelegramClient("bot_silva_session", API_ID, API_HASH)

# ══════════════════════════════════════
# UTILITÁRIOS DE ARQUIVO
# ══════════════════════════════════════

def ensure_base_dir():
    os.makedirs(BASE_DIR, exist_ok=True)

def safe_json_load(filepath, default=None):
    ensure_base_dir()
    if default is None:
        default = []
    if not os.path.exists(filepath):
        safe_json_save(filepath, default)
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return default

def safe_json_save(filepath, data):
    ensure_base_dir()
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ══════════════════════════════════════
# GESTÃO DE USUÁRIOS (registro automático)
# ══════════════════════════════════════

def load_users():
    return safe_json_load(USERS_FILE, [])

def save_users(users):
    safe_json_save(USERS_FILE, users)

def register_user(user_id, first_name="", last_name="", username=None):
    """Registra ou atualiza um usuário automaticamente."""
    users = load_users()
    existing = next((u for u in users if u["id"] == user_id), None)
    now = datetime.now().strftime('%d/%m/%Y %H:%M:%S')

    if existing:
        existing["nome"] = f"{first_name} {last_name}".strip()
        existing["username"] = username
        existing["ultimo_acesso"] = now
        existing["interacoes"] = existing.get("interacoes", 0) + 1
    else:
        users.append({
            "id": user_id,
            "nome": f"{first_name} {last_name}".strip(),
            "username": username,
            "registrado_em": now,
            "ultimo_acesso": now,
            "interacoes": 1
        })
    save_users(users)

def get_user_info(user_id):
    users = load_users()
    return next((u for u in users if u["id"] == user_id), None)

def find_user(query):
    """Encontra usuário por ID, username ou nome."""
    users = load_users()
    query_str = str(query).strip().lstrip("@")
    for u in users:
        if str(u["id"]) == query_str:
            return u
        if u.get("username") and u["username"].lower() == query_str.lower():
            return u
    return None

# ══════════════════════════════════════
# GESTÃO DE GRUPOS PERMITIDOS
# ══════════════════════════════════════

def load_groups():
    ensure_base_dir()
    if not os.path.exists(GRUPOS_FILE):
        with open(GRUPOS_FILE, "w") as f:
            f.write("")
        return []
    with open(GRUPOS_FILE, "r") as f:
        lines = f.read().strip().split("\n")
    groups = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parts = line.split("|", 1)
            gid = int(parts[0].strip())
            name = parts[1].strip() if len(parts) > 1 else "Sem nome"
            groups.append({"id": gid, "name": name})
        except ValueError:
            continue
    return groups

def save_groups(groups):
    ensure_base_dir()
    with open(GRUPOS_FILE, "w") as f:
        for g in groups:
            f.write(f"{g['id']}|{g['name']}\n")

def is_group_allowed(chat_id):
    groups = load_groups()
    return any(g["id"] == chat_id for g in groups)

def add_group(chat_id, name):
    groups = load_groups()
    if any(g["id"] == chat_id for g in groups):
        return False
    groups.append({"id": chat_id, "name": name})
    save_groups(groups)
    return True

def remove_group(chat_id):
    groups = load_groups()
    new_groups = [g for g in groups if g["id"] != chat_id]
    if len(new_groups) == len(groups):
        return False
    save_groups(new_groups)
    return True

# ══════════════════════════════════════
# GESTÃO DE AUTOMS (Mensagens Automáticas)
# ══════════════════════════════════════

def load_automs():
    return safe_json_load(AUTOMS_FILE, [])

def save_automs(automs):
    safe_json_save(AUTOMS_FILE, automs)

def add_autom(title, message):
    automs = load_automs()
    automs.append({
        "title": title or "",
        "message": message or "",
        "ativa": True,
        "criada_em": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    })
    save_automs(automs)
    return len(automs)

def remove_autom(index):
    automs = load_automs()
    if 0 <= index < len(automs):
        removed = automs.pop(index)
        save_automs(automs)
        return removed
    return None

def toggle_autom(index):
    automs = load_automs()
    if 0 <= index < len(automs):
        automs[index]["ativa"] = not automs[index].get("ativa", True)
        save_automs(automs)
        return automs[index]
    return None

def update_autom(index, title=None, message=None):
    automs = load_automs()
    if 0 <= index < len(automs):
        if title is not None:
            automs[index]["title"] = title
        if message is not None:
            automs[index]["message"] = message
        save_automs(automs)
        return automs[index]
    return None

# ══════════════════════════════════════
# MENSAGENS PRONTAS (pré-configuradas)
# ══════════════════════════════════════

def load_msgs_prontas():
    return safe_json_load(MSGS_PRONTAS_FILE, [])

def save_msgs_prontas(msgs):
    safe_json_save(MSGS_PRONTAS_FILE, msgs)

def add_msg_pronta(title, message):
    msgs = load_msgs_prontas()
    msgs.append({
        "title": title or "",
        "message": message or "",
        "ativa": True,
        "criada_em": datetime.now().strftime('%d/%m/%Y %H:%M:%S')
    })
    save_msgs_prontas(msgs)
    return len(msgs)

def remove_msg_pronta(index):
    msgs = load_msgs_prontas()
    if 0 <= index < len(msgs):
        removed = msgs.pop(index)
        save_msgs_prontas(msgs)
        return removed
    return None

def toggle_msg_pronta(index):
    msgs = load_msgs_prontas()
    if 0 <= index < len(msgs):
        msgs[index]["ativa"] = not msgs[index].get("ativa", True)
        save_msgs_prontas(msgs)
        return msgs[index]
    return None

def update_msg_pronta(index, title=None, message=None):
    msgs = load_msgs_prontas()
    if 0 <= index < len(msgs):
        if title is not None:
            msgs[index]["title"] = title
        if message is not None:
            msgs[index]["message"] = message
        save_msgs_prontas(msgs)
        return msgs[index]
    return None

# ══════════════════════════════════════
# AUTO-REPLY (Resposta automática em DM)
# ══════════════════════════════════════

def load_autoreply():
    data = safe_json_load(AUTOREPLY_FILE, {"ativo": False, "mensagem": ""})
    if isinstance(data, list):
        data = {"ativo": False, "mensagem": ""}
        safe_json_save(AUTOREPLY_FILE, data)
    return data

def save_autoreply(data):
    safe_json_save(AUTOREPLY_FILE, data)

def set_autoreply(ativo, mensagem=None):
    data = load_autoreply()
    data["ativo"] = ativo
    if mensagem is not None:
        data["mensagem"] = mensagem
    save_autoreply(data)
    return data

# Track quem já recebeu auto-reply nesta sessão
autoreply_sent = set()

# ══════════════════════════════════════
# ESTADO PER-USER (edição, envio, etc.)
# ══════════════════════════════════════

edit_states = {}
# Estados possíveis:
# {"action": "edit_autom", "index": N, "step": "choose|waiting", "field": "title|message"}
# {"action": "set_autoreply", "step": "waiting"}
# {"action": "edit_msgpronta", "index": N, "step": "choose|waiting", "field": "title|message"}
# {"action": "add_msgpronta", "step": "title|message", "title": "...", "message": "..."}
# {"action": "send_msgpronta", "index": N, "step": "waiting_target"}
# {"action": "add_autom", "step": "title|message", "title": "...", "message": "..."}

# ══════════════════════════════════════
# FUNÇÕES DE CONSULTA IPTV / URL
# ══════════════════════════════════════

def format_date(timestamp):
    try:
        return datetime.fromtimestamp(int(timestamp)).strftime('%d/%m/%Y %H:%M:%S')
    except Exception:
        return "N/D"

def fetch_data(session, url):
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Mozilla/5.0 (Linux; Android 10)",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6)",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64)"
    ]
    headers = {'User-Agent': random.choice(user_agents)}
    try:
        response = session.get(url, headers=headers, timeout=8)
        response.raise_for_status()
        return response.json()
    except requests.RequestException:
        return None

def is_port_open(host, port):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(3)
            return sock.connect_ex((host, port)) == 0
    except socket.error:
        return False

def get_host_ip(host):
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return None

def check_url(url):
    parsed_url = urlparse(url)
    host = parsed_url.hostname
    port = parsed_url.port or 80
    query_params = parse_qs(parsed_url.query)
    username = query_params.get('username', [None])[0]
    password = query_params.get('password', [None])[0]

    if not (host and username and password):
        return None, "❌ URL inválida. Faltam parâmetros (username/password)."

    ip_address = get_host_ip(host)
    if not ip_address:
        return None, f"❌ Não foi possível resolver o host."

    if not is_port_open(host, port):
        return None, f"❌ Servidor offline."

    api_url = f'http://{host}:{port}/player_api.php?username={username}&password={password}'

    try:
        with Session() as session:
            data = fetch_data(session, api_url)
            if not data:
                return None, "❌ Servidor OFF ou sem resposta."

            user_info = data.get('user_info', {})
            if user_info.get('auth') == 0:
                return None, "❌ Credenciais inválidas (auth=0)."

            live = fetch_data(session, f'{api_url}&action=get_live_streams')
            vod = fetch_data(session, f'{api_url}&action=get_vod_streams')
            series = fetch_data(session, f'{api_url}&action=get_series')

            total_canais = len(live) if live else 0
            total_vods = len(vod) if vod else 0
            total_series = len(series) if series else 0

            return build_result(data, total_canais, total_vods, total_series, ip_address), None

    except Exception as e:
        return None, f"❌ Erro: {str(e)}"

def build_result(data, total_canais, total_vods, total_series, ip_address):
    ui = data['user_info']
    si = data['server_info']
    server = si.get('url', 'N/D')
    port = si.get('port', 'N/D')
    username = ui.get('username', 'N/D')
    password = ui.get('password', 'N/D')
    status = ui.get('status', 'N/D')
    creation = format_date(ui.get('created_at', 0))
    expiration = format_date(ui.get('exp_date', 0))
    max_conn = ui.get('max_connections', 'N/D')
    active_conn = ui.get('active_cons', 'N/D')
    formats = ', '.join(ui.get('allowed_output_formats', []))
    timezone = si.get('timezone', 'N/D')
    https_port = si.get('https_port', 'N/D')
    protocol = si.get('server_protocol', 'N/D')
    rtmp_port = si.get('rtmp_port', 'N/D')
    time_now = si.get('time_now', 'N/D')

    status_emoji = "✅" if status == "Active" else "❌"
    m3u_link = f"http://{server}:{port}/get.php?username={username}&password={password}&type=m3u"

    result = (
        f"╔══════════════════════════════╗\n"
        f"║   {status_emoji} RESULTADO DA CONSULTA     ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"📊 **Status:** `{status}`\n"
        f"👤 **Usuário:** `{username}`\n"
        f"🔑 **Senha:** `{password}`\n"
        f"\n"
        f"📅 **Criação:** `{creation}`\n"
        f"⏰ **Expiração:** `{expiration}`\n"
        f"\n"
        f"🔗 **Conexões:** `{active_conn}/{max_conn}`\n"
        f"\n"
        f"🌐 **Host:** `{server}`\n"
        f"🔌 **Porta:** `{port}`\n"
        f"📡 **IP:** `{ip_address}`\n"
        f"🔒 **HTTPS:** `{https_port}`\n"
        f"📶 **Protocolo:** `{protocol}`\n"
        f"📺 **RTMP:** `{rtmp_port}`\n"
        f"🕐 **Hora:** `{time_now}`\n"
        f"🌍 **Timezone:** `{timezone}`\n"
        f"\n"
        f"📂 **Formato:** `{formats}`\n"
        f"📺 **Canais:** `{total_canais}`\n"
        f"🎬 **Filmes:** `{total_vods}`\n"
        f"🎭 **Séries:** `{total_series}`\n"
        f"\n"
        f"🔗 **M3U:**\n`{m3u_link}`\n"
        f"\n"
        f"╚══════════════════════════════╝"
    )
    return result

# ══════════════════════════════════════
#  USERBOT — AUTO-REPLY EM DMs
# ══════════════════════════════════════

@userbot.on(events.NewMessage(incoming=True, func=lambda e: e.is_private))
async def handle_dm_autoreply(event):
    """Responde automaticamente quando alguém inicia DM."""
    if event.sender_id == OWNER_ID:
        return

    ar = load_autoreply()
    if not ar.get("ativo") or not ar.get("mensagem"):
        return

    # Envia apenas uma vez por sessão
    if event.sender_id in autoreply_sent:
        return

    autoreply_sent.add(event.sender_id)

    # Registra o usuário
    sender = await event.get_sender()
    register_user(
        event.sender_id,
        getattr(sender, 'first_name', '') or '',
        getattr(sender, 'last_name', '') or '',
        getattr(sender, 'username', None)
    )

    await event.reply(ar["mensagem"], parse_mode='md')

# ══════════════════════════════════════
#  USERBOT — CONSULTA VIA REPLY (URL)
# ══════════════════════════════════════

URL_PATTERN = r'(https?://[^\s]+)'

@userbot.on(events.NewMessage(incoming=True))
async def handle_incoming_reply(event):
    """Responde consultas quando alguém responde a uma mensagem do userbot com URL."""
    if not event.is_reply:
        return

    replied = await event.get_reply_message()
    if not replied or not replied.out:
        return

    # Verifica se o grupo é permitido
    if event.is_group or event.is_channel:
        if not is_group_allowed(event.chat_id):
            return

    match = re.search(URL_PATTERN, event.raw_text)
    if not match:
        return

    url = match.group(1)
    sender = await event.get_sender()
    sender_name = getattr(sender, 'first_name', '') or ''
    sender_last = getattr(sender, 'last_name', '') or ''
    sender_username = getattr(sender, 'username', None)
    sender_id = sender.id

    # Registra o usuário
    register_user(sender_id, sender_name, sender_last, sender_username)

    processing_msg = await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║    ⏳ PROCESSANDO CONSULTA    ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"👤 **Solicitante:** {sender_name} {sender_last}\n"
        f"🆔 **ID:** `{sender_id}`\n"
        f"📡 Aguarde..."
    )

    loop = asyncio.get_event_loop()
    result, error = await loop.run_in_executor(None, check_url, url)

    if error:
        await processing_msg.edit(
            f"╔══════════════════════════════╗\n"
            f"║     ❌ CONSULTA FALHOU        ║\n"
            f"╚══════════════════════════════╝\n"
            f"\n"
            f"👤 **Solicitante:** {sender_name} {sender_last}\n"
            f"🆔 **ID:** `{sender_id}`\n"
            f"\n{error}"
        )
        return

    user_tag = f"@{sender_username}" if sender_username else f"`{sender_id}`"
    header = (
        f"👤 **Solicitante:** {sender_name} {sender_last}\n"
        f"🆔 **ID:** `{sender_id}`\n"
        f"📎 **User:** {user_tag}\n\n"
    )

    await processing_msg.edit(header + result, parse_mode='md')

    # Envia para o canal
    try:
        channel_msg = (
            f"📨 **Nova Consulta**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **De:** {sender_name} {sender_last} ({user_tag})\n"
            f"🆔 **ID:** `{sender_id}`\n"
            f"💬 **Chat:** `{event.chat_id}`\n"
            f"🕐 **Data:** `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"\n{result}"
        )
        await userbot.send_message(CANAL_RESULTADOS_ID, channel_msg, parse_mode='md')
    except Exception as e:
        print(f"[!] Erro ao enviar ao canal: {e}")

@userbot.on(events.NewMessage(outgoing=True))
async def handle_self_reply(event):
    """Permite o próprio dono consultar respondendo suas próprias mensagens com URL."""
    if not event.is_reply:
        return

    replied = await event.get_reply_message()
    if not replied or not replied.out:
        return

    if "RESULTADO DA CONSULTA" in event.raw_text or "PROCESSANDO" in event.raw_text:
        return

    match = re.search(URL_PATTERN, event.raw_text)
    if not match:
        return

    url = match.group(1)
    me = await userbot.get_me()

    processing_msg = await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║    ⏳ PROCESSANDO (TESTE)     ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"👤 **Dono:** {me.first_name or ''}\n"
        f"📡 Aguarde..."
    )

    loop = asyncio.get_event_loop()
    result, error = await loop.run_in_executor(None, check_url, url)

    if error:
        await processing_msg.edit(
            f"╔══════════════════════════════╗\n"
            f"║     ❌ CONSULTA FALHOU        ║\n"
            f"╚══════════════════════════════╝\n"
            f"\n{error}"
        )
        return

    me_tag = f"@{me.username}" if me.username else f"`{me.id}`"
    header = (
        f"👤 **Dono:** {me.first_name or ''}\n"
        f"🆔 **ID:** `{me.id}`\n\n"
    )

    await processing_msg.edit(header + result, parse_mode='md')

    try:
        channel_msg = (
            f"📨 **Consulta (Teste Próprio)**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **Dono:** {me.first_name or ''} ({me_tag})\n"
            f"🕐 **Data:** `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"\n{result}"
        )
        await userbot.send_message(CANAL_RESULTADOS_ID, channel_msg, parse_mode='md')
    except Exception as e:
        print(f"[!] Erro ao enviar ao canal: {e}")

# ══════════════════════════════════════
#  USERBOT — CONSULTA VIA @InforUser_Bot + URL
#  O userbot detecta menções ao bot no chat
#  e faz a consulta mesmo que o bot não esteja
#  presente — basta o userbot estar no chat.
# ══════════════════════════════════════

@userbot.on(events.NewMessage(incoming=True))
async def handle_bot_mention_query(event):
    """
    Detecta quando alguém escreve @InforUser_Bot + URL no chat.
    O userbot faz a consulta e responde, mesmo que o bot não esteja no chat.
    Apenas funciona em grupos permitidos.
    """
    if event.is_private:
        return

    text = event.raw_text or ""
    # Verifica se a mensagem menciona @InforUser_Bot
    mention_pattern = r'@InforUser_Bot\s+(https?://[^\s]+)'
    match = re.search(mention_pattern, text, re.IGNORECASE)
    if not match:
        return

    # Verifica se o grupo é permitido
    if not is_group_allowed(event.chat_id):
        return

    url = match.group(1)
    sender = await event.get_sender()
    sender_name = getattr(sender, 'first_name', '') or ''
    sender_last = getattr(sender, 'last_name', '') or ''
    sender_username = getattr(sender, 'username', None)
    sender_id = sender.id

    register_user(sender_id, sender_name, sender_last, sender_username)

    processing_msg = await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║    ⏳ CONSULTANDO URL...       ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"👤 **Solicitante:** {sender_name} {sender_last}\n"
        f"🆔 **ID:** `{sender_id}`\n"
        f"📡 Aguarde...",
        parse_mode='md'
    )

    loop = asyncio.get_event_loop()
    result, error = await loop.run_in_executor(None, check_url, url)

    if error:
        await processing_msg.edit(
            f"╔══════════════════════════════╗\n"
            f"║     ❌ CONSULTA FALHOU        ║\n"
            f"╚══════════════════════════════╝\n"
            f"\n"
            f"👤 {sender_name} {sender_last}\n"
            f"🆔 `{sender_id}`\n"
            f"\n{error}",
            parse_mode='md'
        )
        return

    user_tag = f"@{sender_username}" if sender_username else f"`{sender_id}`"
    header = (
        f"👤 **Solicitante:** {sender_name} {sender_last}\n"
        f"🆔 **ID:** `{sender_id}`\n"
        f"📎 **User:** {user_tag}\n\n"
    )

    await processing_msg.edit(header + result, parse_mode='md')

    # Log no canal
    try:
        channel_msg = (
            f"📨 **Consulta via @InforUser\_Bot (Userbot)**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **De:** {sender_name} {sender_last} ({user_tag})\n"
            f"🆔 **ID:** `{sender_id}`\n"
            f"💬 **Chat:** `{event.chat_id}`\n"
            f"🕐 **Data:** `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"\n{result}"
        )
        await userbot.send_message(CANAL_RESULTADOS_ID, channel_msg, parse_mode='md')
    except Exception as e:
        print(f"[!] Erro ao enviar ao canal (mention): {e}")

# ══════════════════════════════════════
#  BOT — GESTÃO DE GRUPOS (com paginação)
# ══════════════════════════════════════

def build_groups_page(page=0):
    groups = load_groups()
    total = len(groups)
    total_pages = max(1, math.ceil(total / ITEMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_groups = groups[start:end]

    text = (
        f"╔══════════════════════════════╗\n"
        f"║   📋 GRUPOS PERMITIDOS        ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"📊 **Total:** `{total}` grupo(s)\n"
        f"📄 **Página:** `{page + 1}/{total_pages}`\n\n"
    )

    if not page_groups:
        text += "📭 Nenhum grupo cadastrado.\n"
    else:
        for i, g in enumerate(page_groups, start=start + 1):
            text += f"**{i}.** `{g['id']}` — {g['name']}\n"

    text += f"\n╚══════════════════════════════╝"

    buttons = []
    for g in page_groups:
        buttons.append([Button.inline(f"🗑 Remover: {g['name'][:20]}", data=f"rmgrp:{g['id']}")])

    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀️ Voltar", data=f"grppage:{page - 1}"))
    nav_row.append(Button.inline(f"📄 {page + 1}/{total_pages}", data="noop"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("Avançar ▶️", data=f"grppage:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        Button.inline("➕ Adicionar Grupo", data="addgrp"),
        Button.inline("🔄 Atualizar", data="grppage:0")
    ])

    return text, buttons

# ---------- BOT: /start ----------
@bot.on(events.NewMessage(pattern=r'^/start$'))
async def bot_start(event):
    if event.is_private:
        sender = await event.get_sender()
        register_user(
            event.sender_id,
            getattr(sender, 'first_name', '') or '',
            getattr(sender, 'last_name', '') or '',
            getattr(sender, 'username', None)
        )

        is_owner = event.sender_id == OWNER_ID
        text = (
            "╔══════════════════════════════╗\n"
            "║  🤖 SILVA AUTOMAÇÃO  PRO      ║\n"
            "╚══════════════════════════════╝\n"
            "\n"
            "Bem-vindo! Sistema de **automação de mensagens**\n"
            "e consulta de URL.\n\n"
            "📡 **Inline:** `@InforUser_Bot URL`\n"
            "📨 **Privado:** Envie uma URL aqui\n"
            "📋 **Comandos:** /help\n"
        )
        if is_owner:
            text += (
                "\n"
                "👑 **Painel Admin disponível!**\n"
            )
        text += "\n╚══════════════════════════════╝"

        buttons = []
        if is_owner:
            buttons = [
                [Button.inline("📋 Grupos", data="grppage:0"), Button.inline("💬 AutoMs", data="autompage:0")],
                [Button.inline("📝 Msgs Prontas", data="mppage:0"), Button.inline("🔄 Auto-Reply", data="ar_panel")],
                [Button.inline("👥 Usuários", data="userspage:0"), Button.inline("📊 Status", data="show_status")]
            ]

        await event.reply(text, buttons=buttons if buttons else None, parse_mode='md')

# ---------- BOT: /help ----------
@bot.on(events.NewMessage(pattern=r'^/help$'))
async def bot_help(event):
    is_owner = (event.sender_id == OWNER_ID)
    text = (
        "╔══════════════════════════════╗\n"
        "║   📖 COMANDOS                 ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "🔹 `/start` — Menu inicial\n"
        "🔹 `/help` — Esta mensagem\n"
        "🔹 Envie uma **URL** no privado para consultar\n"
        "🔹 **Inline:** `@InforUser_Bot URL`\n"
    )
    if is_owner:
        text += (
            "\n"
            "👑 **COMANDOS ADMIN:**\n"
            "🔹 `/grupos` — Gestão de grupos\n"
            "🔹 `/addgrupo <id>` — Adicionar grupo\n"
            "🔹 `/id` — Ver ID do chat\n"
            "🔹 `/status` — Status do sistema\n"
            "🔹 `/automs` — Mensagens automáticas\n"
            "🔹 `/addautom <titulo> | <msg>` — Add autom\n"
            "🔹 `/msgprontas` — Msgs pré-configuradas\n"
            "🔹 `/addmsg <titulo> | <msg>` — Add msg pronta\n"
            "🔹 `/autoreply` — Auto-reply em DMs\n"
            "🔹 `/usuarios` — Usuários registrados\n"
            "🔹 `/broadcast <msg>` — Enviar a todos\n"
        )
    text += "\n╚══════════════════════════════╝"
    await event.reply(text, parse_mode='md')

# ---------- BOT: /grupos ----------
@bot.on(events.NewMessage(pattern=r'^/grupos$'))
async def bot_grupos(event):
    if event.sender_id != OWNER_ID:
        await event.reply("⛔ Apenas o dono pode gerenciar grupos.")
        return
    text, buttons = build_groups_page(0)
    await event.reply(text, buttons=buttons, parse_mode='md')

# ---------- BOT: Callback paginação grupos ----------
@bot.on(events.CallbackQuery(pattern=r'^grppage:(\d+)$'))
async def bot_callback_page(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    page = int(event.pattern_match.group(1))
    text, buttons = build_groups_page(page)
    await event.edit(text, buttons=buttons, parse_mode='md')

# ---------- BOT: Callback remover grupo ----------
@bot.on(events.CallbackQuery(pattern=r'^rmgrp:(-?\d+)$'))
async def bot_callback_remove(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    gid = int(event.pattern_match.group(1))
    removed = remove_group(gid)
    if removed:
        await event.answer(f"✅ Grupo {gid} removido!", alert=True)
    else:
        await event.answer(f"❌ Grupo {gid} não encontrado.", alert=True)
    text, buttons = build_groups_page(0)
    await event.edit(text, buttons=buttons, parse_mode='md')

# ---------- BOT: Callback adicionar prompt ----------
@bot.on(events.CallbackQuery(pattern=r'^addgrp$'))
async def bot_callback_add_prompt(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    await event.answer()
    await event.reply(
        "╔══════════════════════════════╗\n"
        "║   ➕ ADICIONAR GRUPO          ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "Envie apenas o **ID do grupo**:\n"
        "`/addgrupo -100123456`\n"
        "\n💡 O nome será detectado automaticamente.\n"
        "💡 Use `/id` dentro do grupo para descobrir o ID.",
        parse_mode='md'
    )

@bot.on(events.CallbackQuery(pattern=r'^noop$'))
async def bot_callback_noop(event):
    await event.answer()

# ---------- BOT: /addgrupo ----------
@bot.on(events.NewMessage(pattern=r'^/addgrupo\s+(-?\d+)(?:\s+(.+))?$'))
async def bot_add_group(event):
    if event.sender_id != OWNER_ID:
        return
    gid = int(event.pattern_match.group(1))
    name = event.pattern_match.group(2)

    if not name:
        try:
            entity = await bot.get_entity(gid)
            name = getattr(entity, 'title', None) or getattr(entity, 'first_name', 'Grupo')
        except Exception:
            name = f"Grupo {gid}"

    name = name.strip()
    added = add_group(gid, name)
    if added:
        await event.reply(
            f"✅ **Grupo adicionado!**\n"
            f"📋 **Nome:** {name}\n"
            f"🆔 **ID:** `{gid}`\n"
            f"\nUse /grupos para ver a lista.",
            parse_mode='md'
        )
    else:
        await event.reply(f"⚠️ Grupo `{gid}` já está cadastrado.", parse_mode='md')

# ---------- BOT: /id ----------
@bot.on(events.NewMessage(pattern=r'^/id$'))
async def bot_get_id(event):
    chat = await event.get_chat()
    chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'N/A')
    await event.reply(
        f"🆔 **Chat:** `{event.chat_id}`\n"
        f"📋 **Nome:** {chat_name}\n"
        f"👤 **Seu ID:** `{event.sender_id}`",
        parse_mode='md'
    )

# ---------- BOT: /status ----------
@bot.on(events.NewMessage(pattern=r'^/status$'))
async def bot_status(event):
    if event.sender_id != OWNER_ID:
        return
    groups = load_groups()
    automs = load_automs()
    users = load_users()
    ar = load_autoreply()
    msgs = load_msgs_prontas()
    active_automs = sum(1 for a in automs if a.get("ativa", True))
    active_msgs = sum(1 for m in msgs if m.get("ativa", True))
    await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║   📊 STATUS DO SISTEMA        ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"✅ **Bot + Userbot Online**\n"
        f"📋 **Grupos ativos:** `{len(groups)}`\n"
        f"💬 **AutoMs:** `{active_automs}/{len(automs)}`\n"
        f"📝 **Msgs Prontas:** `{active_msgs}/{len(msgs)}`\n"
        f"👥 **Usuários:** `{len(users)}`\n"
        f"🔄 **Auto-Reply:** `{'✅ Ativo' if ar.get('ativo') else '❌ Inativo'}`\n"
        f"🕐 **Hora:** `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
        f"\n╚══════════════════════════════╝",
        parse_mode='md'
    )

@bot.on(events.CallbackQuery(pattern=r'^show_status$'))
async def bot_callback_status(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    groups = load_groups()
    automs = load_automs()
    users = load_users()
    ar = load_autoreply()
    msgs = load_msgs_prontas()
    active_automs = sum(1 for a in automs if a.get("ativa", True))
    active_msgs = sum(1 for m in msgs if m.get("ativa", True))
    await event.answer()
    await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║   📊 STATUS DO SISTEMA        ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"✅ **Bot + Userbot Online**\n"
        f"📋 **Grupos:** `{len(groups)}`\n"
        f"💬 **AutoMs:** `{active_automs}/{len(automs)}`\n"
        f"📝 **Msgs Prontas:** `{active_msgs}/{len(msgs)}`\n"
        f"👥 **Usuários:** `{len(users)}`\n"
        f"🔄 **Auto-Reply:** `{'✅ Ativo' if ar.get('ativo') else '❌ Inativo'}`\n"
        f"🕐 `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
        f"\n╚══════════════════════════════╝",
        parse_mode='md'
    )

# ══════════════════════════════════════
#  BOT — CONSULTA NO PRIVADO
# ══════════════════════════════════════

@bot.on(events.NewMessage(func=lambda e: e.is_private and not e.raw_text.startswith('/')))
async def bot_private_query(event):
    """Consulta URL quando o usuário envia no privado do bot."""
    sender = await event.get_sender()
    register_user(
        event.sender_id,
        getattr(sender, 'first_name', '') or '',
        getattr(sender, 'last_name', '') or '',
        getattr(sender, 'username', None)
    )

    # Verifica estado de edição
    state = edit_states.get(event.sender_id)
    if state:
        await handle_edit_state(event, state)
        return

    # Verifica se é mensagem encaminhada (para identificar usuário)
    if event.sender_id == OWNER_ID and event.forward:
        fwd = event.forward
        fwd_id = getattr(fwd, 'sender_id', None) or getattr(fwd, 'from_id', None)
        if fwd_id:
            user = find_user(fwd_id)
            if user:
                await event.reply(
                    f"╔══════════════════════════════╗\n"
                    f"║   👤 USUÁRIO ENCONTRADO       ║\n"
                    f"╚══════════════════════════════╝\n"
                    f"\n"
                    f"👤 **Nome:** {user['nome']}\n"
                    f"🆔 **ID:** `{user['id']}`\n"
                    f"📎 **Username:** @{user.get('username', 'N/A')}\n"
                    f"📅 **Registrado:** `{user.get('registrado_em', 'N/D')}`\n"
                    f"🕐 **Último acesso:** `{user.get('ultimo_acesso', 'N/D')}`\n"
                    f"📊 **Interações:** `{user.get('interacoes', 0)}`\n"
                    f"\n╚══════════════════════════════╝",
                    parse_mode='md'
                )
            else:
                await event.reply(f"❌ Usuário `{fwd_id}` não encontrado no registro.", parse_mode='md')
            return

    # Verifica se o usuário pertence a algum grupo permitido (ou é o dono)
    if event.sender_id == OWNER_ID:
        allowed = True
    else:
        allowed = False
        groups = load_groups()
        for g in groups:
            try:
                participant = await bot(
                    GetParticipantRequest(g["id"], event.sender_id)
                )
                if participant:
                    allowed = True
                    break
            except (UserNotParticipantError, Exception):
                continue

    if not allowed:
        await event.reply(
            "⛔ **Acesso negado.**\n\n"
            f"Você precisa ser membro de um grupo autorizado.\n"
            f"Contato: {OWNER_CONTACT}",
            parse_mode='md'
        )
        return

    # Verifica se contém URL
    match = re.search(URL_PATTERN, event.raw_text)
    if not match:
        await event.reply(
            "📡 Envie uma **URL** válida para consultar.\n\n"
            "Ou use inline: `@InforUser_Bot URL`",
            parse_mode='md'
        )
        return

    url = match.group(1)
    sender_name = getattr(sender, 'first_name', '') or ''
    sender_last = getattr(sender, 'last_name', '') or ''
    sender_username = getattr(sender, 'username', None)

    processing_msg = await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║    ⏳ PROCESSANDO...          ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n📡 Aguarde...",
        parse_mode='md'
    )

    loop = asyncio.get_event_loop()
    result, error = await loop.run_in_executor(None, check_url, url)

    if error:
        await processing_msg.edit(
            f"╔══════════════════════════════╗\n"
            f"║     ❌ CONSULTA FALHOU        ║\n"
            f"╚══════════════════════════════╝\n"
            f"\n{error}",
            parse_mode='md'
        )
        return

    user_tag = f"@{sender_username}" if sender_username else f"`{event.sender_id}`"
    header = (
        f"👤 **Solicitante:** {sender_name} {sender_last}\n"
        f"🆔 **ID:** `{event.sender_id}`\n\n"
    )

    await processing_msg.edit(header + result, parse_mode='md')

    # Log no canal
    try:
        channel_msg = (
            f"📨 **Consulta (Privado Bot)**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **De:** {sender_name} {sender_last} ({user_tag})\n"
            f"🆔 **ID:** `{event.sender_id}`\n"
            f"🕐 **Data:** `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n{result}"
        )
        await bot.send_message(CANAL_RESULTADOS_ID, channel_msg, parse_mode='md')
    except Exception as e:
        print(f"[!] Erro ao enviar ao canal (privado): {e}")

# ══════════════════════════════════════
#  BOT — INLINE MODE (@InforUser_Bot + URL)
# ══════════════════════════════════════

@bot.on(events.InlineQuery)
async def bot_inline_handler(event):
    """Inline: @InforUser_Bot URL — mostra resultado inline."""
    query = event.text.strip()

    if not query:
        builder = event.builder
        article = builder.article(
            title="📡 Silva Automação PRO",
            description="Digite: @InforUser_Bot URL para consultar",
            text="📡 Use: `@InforUser_Bot URL` para consultar uma URL.",
            parse_mode='md'
        )
        await event.answer([article])
        return

    match = re.search(URL_PATTERN, query)
    if not match:
        builder = event.builder
        article = builder.article(
            title="❌ URL não detectada",
            description="Envie uma URL válida após @InforUser_Bot",
            text="❌ Envie uma URL válida.\nExemplo: `@InforUser_Bot http://...`",
            parse_mode='md'
        )
        await event.answer([article])
        return

    url = match.group(1)

    # Registra quem usou inline
    sender = await event.get_sender()
    register_user(
        event.sender_id,
        getattr(sender, 'first_name', '') or '',
        getattr(sender, 'last_name', '') or '',
        getattr(sender, 'username', None)
    )

    # Verifica se o usuário é permitido
    if event.sender_id == OWNER_ID:
        allowed = True
    else:
        allowed = False
        groups = load_groups()
        for g in groups:
            try:
                participant = await bot(
                    GetParticipantRequest(g["id"], event.sender_id)
                )
                if participant:
                    allowed = True
                    break
            except (UserNotParticipantError, Exception):
                continue

    if not allowed:
        await event.answer(
            results=[],
            switch_pm="⛔ Sem permissão. Entre em um grupo autorizado.",
            switch_pm_param="start"
        )
        return

    # Executa a consulta
    loop = asyncio.get_event_loop()
    result, error = await loop.run_in_executor(None, check_url, url)

    if error:
        builder = event.builder
        article = builder.article(
            title="❌ Consulta Falhou",
            description=error[:100],
            text=error,
            parse_mode='md'
        )
        await event.answer([article])
        return

    builder = event.builder
    article = builder.article(
        title="✅ Resultado da Consulta",
        description="Clique para enviar o resultado",
        text=result,
        parse_mode='md'
    )
    await event.answer([article])

    # Envia para o canal
    try:
        sender_name = getattr(sender, 'first_name', '') or ''
        sender_username = getattr(sender, 'username', None)
        user_tag = f"@{sender_username}" if sender_username else f"`{event.sender_id}`"
        channel_msg = (
            f"📨 **Consulta via Inline**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **De:** {sender_name} ({user_tag})\n"
            f"🆔 **ID:** `{event.sender_id}`\n"
            f"🕐 **Data:** `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n{result}"
        )
        await bot.send_message(CANAL_RESULTADOS_ID, channel_msg, parse_mode='md')
    except Exception as e:
        print(f"[!] Erro ao enviar ao canal (inline): {e}")

# ══════════════════════════════════════
#  BOT — AUTOMS PRO (com botões inline)
# ══════════════════════════════════════

AUTOMS_PER_PAGE = 5

def build_automs_page(page=0):
    automs = load_automs()
    total = len(automs)
    total_pages = max(1, math.ceil(total / AUTOMS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    start = page * AUTOMS_PER_PAGE
    end = start + AUTOMS_PER_PAGE
    page_automs = automs[start:end]

    text = (
        f"╔══════════════════════════════╗\n"
        f"║   💬 AUTOMS - RESPOSTAS AUTO  ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"📊 **Total:** `{total}` mensagem(ns)\n"
        f"📄 **Página:** `{page + 1}/{total_pages}`\n\n"
    )

    if not page_automs:
        text += "📭 Nenhuma mensagem automática cadastrada.\n"
    else:
        for i, am in enumerate(page_automs, start=start + 1):
            status = "✅" if am.get("ativa", True) else "❌"
            preview = am['message'][:50] + "..." if len(am['message']) > 50 else am['message']
            title_str = am.get('title') or '(sem título)'
            text += f"**{i}.** {status} 📌 **{title_str}**\n   _{preview}_\n\n"

    text += "╚══════════════════════════════╝"

    buttons = []
    for idx, am in enumerate(page_automs):
        real_idx = start + idx
        status_icon = "✅" if am.get("ativa", True) else "❌"
        buttons.append([
            Button.inline(f"👁 Ver", data=f"viewautom:{real_idx}"),
            Button.inline(f"✏️ Editar", data=f"editautom:{real_idx}"),
            Button.inline(f"{status_icon} On/Off", data=f"toggleautom:{real_idx}"),
            Button.inline(f"🗑", data=f"rmautom:{real_idx}")
        ])

    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀️ Voltar", data=f"autompage:{page - 1}"))
    if total > 0:
        nav_row.append(Button.inline(f"📄 {page + 1}/{total_pages}", data="noop"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("Avançar ▶️", data=f"autompage:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        Button.inline("➕ Adicionar", data="addautom_prompt"),
        Button.inline("🔄 Atualizar", data="autompage:0"),
        Button.inline("⛔ Fechar", data="close_panel")
    ])

    return text, buttons

@bot.on(events.NewMessage(pattern=r'^/automs$'))
async def bot_automs(event):
    if event.sender_id != OWNER_ID:
        return
    text, buttons = build_automs_page(0)
    await event.reply(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^autompage:(\d+)$'))
async def bot_callback_autom_page(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    page = int(event.pattern_match.group(1))
    text, buttons = build_automs_page(page)
    await event.edit(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^viewautom:(\d+)$'))
async def bot_callback_view_autom(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    automs = load_automs()
    if 0 <= idx < len(automs):
        am = automs[idx]
        status = "✅ Ativa" if am.get("ativa", True) else "❌ Inativa"
        title_str = am.get('title') or '(sem título)'
        await event.answer()
        await event.reply(
            f"╔══════════════════════════════╗\n"
            f"║   📌 AUTOM #{idx + 1}                ║\n"
            f"╚══════════════════════════════╝\n"
            f"\n"
            f"📋 **Título:** {title_str}\n"
            f"📊 **Status:** {status}\n"
            f"📅 **Criada:** {am.get('criada_em', 'N/D')}\n\n"
            f"💬 **Mensagem:**\n{am['message']}\n"
            f"\n╚══════════════════════════════╝",
            buttons=[
                [
                    Button.inline("✏️ Editar", data=f"editautom:{idx}"),
                    Button.inline("🔄 On/Off", data=f"toggleautom:{idx}"),
                    Button.inline("🗑 Apagar", data=f"rmautom:{idx}")
                ],
                [Button.inline("📤 Enviar", data=f"sendautom:{idx}"),
                 Button.inline("◀️ Voltar", data="autompage:0")]
            ],
            parse_mode='md'
        )
    else:
        await event.answer("❌ Mensagem não encontrada.", alert=True)

@bot.on(events.CallbackQuery(pattern=r'^toggleautom:(\d+)$'))
async def bot_callback_toggle_autom(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    toggled = toggle_autom(idx)
    if toggled:
        status = "✅ Ativada" if toggled.get("ativa") else "❌ Desativada"
        await event.answer(f"{status}: {toggled.get('title', 'msg')}", alert=True)
    else:
        await event.answer("❌ Não encontrada.", alert=True)
    text, buttons = build_automs_page(0)
    await event.edit(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^editautom:(\d+)$'))
async def bot_callback_edit_autom(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    automs = load_automs()
    if 0 <= idx < len(automs):
        edit_states[event.sender_id] = {"action": "edit_autom", "index": idx, "step": "choose"}
        await event.answer()
        await event.reply(
            f"✏️ **Editando AutoM #{idx + 1}**\n\n"
            f"O que deseja editar?",
            buttons=[
                [Button.inline("📋 Título", data=f"editfield:title:{idx}"),
                 Button.inline("💬 Mensagem", data=f"editfield:message:{idx}")],
                [Button.inline("❌ Cancelar", data="canceledit")]
            ],
            parse_mode='md'
        )
    else:
        await event.answer("❌ Não encontrada.", alert=True)

@bot.on(events.CallbackQuery(pattern=r'^editfield:(title|message):(\d+)$'))
async def bot_callback_edit_field(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    field = event.pattern_match.group(1)
    idx = int(event.pattern_match.group(2))

    edit_states[event.sender_id] = {"action": "edit_autom", "index": idx, "step": "waiting", "field": field}
    await event.answer()

    field_name = "título" if field == "title" else "mensagem"
    await event.reply(
        f"✏️ Envie o novo **{field_name}** para a AutoM #{idx + 1}:\n\n"
        f"(Envie qualquer texto ou /cancelar)",
        parse_mode='md'
    )

@bot.on(events.CallbackQuery(pattern=r'^canceledit$'))
async def bot_callback_cancel_edit(event):
    edit_states.pop(event.sender_id, None)
    await event.answer("❌ Edição cancelada.")
    await event.delete()

# Enviar AutoM para um chat
@bot.on(events.CallbackQuery(pattern=r'^sendautom:(\d+)$'))
async def bot_callback_send_autom(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    automs = load_automs()
    if 0 <= idx < len(automs):
        edit_states[event.sender_id] = {"action": "send_autom", "index": idx, "step": "waiting_target"}
        await event.answer()
        await event.reply(
            f"📤 **Enviar AutoM #{idx + 1}**\n\n"
            f"Envie o **ID do chat** ou **@username** do destinatário:\n\n"
            f"💡 Pode enviar para usuário ou grupo.\n"
            f"Envie /cancelar para desistir.",
            parse_mode='md'
        )
    else:
        await event.answer("❌ Não encontrada.", alert=True)

# Fechar painel
@bot.on(events.CallbackQuery(pattern=r'^close_panel$'))
async def bot_callback_close(event):
    await event.answer("✅ Painel fechado.")
    await event.delete()

async def handle_edit_state(event, state):
    """Processa estados de edição/envio em andamento."""
    if event.raw_text == "/cancelar":
        edit_states.pop(event.sender_id, None)
        await event.reply("❌ Operação cancelada.")
        return

    # --- Edit AutoM ---
    if state["action"] == "edit_autom" and state["step"] == "waiting":
        idx = state["index"]
        field = state["field"]
        new_value = event.raw_text.strip()

        if field == "title":
            updated = update_autom(idx, title=new_value)
        else:
            updated = update_autom(idx, message=new_value)

        edit_states.pop(event.sender_id, None)

        if updated:
            field_name = "Título" if field == "title" else "Mensagem"
            await event.reply(
                f"✅ **{field_name} atualizado!**\n\n"
                f"📌 **Título:** {updated.get('title') or '(sem título)'}\n"
                f"💬 **Preview:** {updated['message'][:80]}...\n\n"
                f"Use /automs para gerenciar.",
                parse_mode='md'
            )
        else:
            await event.reply("❌ Erro ao atualizar.", parse_mode='md')

    # --- Set Auto-Reply ---
    elif state["action"] == "set_autoreply":
        new_msg = event.raw_text.strip()
        set_autoreply(True, new_msg)
        edit_states.pop(event.sender_id, None)
        await event.reply(
            f"✅ **Auto-Reply configurado e ativado!**\n\n"
            f"💬 **Mensagem:**\n{new_msg}\n\n"
            f"Use /autoreply para gerenciar.",
            parse_mode='md'
        )

    # --- Edit Msg Pronta ---
    elif state["action"] == "edit_msgpronta" and state["step"] == "waiting":
        idx = state["index"]
        field = state["field"]
        new_value = event.raw_text.strip()

        if field == "title":
            updated = update_msg_pronta(idx, title=new_value)
        else:
            updated = update_msg_pronta(idx, message=new_value)

        edit_states.pop(event.sender_id, None)

        if updated:
            field_name = "Título" if field == "title" else "Mensagem"
            await event.reply(
                f"✅ **{field_name} atualizado!**\n\n"
                f"📌 **Título:** {updated.get('title') or '(sem título)'}\n"
                f"💬 **Preview:** {updated['message'][:80]}...\n\n"
                f"Use /msgprontas para gerenciar.",
                parse_mode='md'
            )
        else:
            await event.reply("❌ Erro ao atualizar.", parse_mode='md')

    # --- Add Msg Pronta step by step ---
    elif state["action"] == "add_msgpronta":
        if state["step"] == "title":
            title = event.raw_text.strip()
            edit_states[event.sender_id] = {"action": "add_msgpronta", "step": "message", "title": title}
            await event.reply(
                f"📋 Título: **{title or '(vazio)'}**\n\n"
                f"Agora envie a **mensagem** (suporta Markdown):\n\n"
                f"Envie /cancelar para desistir.",
                parse_mode='md'
            )
        elif state["step"] == "message":
            message = event.raw_text.strip()
            title = state.get("title", "")
            if not message:
                await event.reply("❌ A mensagem não pode estar vazia.")
                return
            count = add_msg_pronta(title, message)
            edit_states.pop(event.sender_id, None)
            await event.reply(
                f"✅ **Mensagem pronta adicionada!**\n\n"
                f"📌 **Título:** {title or '(sem título)'}\n"
                f"💬 **Preview:** {message[:80]}{'...' if len(message) > 80 else ''}\n"
                f"📊 **Total:** `{count}`\n\n"
                f"Use /msgprontas para gerenciar.",
                buttons=[
                    [Button.inline("👁 Review", data=f"viewmp:{count - 1}"),
                     Button.inline("📝 Lista", data="mppage:0")]
                ],
                parse_mode='md'
            )

    # --- Send AutoM to target ---
    elif state["action"] == "send_autom" and state["step"] == "waiting_target":
        target = event.raw_text.strip()
        idx = state["index"]
        automs = load_automs()
        edit_states.pop(event.sender_id, None)

        if 0 <= idx < len(automs):
            am = automs[idx]
            try:
                # Tenta resolver target
                if target.startswith("@"):
                    entity = await bot.get_entity(target)
                elif target.lstrip("-").isdigit():
                    entity = await bot.get_entity(int(target))
                else:
                    entity = await bot.get_entity(target)

                msg_text = ""
                if am.get("title"):
                    msg_text += f"📌 **{am['title']}**\n\n"
                msg_text += am["message"]

                await bot.send_message(entity, msg_text, parse_mode='md')
                target_name = getattr(entity, 'title', None) or getattr(entity, 'first_name', str(target))
                await event.reply(
                    f"✅ **Mensagem enviada!**\n\n"
                    f"📌 **AutoM:** {am.get('title') or '(sem título)'}\n"
                    f"📤 **Para:** {target_name}",
                    parse_mode='md'
                )
            except Exception as e:
                await event.reply(f"❌ Erro ao enviar: `{str(e)[:100]}`", parse_mode='md')
        else:
            await event.reply("❌ AutoM não encontrada.", parse_mode='md')

    # --- Send Msg Pronta to target ---
    elif state["action"] == "send_msgpronta" and state["step"] == "waiting_target":
        target = event.raw_text.strip()
        idx = state["index"]
        msgs = load_msgs_prontas()
        edit_states.pop(event.sender_id, None)

        if 0 <= idx < len(msgs):
            mp = msgs[idx]
            try:
                if target.startswith("@"):
                    entity = await bot.get_entity(target)
                elif target.lstrip("-").isdigit():
                    entity = await bot.get_entity(int(target))
                else:
                    entity = await bot.get_entity(target)

                msg_text = ""
                if mp.get("title"):
                    msg_text += f"📌 **{mp['title']}**\n\n"
                msg_text += mp["message"]

                await bot.send_message(entity, msg_text, parse_mode='md')
                target_name = getattr(entity, 'title', None) or getattr(entity, 'first_name', str(target))
                await event.reply(
                    f"✅ **Mensagem pronta enviada!**\n\n"
                    f"📌 **Msg:** {mp.get('title') or '(sem título)'}\n"
                    f"📤 **Para:** {target_name}",
                    parse_mode='md'
                )
            except Exception as e:
                await event.reply(f"❌ Erro ao enviar: `{str(e)[:100]}`", parse_mode='md')
        else:
            await event.reply("❌ Mensagem pronta não encontrada.", parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^rmautom:(\d+)$'))
async def bot_callback_remove_autom(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    removed = remove_autom(idx)
    if removed:
        await event.answer(f"✅ AutoM '{removed.get('title', 'msg')}' removida!", alert=True)
    else:
        await event.answer("❌ Não encontrada.", alert=True)
    text, buttons = build_automs_page(0)
    await event.edit(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^addautom_prompt$'))
async def bot_callback_add_autom_prompt(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    await event.answer()
    await event.reply(
        "╔══════════════════════════════╗\n"
        "║   ➕ ADICIONAR AUTOM          ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "Envie no formato:\n"
        "`/addautom Título | Mensagem`\n\n"
        "💡 Título é **opcional**:\n"
        "`/addautom | Apenas a mensagem`\n"
        "\n╚══════════════════════════════╝",
        parse_mode='md'
    )

@bot.on(events.NewMessage(pattern=r'^/addautom\s+(.+)$'))
async def bot_add_autom(event):
    if event.sender_id != OWNER_ID:
        return

    text = event.pattern_match.group(1).strip()
    if '|' in text:
        parts = text.split('|', 1)
        title = parts[0].strip()
        message = parts[1].strip()
    else:
        title = ""
        message = text

    if not message:
        await event.reply("❌ A mensagem não pode estar vazia.", parse_mode='md')
        return

    count = add_autom(title, message)
    title_str = title or "(sem título)"
    await event.reply(
        f"✅ **AutoM adicionada!**\n\n"
        f"📌 **Título:** {title_str}\n"
        f"💬 **Preview:** {message[:80]}{'...' if len(message) > 80 else ''}\n"
        f"📊 **Total:** `{count}` mensagem(ns)\n\n"
        f"Use /automs para gerenciar.",
        parse_mode='md'
    )

# ══════════════════════════════════════
#  BOT — MENSAGENS PRONTAS PRO
#  (pré-configuradas com envio direto)
# ══════════════════════════════════════

MSGS_PER_PAGE = 5

def build_msgs_prontas_page(page=0):
    msgs = load_msgs_prontas()
    total = len(msgs)
    total_pages = max(1, math.ceil(total / MSGS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    start = page * MSGS_PER_PAGE
    end = start + MSGS_PER_PAGE
    page_msgs = msgs[start:end]

    text = (
        f"╔══════════════════════════════╗\n"
        f"║   📝 MENSAGENS PRONTAS        ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"📊 **Total:** `{total}` mensagem(ns)\n"
        f"📄 **Página:** `{page + 1}/{total_pages}`\n\n"
    )

    if not page_msgs:
        text += "📭 Nenhuma mensagem pronta cadastrada.\n"
    else:
        for i, mp in enumerate(page_msgs, start=start + 1):
            status = "✅" if mp.get("ativa", True) else "❌"
            preview = mp['message'][:50] + "..." if len(mp['message']) > 50 else mp['message']
            title_str = mp.get('title') or '(sem título)'
            text += f"**{i}.** {status} 📌 **{title_str}**\n   _{preview}_\n\n"

    text += "╚══════════════════════════════╝"

    buttons = []
    for idx, mp in enumerate(page_msgs):
        real_idx = start + idx
        status_icon = "✅" if mp.get("ativa", True) else "❌"
        buttons.append([
            Button.inline(f"👁 Ver", data=f"viewmp:{real_idx}"),
            Button.inline(f"✏️ Edit", data=f"editmp:{real_idx}"),
            Button.inline(f"📤 Enviar", data=f"sendmp:{real_idx}"),
            Button.inline(f"🗑", data=f"rmmp:{real_idx}")
        ])

    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀️ Voltar", data=f"mppage:{page - 1}"))
    if total > 0:
        nav_row.append(Button.inline(f"📄 {page + 1}/{total_pages}", data="noop"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("Avançar ▶️", data=f"mppage:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        Button.inline("➕ Adicionar", data="addmp_prompt"),
        Button.inline("🔄 Atualizar", data="mppage:0"),
        Button.inline("⛔ Fechar", data="close_panel")
    ])

    return text, buttons

@bot.on(events.NewMessage(pattern=r'^/msgprontas$'))
async def bot_msgs_prontas(event):
    if event.sender_id != OWNER_ID:
        return
    text, buttons = build_msgs_prontas_page(0)
    await event.reply(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^mppage:(\d+)$'))
async def bot_callback_mp_page(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    page = int(event.pattern_match.group(1))
    text, buttons = build_msgs_prontas_page(page)
    await event.edit(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^viewmp:(\d+)$'))
async def bot_callback_view_mp(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    msgs = load_msgs_prontas()
    if 0 <= idx < len(msgs):
        mp = msgs[idx]
        status = "✅ Ativa" if mp.get("ativa", True) else "❌ Inativa"
        title_str = mp.get('title') or '(sem título)'
        await event.answer()
        await event.reply(
            f"╔══════════════════════════════╗\n"
            f"║   📝 MSG PRONTA #{idx + 1}           ║\n"
            f"╚══════════════════════════════╝\n"
            f"\n"
            f"📋 **Título:** {title_str}\n"
            f"📊 **Status:** {status}\n"
            f"📅 **Criada:** {mp.get('criada_em', 'N/D')}\n\n"
            f"💬 **Mensagem:**\n{mp['message']}\n"
            f"\n╚══════════════════════════════╝",
            buttons=[
                [
                    Button.inline("✏️ Editar", data=f"editmp:{idx}"),
                    Button.inline("📤 Enviar", data=f"sendmp:{idx}"),
                    Button.inline("🗑 Apagar", data=f"rmmp:{idx}")
                ],
                [Button.inline("◀️ Voltar", data="mppage:0")]
            ],
            parse_mode='md'
        )
    else:
        await event.answer("❌ Não encontrada.", alert=True)

@bot.on(events.CallbackQuery(pattern=r'^editmp:(\d+)$'))
async def bot_callback_edit_mp(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    msgs = load_msgs_prontas()
    if 0 <= idx < len(msgs):
        await event.answer()
        await event.reply(
            f"✏️ **Editando Msg Pronta #{idx + 1}**\n\nO que deseja editar?",
            buttons=[
                [Button.inline("📋 Título", data=f"editmpfield:title:{idx}"),
                 Button.inline("💬 Mensagem", data=f"editmpfield:message:{idx}")],
                [Button.inline("❌ Cancelar", data="canceledit")]
            ],
            parse_mode='md'
        )
    else:
        await event.answer("❌ Não encontrada.", alert=True)

@bot.on(events.CallbackQuery(pattern=r'^editmpfield:(title|message):(\d+)$'))
async def bot_callback_edit_mp_field(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    field = event.pattern_match.group(1)
    idx = int(event.pattern_match.group(2))
    edit_states[event.sender_id] = {"action": "edit_msgpronta", "index": idx, "step": "waiting", "field": field}
    await event.answer()
    field_name = "título" if field == "title" else "mensagem"
    await event.reply(
        f"✏️ Envie o novo **{field_name}** para a Msg Pronta #{idx + 1}:\n\n"
        f"(Envie qualquer texto ou /cancelar)",
        parse_mode='md'
    )

@bot.on(events.CallbackQuery(pattern=r'^sendmp:(\d+)$'))
async def bot_callback_send_mp(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    msgs = load_msgs_prontas()
    if 0 <= idx < len(msgs):
        edit_states[event.sender_id] = {"action": "send_msgpronta", "index": idx, "step": "waiting_target"}
        await event.answer()
        await event.reply(
            f"📤 **Enviar Msg Pronta #{idx + 1}**\n\n"
            f"Envie o **ID do chat** ou **@username** do destinatário:\n\n"
            f"Envie /cancelar para desistir.",
            parse_mode='md'
        )
    else:
        await event.answer("❌ Não encontrada.", alert=True)

@bot.on(events.CallbackQuery(pattern=r'^rmmp:(\d+)$'))
async def bot_callback_remove_mp(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    idx = int(event.pattern_match.group(1))
    removed = remove_msg_pronta(idx)
    if removed:
        await event.answer(f"✅ Msg '{removed.get('title', 'msg')}' removida!", alert=True)
    else:
        await event.answer("❌ Não encontrada.", alert=True)
    text, buttons = build_msgs_prontas_page(0)
    await event.edit(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^addmp_prompt$'))
async def bot_callback_add_mp_prompt(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    await event.answer()
    await event.reply(
        "╔══════════════════════════════╗\n"
        "║   ➕ ADICIONAR MSG PRONTA     ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "**Opção 1** - Comando rápido:\n"
        "`/addmsg Título | Mensagem`\n\n"
        "**Opção 2** - Passo a passo:\n"
        "Clique abaixo para iniciar.",
        buttons=[
            [Button.inline("📝 Criar passo a passo", data="addmp_wizard")],
            [Button.inline("❌ Cancelar", data="close_panel")]
        ],
        parse_mode='md'
    )

@bot.on(events.CallbackQuery(pattern=r'^addmp_wizard$'))
async def bot_callback_add_mp_wizard(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    edit_states[event.sender_id] = {"action": "add_msgpronta", "step": "title", "title": "", "message": ""}
    await event.answer()
    await event.reply(
        "📋 **Passo 1/2 — Título**\n\n"
        "Envie o **título** da mensagem pronta:\n"
        "(Pode enviar vazio para pular)\n\n"
        "Envie /cancelar para desistir.",
        parse_mode='md'
    )

@bot.on(events.NewMessage(pattern=r'^/addmsg\s+(.+)$'))
async def bot_add_msg_pronta(event):
    if event.sender_id != OWNER_ID:
        return

    text = event.pattern_match.group(1).strip()
    if '|' in text:
        parts = text.split('|', 1)
        title = parts[0].strip()
        message = parts[1].strip()
    else:
        title = ""
        message = text

    if not message:
        await event.reply("❌ A mensagem não pode estar vazia.", parse_mode='md')
        return

    count = add_msg_pronta(title, message)
    title_str = title or "(sem título)"
    await event.reply(
        f"✅ **Mensagem pronta adicionada!**\n\n"
        f"📌 **Título:** {title_str}\n"
        f"💬 **Preview:** {message[:80]}{'...' if len(message) > 80 else ''}\n"
        f"📊 **Total:** `{count}`\n\n"
        f"Use /msgprontas para gerenciar.",
        buttons=[
            [Button.inline("👁 Review", data=f"viewmp:{count - 1}"),
             Button.inline("📝 Lista", data="mppage:0")]
        ],
        parse_mode='md'
    )

# ══════════════════════════════════════
#  BOT — AUTO-REPLY PANEL
# ══════════════════════════════════════

def build_autoreply_panel():
    ar = load_autoreply()
    status = "✅ ATIVO" if ar.get("ativo") else "❌ INATIVO"
    msg_preview = ar.get("mensagem", "")[:100] or "(nenhuma mensagem configurada)"

    text = (
        f"╔══════════════════════════════╗\n"
        f"║   🔄 AUTO-REPLY EM DMs        ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"📊 **Status:** {status}\n"
        f"💬 **Mensagem:**\n_{msg_preview}_\n"
        f"\nQuando ativo, responde automaticamente\n"
        f"a qualquer pessoa que iniciar DM.\n"
        f"\n╚══════════════════════════════╝"
    )

    is_active = ar.get("ativo", False)
    buttons = [
        [
            Button.inline("✅ Ativar" if not is_active else "❌ Desativar", data="ar_toggle"),
            Button.inline("✏️ Editar Mensagem", data="ar_edit")
        ],
        [Button.inline("👁 Ver Completa", data="ar_view"),
         Button.inline("⛔ Fechar", data="close_panel")]
    ]

    return text, buttons

@bot.on(events.NewMessage(pattern=r'^/autoreply$'))
async def bot_autoreply(event):
    if event.sender_id != OWNER_ID:
        return
    text, buttons = build_autoreply_panel()
    await event.reply(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^ar_panel$'))
async def bot_callback_ar_panel(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    text, buttons = build_autoreply_panel()
    try:
        await event.edit(text, buttons=buttons, parse_mode='md')
    except Exception:
        await event.answer()
        await event.reply(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^ar_toggle$'))
async def bot_callback_ar_toggle(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    ar = load_autoreply()
    new_state = not ar.get("ativo", False)
    set_autoreply(new_state)
    status = "✅ Ativado" if new_state else "❌ Desativado"
    await event.answer(f"Auto-Reply {status}!", alert=True)
    text, buttons = build_autoreply_panel()
    await event.edit(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^ar_edit$'))
async def bot_callback_ar_edit(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    edit_states[event.sender_id] = {"action": "set_autoreply", "step": "waiting"}
    await event.answer()
    await event.reply(
        "✏️ **Envie a nova mensagem de auto-reply:**\n\n"
        "Suporta **Markdown**.\n"
        "Envie /cancelar para desistir.",
        parse_mode='md'
    )

@bot.on(events.CallbackQuery(pattern=r'^ar_view$'))
async def bot_callback_ar_view(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    ar = load_autoreply()
    msg = ar.get("mensagem", "(vazia)")
    await event.answer()
    await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║   💬 MENSAGEM AUTO-REPLY      ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n{msg}\n"
        f"\n╚══════════════════════════════╝",
        parse_mode='md'
    )

# ══════════════════════════════════════
#  BOT — GESTÃO DE USUÁRIOS
# ══════════════════════════════════════

USERS_PER_PAGE = 8

def build_users_page(page=0):
    users = load_users()
    total = len(users)
    total_pages = max(1, math.ceil(total / USERS_PER_PAGE))
    page = max(0, min(page, total_pages - 1))

    start = page * USERS_PER_PAGE
    end = start + USERS_PER_PAGE
    page_users = users[start:end]

    text = (
        f"╔══════════════════════════════╗\n"
        f"║   👥 USUÁRIOS REGISTRADOS     ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"📊 **Total:** `{total}` usuário(s)\n"
        f"📄 **Página:** `{page + 1}/{total_pages}`\n\n"
    )

    if not page_users:
        text += "📭 Nenhum usuário registrado.\n"
    else:
        for i, u in enumerate(page_users, start=start + 1):
            uname = f"@{u['username']}" if u.get('username') else "N/A"
            text += f"**{i}.** `{u['id']}` — {u['nome']} ({uname})\n"

    text += f"\n╚══════════════════════════════╝"

    buttons = []
    nav_row = []
    if page > 0:
        nav_row.append(Button.inline("◀️ Voltar", data=f"userspage:{page - 1}"))
    nav_row.append(Button.inline(f"📄 {page + 1}/{total_pages}", data="noop"))
    if page < total_pages - 1:
        nav_row.append(Button.inline("Avançar ▶️", data=f"userspage:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([
        Button.inline("🔄 Atualizar", data="userspage:0"),
        Button.inline("⛔ Fechar", data="close_panel")
    ])

    return text, buttons

@bot.on(events.NewMessage(pattern=r'^/usuarios$'))
async def bot_usuarios(event):
    if event.sender_id != OWNER_ID:
        return
    text, buttons = build_users_page(0)
    await event.reply(text, buttons=buttons, parse_mode='md')

@bot.on(events.CallbackQuery(pattern=r'^userspage:(\d+)$'))
async def bot_callback_users_page(event):
    if event.sender_id != OWNER_ID:
        await event.answer("⛔ Sem permissão.", alert=True)
        return
    page = int(event.pattern_match.group(1))
    text, buttons = build_users_page(page)
    await event.edit(text, buttons=buttons, parse_mode='md')

# ---------- BOT: /broadcast ----------
@bot.on(events.NewMessage(pattern=r'^/broadcast\s+(.+)$'))
async def bot_broadcast(event):
    if event.sender_id != OWNER_ID:
        return
    msg = event.pattern_match.group(1).strip()
    users = load_users()
    sent = 0
    failed = 0

    status_msg = await event.reply(
        f"📣 **Broadcast em andamento...**\n\n"
        f"📊 Total: `{len(users)}` usuário(s)\n"
        f"⏳ Enviando...",
        parse_mode='md'
    )

    for u in users:
        try:
            await bot.send_message(u["id"], msg, parse_mode='md')
            sent += 1
        except Exception:
            failed += 1

    await status_msg.edit(
        f"╔══════════════════════════════╗\n"
        f"║   📣 BROADCAST CONCLUÍDO      ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"✅ **Enviados:** `{sent}`\n"
        f"❌ **Falharam:** `{failed}`\n"
        f"📊 **Total:** `{len(users)}`\n"
        f"\n╚══════════════════════════════╝",
        parse_mode='md'
    )

# ══════════════════════════════════════
#  USERBOT — COMANDOS DO DONO (via userbot)
# ══════════════════════════════════════

@userbot.on(events.NewMessage(pattern=r'^[!/]grupos$', outgoing=True))
async def ub_cmd_grupos(event):
    text, buttons = build_groups_page(0)
    await event.reply(text, buttons=buttons, parse_mode='md')

@userbot.on(events.CallbackQuery(pattern=r'^grppage:(\d+)$'))
async def ub_callback_page(event):
    me = await userbot.get_me()
    if event.sender_id != me.id:
        return
    page = int(event.pattern_match.group(1))
    text, buttons = build_groups_page(page)
    await event.edit(text, buttons=buttons, parse_mode='md')

@userbot.on(events.CallbackQuery(pattern=r'^rmgrp:(-?\d+)$'))
async def ub_callback_remove(event):
    me = await userbot.get_me()
    if event.sender_id != me.id:
        return
    gid = int(event.pattern_match.group(1))
    remove_group(gid)
    text, buttons = build_groups_page(0)
    await event.edit(text, buttons=buttons, parse_mode='md')

@userbot.on(events.CallbackQuery(pattern=r'^addgrp$'))
async def ub_callback_add(event):
    me = await userbot.get_me()
    if event.sender_id != me.id:
        return
    await event.answer()
    await event.reply(
        "Envie: `/addgrupo -100123456`\n💡 Nome será detectado automaticamente.",
        parse_mode='md'
    )

@userbot.on(events.CallbackQuery(pattern=r'^noop$'))
async def ub_callback_noop(event):
    await event.answer()

@userbot.on(events.NewMessage(pattern=r'^[!/]addgrupo\s+(-?\d+)(?:\s+(.+))?$', outgoing=True))
async def ub_add_group(event):
    gid = int(event.pattern_match.group(1))
    name = event.pattern_match.group(2)

    if not name:
        try:
            entity = await userbot.get_entity(gid)
            name = getattr(entity, 'title', None) or getattr(entity, 'first_name', 'Grupo')
        except Exception:
            name = f"Grupo {gid}"

    name = name.strip()
    added = add_group(gid, name)
    if added:
        await event.reply(f"✅ Grupo **{name}** (`{gid}`) adicionado!", parse_mode='md')
    else:
        await event.reply(f"⚠️ Grupo `{gid}` já cadastrado.", parse_mode='md')

@userbot.on(events.NewMessage(pattern=r'^[!/]id$', outgoing=True))
async def ub_get_id(event):
    chat = await event.get_chat()
    chat_name = getattr(chat, 'title', None) or getattr(chat, 'first_name', 'N/A')
    await event.reply(
        f"🆔 **Chat:** `{event.chat_id}`\n📋 **Nome:** {chat_name}",
        parse_mode='md'
    )

@userbot.on(events.NewMessage(pattern=r'^[!/]help$', outgoing=True))
async def ub_help(event):
    await event.reply(
        "╔══════════════════════════════╗\n"
        "║   📖 COMANDOS DO USERBOT      ║\n"
        "╚══════════════════════════════╝\n"
        "\n"
        "🔹 `/grupos` — Gestão de grupos\n"
        "🔹 `/addgrupo <id>` — Adicionar grupo\n"
        "🔹 `/id` — Ver ID do chat\n"
        "🔹 `/status` — Status\n"
        "🔹 `/help` — Ajuda\n"
        "\n📡 Responda minha mensagem com URL para consultar.\n"
        "📡 Use `@InforUser_Bot URL` em grupos permitidos.\n"
        "\n╚══════════════════════════════╝",
        parse_mode='md'
    )

@userbot.on(events.NewMessage(pattern=r'^[!/]status$', outgoing=True))
async def ub_status(event):
    me = await userbot.get_me()
    groups = load_groups()
    automs = load_automs()
    users = load_users()
    ar = load_autoreply()
    msgs = load_msgs_prontas()
    await event.reply(
        f"╔══════════════════════════════╗\n"
        f"║   📊 STATUS DO SISTEMA        ║\n"
        f"╚══════════════════════════════╝\n"
        f"\n"
        f"✅ **Userbot + Bot Online**\n"
        f"👤 {me.first_name} (@{me.username or 'N/A'})\n"
        f"📋 **Grupos:** `{len(groups)}`\n"
        f"💬 **AutoMs:** `{len(automs)}`\n"
        f"📝 **Msgs Prontas:** `{len(msgs)}`\n"
        f"👥 **Usuários:** `{len(users)}`\n"
        f"🔄 **Auto-Reply:** `{'✅' if ar.get('ativo') else '❌'}`\n"
        f"🕐 `{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}`\n"
        f"\n╚══════════════════════════════╝",
        parse_mode='md'
    )

# ══════════════════════════════════════
#  INICIALIZAÇÃO (USERBOT + BOT JUNTOS)
# ══════════════════════════════════════

async def main():
    await userbot.start(phone=PHONE)
    me = await userbot.get_me()

    print("╔══════════════════════════════════════════╗")
    print("║   ✅ USERBOT SILVA AUTOMAÇÃO ONLINE       ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  👤 {me.first_name} (@{me.username or 'N/A'})")
    print(f"  🆔 {me.id}")
    print(f"  📋 Grupos: {len(load_groups())}")
    print(f"  💬 AutoMs: {len(load_automs())}")
    print(f"  📝 Msgs Prontas: {len(load_msgs_prontas())}")
    print(f"  👥 Usuários: {len(load_users())}")
    print("═══════════════════════════════════════════")

    await bot.start(bot_token=BOT_TOKEN)
    bot_me = await bot.get_me()

    print("╔══════════════════════════════════════════╗")
    print("║   🤖 @InforUser_Bot AUTOMAÇÃO ONLINE      ║")
    print("╚══════════════════════════════════════════╝")
    print(f"  🤖 {bot_me.first_name} (@{bot_me.username or 'N/A'})")
    print(f"  🆔 {bot_me.id}")
    print("═══════════════════════════════════════════")
    print()
    print("🚀 Sistema de Automação PRO rodando!")
    print("   Userbot + Bot + Inline + AutoMs + Msgs Prontas + AutoReply")
    print(f"   👤 Dono: Edivaldo Silva ({OWNER_ID})")
    print()

    await asyncio.gather(
        userbot.run_until_disconnected(),
        bot.run_until_disconnected()
    )

if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())
