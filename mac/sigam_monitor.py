#!/usr/bin/env python3
"""
Robô Sigam/Naturatins — versão para rodar no Mac (só biblioteca padrão do Python).

Roda a cada 10 min (launchd). Em cada execução:
  1. lê comandos novos do Telegram (/status, /processo, /add, /remover, /ajuda);
  2. consulta cada processo na consulta pública do Sigam (sem login);
  3. avisa no Telegram qualquer mudança de situação/departamento/assunto;
  4. responde os comandos; avisa quando ele próprio falha.

Arquivos em ~/SigamMonitor:  config.json (token), estado.json, robo.log
"""
import datetime as dt
import http.cookiejar
import json
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
from html import escape, unescape
from html.parser import HTMLParser
from pathlib import Path

PASTA = Path.home() / "SigamMonitor"
ARQ_CONFIG = PASTA / "config.json"
ARQ_ESTADO = PASTA / "estado.json"
URL = "https://sigam.to.gov.br/cadastrousuarioexterno/consulta_documento_processo.aspx"
P = "ctl00$ContentPlaceHolder1$"
PROCESSOS_INICIAIS = {
    "2026/40311/011248": "Colinas – LP/LI",
    "2026/40311/015485": "Colinas – AEF",
    "2025/40311/012702": "Formoso do Araguaia – LP/LI",
    "2026/40311/003571": "Formoso do Araguaia – AEF",
}
FUSO = dt.timezone(dt.timedelta(hours=-3))
HORA_INICIO, HORA_FIM = 6, 22          # consulta ao Sigam só nesse horário
INTERVALO_AVISO_FALHA_H = 6
CAMPOS = ("tipo", "departamento", "interessado", "assunto", "situacao")
NOMES = {"tipo": "Tipo", "departamento": "Departamento", "interessado": "Interessado",
         "assunto": "Assunto", "situacao": "Situação"}
RE_NUM = re.compile(r"\d{4}/\d+/\d+")
AJUDA = ("Comandos:\n/status — todos os processos (com o significado de cada situação)\n/processo NÚMERO — detalhe, histórico e link do processo\n/atualizar — consulta o Sigam agora (leva alguns segundos)\n/fonte — de onde vêm as informações\n"
         "/add NÚMERO Apelido — monitorar novo processo\n/remover NÚMERO — parar de monitorar\n"
         "Respondo em segundos (com o Mac ligado).")


def agora():
    return dt.datetime.now(FUSO)


def carimbo(m):
    return m.strftime("%d/%m/%Y %H:%M")


def log(msg):
    print(f"[{carimbo(agora())}] {msg}", flush=True)


# ---------------- arquivos ----------------
def ler_json(p, padrao):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return padrao


def gravar_json(p, dados):
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


# ---------------- Telegram ----------------
class Telegram:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.chat = ""

    def api(self, metodo, **dados):
        corpo = urllib.parse.urlencode(dados).encode()
        with urllib.request.urlopen(self.base + metodo, corpo, timeout=int(dados.get("timeout", 0)) + 40) as r:
            return json.loads(r.read())

    def enviar(self, texto):
        for i in range(0, len(texto), 3900):
            self.api("sendMessage", chat_id=self.chat, text=texto[i:i + 3900],
                     parse_mode="HTML", disable_web_page_preview="true")


# ---------------- Sigam ----------------
class Tabela(HTMLParser):
    """Extrai inputs hidden e as linhas <tr> com suas células de texto."""

    def __init__(self):
        super().__init__()
        self.hidden, self.linhas, self.cods_linha = {}, [], []
        self.cods = []
        self._linha = self._cel = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "input" and (a.get("type") or "").lower() == "hidden" and a.get("name"):
            self.hidden[a["name"]] = a.get("value", "")
        elif tag == "input" and a.get("name") == "cod_protocolo" and self._linha is not None:
            self.cods.append(a.get("value", ""))
        elif tag == "tr":
            self._linha, self.cods = [], []
        elif tag == "td" and self._linha is not None:
            self._cel = []

    def handle_endtag(self, tag):
        if tag == "td" and self._cel is not None and self._linha is not None:
            self._linha.append(re.sub(r"\s+", " ", unescape("".join(self._cel))).strip())
            self._cel = None
        elif tag == "tr" and self._linha is not None:
            self.linhas.append(self._linha)
            self.cods_linha.append(self.cods[0] if self.cods else "")
            self._linha = None

    def handle_data(self, data):
        if self._cel is not None:
            self._cel.append(data)


def abrir_sessao():
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    op.addheaders = [("User-Agent", "Mozilla/5.0 (Macintosh) SigamMonitor/1.0"),
                     ("Accept-Language", "pt-BR,pt;q=0.9")]
    return op


def baixar(op, dados=None):
    corpo = urllib.parse.urlencode(dados).encode() if dados else None
    with op.open(URL, corpo, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def consultar(op, numero):
    ano, meio, seq = numero.split("/")
    t = Tabela()
    t.feed(baixar(op))
    if "__VIEWSTATE" not in t.hidden:
        raise RuntimeError("tela de consulta mudou (sem __VIEWSTATE)")
    dados = dict(t.hidden)
    dados.update({P + "cod_protocolo_tipo": "0", P + "txt_numero_ano_final": ano,
                  P + "txt_numero_orgao_final": meio, P + "txt_numero_sequencial_final": seq,
                  P + "txt_identificacao": "", P + "txt_cnpj_cpf": "", P + "txt_interessado": "",
                  P + "txt_email": "", P + "btnPesquisar": "Pesquisar"})
    r = Tabela()
    r.feed(baixar(op, dados))
    for cel, cod in zip(r.linhas, r.cods_linha):
        # processo | identificação | tipo | departamento | interessado | assunto | situação | [x]
        if len(cel) >= 7 and cel[0] == numero:
            d = dict(zip(CAMPOS, cel[2:7]))
            d["cod"] = cod
            return d
    return None


# ---------------- textos ----------------
URL_LOGIN = "https://sigam.to.gov.br/cadastrousuarioexterno/"
URL_DETALHE = "https://sigam.to.gov.br/cadastrousuarioexterno/detalhe_documento_processo.aspx?cod_protocolo={}"
SIGNIFICADO = {
    "CADASTRADO": "registrado e aguardando o início da análise (fila).",
    "ANDAMENTO": "ativo, tramitando no departamento indicado.",
    "EM ANALISE": "em análise técnica.",
    "EM ANÁLISE": "em análise técnica.",
    "SOBRESTADO": "suspenso, aguardando algo (documento, outro processo ou providência). Ver o despacho.",
    "ARQUIVADO": "encerrado e fora de análise. Pode ser conclusão normal da etapa ou pendência não atendida — ver o despacho.",
    "PENDENTE": "aguardando providência do requerente. Ver a notificação.",
    "PENDÊNCIA": "aguardando providência do requerente. Ver a notificação.",
    "NOTIFICADO": "há notificação ao requerente, normalmente com prazo. Ver a notificação.",
    "DEFERIDO": "pedido aprovado.",
    "INDEFERIDO": "pedido negado. Ver o parecer e o prazo de recurso.",
    "CONCLUIDO": "concluído.",
    "CONCLUÍDO": "concluído.",
}


def significado(sit):
    return SIGNIFICADO.get(sit.strip().upper(), "situação sem descrição padrão — ver o despacho no Sigam.")


def num(est, n):
    """Número do processo já como link para a página do processo no Sigam."""
    cod = (est["leituras"].get(n) or {}).get("cod")
    return f'<a href="{URL_DETALHE.format(cod)}">{n}</a>' if cod else n


def links(d=None):
    return ("🔑 Toque no número do processo para abrir no Sigam "
            f'(precisa estar logado — <a href="{URL_LOGIN}">entrar no Sigam</a>).')


def resumo(est, n):
    ap, d = escape(est["monitorados"].get(n, n)), est["leituras"].get(n)
    if not d:
        return f"• {ap} ({n}): ainda sem leitura"
    return (f"• {ap} ({num(est, n)})\n   <b>{escape(d['situacao'])}</b> — {escape(d['departamento'])}"
            f"\n   ℹ️ {significado(d['situacao'])}")


def texto_status(est, m):
    ult = est.get("ultima_leitura")
    quando = carimbo(dt.datetime.fromisoformat(ult)) if ult else carimbo(m)
    return (f"📋 Processos no Sigam — leitura de {quando}\n\n" + "\n".join(resumo(est, n) for n in est["monitorados"])
            + "\n\n" + links())


def texto_processo(est, n):
    d = est["leituras"].get(n)
    if not d:
        return f"Sem leitura de {n}. Ele está na lista? (/status)"
    linhas = [f"📄 {escape(est['monitorados'].get(n, n))} ({num(est, n)})"] + [f"{NOMES[c]}: {escape(d[c])}" for c in CAMPOS]
    linhas.append(f"ℹ️ {d['situacao']} = {significado(d['situacao'])}")
    hist = est["historico"].get(n, [])[-10:]
    if hist:
        linhas.append("\nÚltimas movimentações:")
        linhas += [f"  {h['quando']}: {escape(h['mudanca'])}" for h in reversed(hist)]
    linhas.append("\n" + links(d))
    return "\n".join(linhas)


FONTE = ("ℹ️ De onde vêm as informações:\n"
         "Da consulta pública do Sigam/Naturatins (sem login), lida pelo robô no seu Mac:\n"
         "https://sigam.to.gov.br/cadastrousuarioexterno/consulta_documento_processo.aspx\n\n"
         "Ela mostra situação, departamento, assunto e interessado. O conteúdo de pareceres, "
         "notificações e despachos só aparece logado no Sigam — use o link de /processo.")


def ler_comandos(tg, est, espera=0):
    params = {"timeout": espera}
    if est.get("tg_offset"):
        params["offset"] = est["tg_offset"]
    comandos = []
    for u in tg.api("getUpdates", **params).get("result", []):
        est["tg_offset"] = u["update_id"] + 1
        msg = u.get("message") or {}
        chat = str((msg.get("chat") or {}).get("id", ""))
        if not chat:
            continue
        if not tg.chat:
            tg.chat = est["telegram_chat_id"] = chat
        if chat == tg.chat and (msg.get("text") or "").strip():
            comandos.append(msg["text"].strip())
    return comandos


def tratar_comandos(est, comandos, m):
    resp = []
    for texto in comandos:
        cmd = texto.split()[0].lower().split("@")[0]
        nums = RE_NUM.findall(texto)
        if cmd in ("/start", "/ajuda", "/help"):
            resp.append(lambda: AJUDA)
        elif cmd == "/fonte":
            resp.append(lambda: FONTE)
        elif cmd == "/status":
            resp.append(lambda: texto_status(est, m))
        elif cmd == "/atualizar":
            resp.append(lambda: "🔄 Consulta feita agora no Sigam.\n\n" + texto_status(est, agora()))
        elif cmd == "/processo" and nums:
            resp.append(lambda n=nums[0]: texto_processo(est, n))
        elif cmd == "/add" and nums:
            est["monitorados"][nums[0]] = texto.split(nums[0], 1)[1].strip() or nums[0]
            resp.append(lambda n=nums[0]: "✅ Adicionado.\n" + texto_processo(est, n))
        elif cmd == "/remover" and nums:
            est["monitorados"].pop(nums[0], None)
            resp.append(lambda n=nums[0]: f"🗑️ {n} removido do monitoramento.")
        else:
            resp.append(lambda: "Não entendi.\n" + AJUDA)
    return resp


# ---------------- escuta de comandos ----------------
ESCUTA_S = 600  # entre duas consultas ao Sigam, fica ouvindo o Telegram


def atualizar_leituras(est, m):
    """Consulta todos os processos; devolve lista de alertas de mudança."""
    op, alertas = abrir_sessao(), []
    for n in list(est["monitorados"]):
        d = consultar(op, n)
        if not d:
            continue
        antes = est["leituras"].get(n)
        est["leituras"][n] = d
        if antes and any(antes.get(c) != d[c] for c in CAMPOS):
            mud = "; ".join(f"{NOMES[c]}: {antes.get(c, '—')} → {d[c]}" for c in CAMPOS if antes.get(c) != d[c])
            est["historico"].setdefault(n, []).append({"quando": carimbo(m), "quando_iso": m.isoformat(), "mudanca": mud})
            est["historico"][n] = est["historico"][n][-50:]
            alertas.append(f"📄 {escape(est['monitorados'].get(n, n))} ({num(est, n)})\n  "
                           + "\n  ".join(escape(x) for x in mud.split("; "))
                           + f"\n  ℹ️ <b>{escape(d['situacao'])}</b> = {significado(d['situacao'])}\n" + links())
        est["leituras"][n] = d
    est["ultima_leitura"] = m.isoformat()
    return alertas


def escutar(tg, est, inicio):
    while time.monotonic() - inicio < ESCUTA_S:
        resto = int(ESCUTA_S - (time.monotonic() - inicio))
        try:
            comandos = ler_comandos(tg, est, espera=max(1, min(50, resto)))
        except Exception as e:
            log(f"escuta: {e}")
            time.sleep(20)
            continue
        if not comandos:
            continue
        m = agora()
        try:
            if any(c.split()[0].lower().split("@")[0] in ("/add", "/atualizar") for c in comandos):
                alertas = atualizar_leituras(est, m)
                if alertas:
                    tg.enviar(f"🔔 Movimentação no Sigam — {carimbo(m)}\n\n" + "\n\n".join(alertas))
        except Exception as e:
            log(f"consulta na escuta: {e}")
        for r in tratar_comandos(est, comandos, m):
            try:
                tg.enviar(r())
            except Exception as e:
                log(f"envio: {e}")
        est["ultima_execucao"] = m.isoformat()
        gravar_json(ARQ_ESTADO, est)
        log(f"escuta — {len(comandos)} comando(s) respondido(s)")


# ---------------- execução ----------------
def main():
    PASTA.mkdir(exist_ok=True)
    cfg = ler_json(ARQ_CONFIG, {})
    if not cfg.get("telegram_token"):
        sys.exit("Sem token do Telegram em ~/SigamMonitor/config.json")
    tg = Telegram(cfg["telegram_token"])
    est = ler_json(ARQ_ESTADO, {})
    est.setdefault("monitorados", dict(PROCESSOS_INICIAIS))
    est.setdefault("leituras", {})
    est.setdefault("historico", {})
    tg.chat = est.get("telegram_chat_id") or str(cfg.get("telegram_chat_id", ""))
    m = agora()
    inicio = time.monotonic()
    hoje = m.date().isoformat()
    teste = "--teste" in sys.argv
    try:
        respostas = tratar_comandos(est, ler_comandos(tg, est), m)
        if not tg.chat:
            log("Ninguém falou com o bot ainda — mande /start para ele.")
            time.sleep(60)
            return
        precisa_consultar = teste or respostas or HORA_INICIO <= m.hour < HORA_FIM
        alertas, nao_achados = [], []
        if precisa_consultar:
            try:
                op = abrir_sessao()
                atual = {}
                for n in list(est["monitorados"]):
                    d = consultar(op, n)
                    (atual.__setitem__(n, d) if d else nao_achados.append(n))
                if est["monitorados"] and not atual:
                    raise RuntimeError("nenhum processo retornou na consulta (site fora ou mudou)")
                for n, d in atual.items():
                    antes = est["leituras"].get(n)
                    est["leituras"][n] = d
                    if antes and any(antes.get(c) != d[c] for c in CAMPOS):
                        mud = "; ".join(f"{NOMES[c]}: {antes.get(c, '—')} → {d[c]}"
                                        for c in CAMPOS if antes.get(c) != d[c])
                        est["historico"].setdefault(n, []).append(
                            {"quando": carimbo(m), "quando_iso": m.isoformat(), "mudanca": mud})
                        est["historico"][n] = est["historico"][n][-50:]
                        alertas.append(f"📄 {escape(est['monitorados'].get(n, n))} ({num(est, n)})\n  "
                                       + "\n  ".join(escape(x) for x in mud.split("; "))
                                       + f"\n  ℹ️ <b>{escape(d['situacao'])}</b> = {significado(d['situacao'])}\n" + links())
                    est["leituras"][n] = d
                est["ultima_leitura"] = m.isoformat()
                if est.pop("falhando_desde", None):
                    est.pop("ultimo_aviso_falha", None)
                    tg.enviar(f"✅ Robô do Sigam voltou a funcionar ({carimbo(m)}).")
            except Exception as erro:
                log(traceback.format_exc())
                primeira = not est.get("falhando_desde")
                est.setdefault("falhando_desde", m.isoformat())
                ult = est.get("ultimo_aviso_falha")
                if teste or primeira or not ult or (m - dt.datetime.fromisoformat(ult)).total_seconds() > INTERVALO_AVISO_FALHA_H * 3600:
                    est["ultimo_aviso_falha"] = m.isoformat()
                    tg.enviar(f"⚠️ Robô do Sigam NÃO conseguiu verificar ({carimbo(m)}).\nMotivo: {escape(str(erro))}\n"
                              "Enquanto isso durar, falta de alerta NÃO significa falta de movimentação.")

        if teste or not est.get("iniciado_em"):
            est.setdefault("iniciado_em", m.isoformat())
            tg.enviar("🤖 Monitoramento ativo no seu Mac.\n\n" + texto_status(est, m) + "\n\n" + AJUDA)
        if alertas:
            tg.enviar(f"🔔 Movimentação no Sigam — {carimbo(m)}\n\n" + "\n\n".join(alertas))
        for r in respostas:
            tg.enviar(r())
        if nao_achados and est.get("aviso_nao_achados") != hoje:
            est["aviso_nao_achados"] = hoje
            tg.enviar("❓ Não retornaram na consulta (confira o número):\n" + "\n".join(nao_achados))
        if m.hour >= 18 and est.get("resumo_dia") != hoje and est.get("iniciado_em") and not est.get("falhando_desde"):
            est["resumo_dia"] = hoje
            mov = any(h["quando_iso"].startswith(hoje) for hs in est["historico"].values() for h in hs)
            tg.enviar(texto_status(est, m) if mov else
                      f"✅ Fim do dia: {len(est['monitorados'])} processo(s) verificados, sem movimentação hoje.")
        log(f"ok — {len(est['leituras'])} leituras, {len(alertas)} alertas, {len(respostas)} comandos")
        gravar_json(ARQ_ESTADO, est)
        if not teste:
            escutar(tg, est, inicio)
    finally:
        est["ultima_execucao"] = m.isoformat()
        gravar_json(ARQ_ESTADO, est)


if __name__ == "__main__":
    if "--teste" in sys.argv:
        main()
    else:
        # Fica rodando sem parar: consulta o Sigam a cada 10 min e responde o Telegram na hora.
        while True:
            try:
                main()
            except SystemExit:
                raise
            except Exception:
                log(traceback.format_exc())
                time.sleep(30)
