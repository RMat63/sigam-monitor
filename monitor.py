#!/usr/bin/env python3
"""
Robô de monitoramento de processos no Sigam/Naturatins — consulta pública.

- Sem login nem senha: usa
  https://sigam.to.gov.br/cadastrousuarioexterno/consulta_documento_processo.aspx
- A cada execução: lê comandos recebidos no Telegram, consulta cada processo,
  compara com a última leitura, avisa no Telegram qualquer mudança, grava o
  histórico e atualiza o painel STATUS.md.
- Avisa quando ele próprio falha (silêncio nunca = "sem movimentação").

Comandos no Telegram (respondidos na execução seguinte):
  /status                         status de todos os processos
  /processo 2026/40311/011248     status e histórico de um processo
  /add 2026/40311/011248 Apelido  passa a monitorar um processo
  /remover 2026/40311/011248      deixa de monitorar
  /ajuda                          lista de comandos

Configuração (GitHub › Settings › Secrets and variables › Actions):
  Secret   TELEGRAM_TOKEN   token do @BotFather (obrigatório)
  Variable TELEGRAM_CHAT_ID opcional; se vazio, o 1º chat que falar com o bot
"""
import datetime as dt
import json
import os
import re
import sys
import traceback
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

URL_CONSULTA = "https://sigam.to.gov.br/cadastrousuarioexterno/consulta_documento_processo.aspx"
PROCESSOS_INICIAIS = {
    "2026/40311/011248": "Colinas – LP",
    "2026/40311/015485": "Colinas – AEF",
    "2025/40311/012702": "Formoso do Araguaia – LP",
    "2026/40311/003571": "Formoso do Araguaia – AEF",
}
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
TG_CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
MODO = (os.environ.get("MODO") or "monitorar").strip().lower()
ARQ_ESTADO = Path("estado/estado.json")
ARQ_PAINEL = Path("STATUS.md")
FUSO = dt.timezone(dt.timedelta(hours=-3))
INTERVALO_AVISO_FALHA_H = 6
MAX_HISTORICO = 50
CAMPOS = ("tipo", "departamento", "interessado", "assunto", "situacao")
NOMES = {"tipo": "Tipo", "departamento": "Departamento", "interessado": "Interessado",
         "assunto": "Assunto", "situacao": "Situação"}
RE_NUM = re.compile(r"\d{4}/\d+/\d+")
API_TG = "https://api.telegram.org/bot{}/{}"


def agora():
    return dt.datetime.now(FUSO)


def carimbo(m):
    return m.strftime("%d/%m/%Y %H:%M")


# ---------------- estado ----------------
def carregar_estado():
    try:
        e = json.loads(ARQ_ESTADO.read_text(encoding="utf-8"))
    except Exception:
        e = {}
    e.setdefault("monitorados", dict(PROCESSOS_INICIAIS))
    e.setdefault("leituras", {})
    e.setdefault("historico", {})
    return e


def salvar_estado(estado):
    ARQ_ESTADO.parent.mkdir(parents=True, exist_ok=True)
    ARQ_ESTADO.write_text(json.dumps(estado, ensure_ascii=False, indent=1, sort_keys=True),
                          encoding="utf-8")


# ---------------- Telegram ----------------
def tg_api(metodo, **dados):
    r = requests.post(API_TG.format(TG_TOKEN, metodo), data=dados, timeout=40)
    r.raise_for_status()
    return r.json()


def tg(msg):
    for i in range(0, len(msg), 3900):
        tg_api("sendMessage", chat_id=TG_CHAT, text=msg[i:i + 3900],
               disable_web_page_preview="true")


def ler_comandos(estado):
    """Lê mensagens novas do bot. Só aceita comandos do chat autorizado."""
    global TG_CHAT
    TG_CHAT = TG_CHAT or estado.get("telegram_chat_id", "")
    params = {"timeout": 0}
    if estado.get("tg_offset"):
        params["offset"] = estado["tg_offset"]
    resp = tg_api("getUpdates", **params)
    comandos = []
    for u in resp.get("result", []):
        estado["tg_offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        chat = str((m.get("chat") or {}).get("id", ""))
        if not chat:
            continue
        if not TG_CHAT:
            TG_CHAT = chat
        if chat != TG_CHAT:
            continue  # ignora estranhos
        texto = (m.get("text") or "").strip()
        if texto:
            comandos.append(texto)
    if TG_CHAT:
        estado["telegram_chat_id"] = TG_CHAT
    else:
        try:
            nome = tg_api("getMe")["result"]["username"]
        except Exception:
            nome = "?"
        sys.exit(f"Ninguém falou com o bot @{nome} ainda. Abra o bot no Telegram e mande /start.")
    return comandos


# ---------------- consulta ----------------
def consultar(page, numero):
    ano, meio, seq = numero.split("/")
    page.goto(URL_CONSULTA, wait_until="domcontentloaded", timeout=60000)
    campos = page.locator("input[type=text]")
    if campos.count() < 3:
        raise RuntimeError("tela de consulta mudou (campos do número não encontrados)")
    campos.nth(0).fill(ano)
    campos.nth(1).fill(meio)
    campos.nth(2).fill(seq)
    page.locator("input[type=submit][value*='esquisar' i], button:has-text('Pesquisar')").first.click()
    page.wait_for_load_state("domcontentloaded", timeout=60000)
    linha = page.locator("tr", has=page.locator(f"a:text-is('{numero}')")).first
    try:
        linha.wait_for(timeout=20000)
    except Exception:
        return None
    celulas = [re.sub(r"\s+", " ", c).strip() for c in linha.locator("td").all_inner_texts()]
    # processo | identificação | tipo | departamento | interessado | assunto | situação | [x]
    if len(celulas) < 7:
        raise RuntimeError(f"tabela de resultado mudou ({len(celulas)} colunas)")
    return dict(zip(CAMPOS, celulas[2:7]))


# ---------------- textos ----------------
def resumo(estado, numero):
    ap = estado["monitorados"].get(numero, numero)
    d = estado["leituras"].get(numero)
    if not d:
        return f"• {ap} ({numero}): ainda sem leitura"
    return f"• {ap} ({numero})\n   {d['situacao']} — {d['departamento']}"


def texto_status(estado, momento):
    linhas = [resumo(estado, n) for n in estado["monitorados"]]
    return f"📋 Processos no Sigam — {carimbo(momento)}\n\n" + "\n".join(linhas)


def texto_processo(estado, numero):
    d = estado["leituras"].get(numero)
    if not d:
        return f"Sem leitura de {numero}. Ele está na lista? (/status)"
    ap = estado["monitorados"].get(numero, numero)
    hist = estado["historico"].get(numero, [])[-10:]
    corpo = [f"📄 {ap} ({numero})"] + [f"{NOMES[c]}: {d[c]}" for c in CAMPOS]
    if hist:
        corpo.append("\nÚltimas movimentações:")
        corpo += [f"  {h['quando']}: {h['mudanca']}" for h in reversed(hist)]
    return "\n".join(corpo)


AJUDA = ("Comandos:\n/status — todos os processos\n/processo NÚMERO — detalhe e histórico\n"
         "/add NÚMERO Apelido — monitorar novo processo\n/remover NÚMERO — parar de monitorar\n"
         "Respondo na verificação seguinte (até 15 min).")


def tratar_comandos(estado, comandos, momento):
    """Aplica /add e /remover já; devolve respostas para mandar após a consulta."""
    respostas = []
    for texto in comandos:
        cmd = texto.split()[0].lower().split("@")[0]
        nums = RE_NUM.findall(texto)
        if cmd in ("/start", "/ajuda", "/help"):
            respostas.append(lambda: AJUDA)
        elif cmd == "/status":
            respostas.append(lambda: texto_status(estado, momento))
        elif cmd == "/processo" and nums:
            respostas.append(lambda n=nums[0]: texto_processo(estado, n))
        elif cmd == "/add" and nums:
            ap = texto.split(nums[0], 1)[1].strip() or nums[0]
            estado["monitorados"][nums[0]] = ap
            respostas.append(lambda n=nums[0]: "✅ Adicionado.\n" + texto_processo(estado, n))
        elif cmd == "/remover" and nums:
            estado["monitorados"].pop(nums[0], None)
            respostas.append(lambda n=nums[0]: f"🗑️ {n} removido do monitoramento.")
        else:
            respostas.append(lambda: "Não entendi.\n" + AJUDA)
    return respostas


def gravar_painel(estado, momento, falha=None):
    l = ["# Painel — processos no Sigam/Naturatins", "",
         f"Última verificação: **{carimbo(momento)}**" +
         (f" — ⚠️ falhou: {falha}" if falha else " — ✅ OK"), "",
         "| Processo | Apelido | Situação | Departamento atual | Assunto | Interessado |",
         "|---|---|---|---|---|---|"]
    for n, ap in estado["monitorados"].items():
        d = estado["leituras"].get(n, {})
        l.append(f"| {n} | {ap} | **{d.get('situacao', '—')}** | {d.get('departamento', '—')} "
                 f"| {d.get('assunto', '—')} | {d.get('interessado', '—')} |")
    l += ["", "## Movimentações", ""]
    eventos = [(h["quando_iso"], n, h["mudanca"]) for n, hs in estado["historico"].items() for h in hs]
    for _, n, mud in sorted(eventos, reverse=True)[:40]:
        l.append(f"- {estado['monitorados'].get(n, n)} ({n}): {mud}")
    if not eventos:
        l.append("- Nenhuma movimentação registrada ainda.")
    l += ["", f"Fonte: [consulta pública do Sigam]({URL_CONSULTA})."]
    ARQ_PAINEL.write_text("\n".join(l) + "\n", encoding="utf-8")


# ---------------- execução ----------------
def tratar_falha(estado, erro, momento):
    print(traceback.format_exc())
    if not estado.get("falhando_desde"):
        estado["falhando_desde"] = momento.isoformat(timespec="minutes")
        avisar = True
    else:
        ult = estado.get("ultimo_aviso_falha")
        avisar = ult is None or (momento - dt.datetime.fromisoformat(ult)).total_seconds() > INTERVALO_AVISO_FALHA_H * 3600
    if avisar and TG_CHAT:
        estado["ultimo_aviso_falha"] = momento.isoformat(timespec="minutes")
        tg(f"⚠️ Robô do Sigam NÃO conseguiu verificar ({carimbo(momento)}).\nMotivo: {erro}\n"
           "Enquanto isso durar, falta de alerta NÃO significa falta de movimentação.")


def main():
    if not TG_TOKEN:
        sys.exit("Falta o segredo TELEGRAM_TOKEN.")
    estado = carregar_estado()
    momento = agora()
    hoje = momento.date().isoformat()
    estado["ultima_execucao"] = momento.isoformat(timespec="minutes")
    falha = None
    try:
        comandos = ler_comandos(estado)
        respostas = tratar_comandos(estado, comandos, momento)

        atual, nao_achados = {}, []
        with sync_playwright() as pw:
            nav = pw.chromium.launch(headless=True)
            page = nav.new_context(locale="pt-BR", ignore_https_errors=True).new_page()
            page.on("dialog", lambda d: d.dismiss())
            for numero in list(estado["monitorados"]):
                dados = consultar(page, numero)
                (atual.__setitem__(numero, dados) if dados else nao_achados.append(numero))
            nav.close()
        if estado["monitorados"] and not atual:
            raise RuntimeError("nenhum processo retornou na consulta (site fora ou mudou)")

        alertas = []
        for numero, dados in atual.items():
            antes = estado["leituras"].get(numero)
            if antes and antes != dados:
                mud = "; ".join(f"{NOMES[c]}: {antes.get(c, '—')} → {dados[c]}"
                                for c in CAMPOS if antes.get(c) != dados[c])
                estado["historico"].setdefault(numero, []).append(
                    {"quando": carimbo(momento), "quando_iso": momento.isoformat(), "mudanca": mud})
                estado["historico"][numero] = estado["historico"][numero][-MAX_HISTORICO:]
                ap = estado["monitorados"].get(numero, numero)
                alertas.append(f"📄 {ap} ({numero})\n  " + mud.replace("; ", "\n  "))
            estado["leituras"][numero] = dados

        primeira = not estado.get("iniciado_em")
        if primeira or MODO.startswith("recon"):
            estado.setdefault("iniciado_em", momento.isoformat(timespec="minutes"))
            tg("🤖 Monitoramento ativo.\n\n" + texto_status(estado, momento) + "\n\n" + AJUDA)
        if alertas:
            tg(f"🔔 Movimentação no Sigam — {carimbo(momento)}\n\n" + "\n\n".join(alertas))
        for r in respostas:
            tg(r())
        if not primeira and not alertas and momento.hour >= 18 and estado.get("resumo_dia") != hoje:
            estado["resumo_dia"] = hoje
            tg(f"✅ Fim do dia: {len(atual)} processo(s) verificados, sem movimentação hoje."
               if not any(h["quando_iso"].startswith(hoje) for hs in estado["historico"].values() for h in hs)
               else texto_status(estado, momento))
        if nao_achados and estado.get("aviso_nao_achados") != hoje:
            estado["aviso_nao_achados"] = hoje
            tg("❓ Não retornaram na consulta (confira o número):\n" + "\n".join(nao_achados))
        if estado.pop("falhando_desde", None):
            estado.pop("ultimo_aviso_falha", None)
            tg(f"✅ Robô do Sigam voltou a funcionar ({carimbo(momento)}).")
    except Exception as erro:
        falha = str(erro)[:200]
        tratar_falha(estado, erro, momento)
    finally:
        gravar_painel(estado, momento, falha)
        salvar_estado(estado)


if __name__ == "__main__":
    main()
