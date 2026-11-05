"""
Navegador próprio do robô (Google Chrome controlado pelo Playwright) para ler,
com o login do Ricardo, o Histórico do Processo e o Histórico de Pendência.

- O login é feito pela própria pessoa, na janela que o robô abre no Mac
  (pode ser pelo celular, via acesso remoto à tela do Mac). O robô nunca vê a senha.
- Depois do login, a sessão é mantida viva acessando o Sigam a cada poucos minutos.
"""
import re
import time
from pathlib import Path

URL_LOGIN = "https://sigam.to.gov.br/cadastrousuarioexterno/"
URL_DETALHE = "https://sigam.to.gov.br/cadastrousuarioexterno/detalhe_documento_processo.aspx?cod_protocolo={}"
PERFIL = Path.home() / "SigamMonitor" / "navegador"
MANTER_VIVA_S = 300

# Lê todas as tabelas da página com o título "Histórico..." mais próximo acima delas.
JS_TABELAS = r"""() => {
  const limpa = t => (t || '').replace(/\s+/g, ' ').trim();
  const out = [];
  document.querySelectorAll('table').forEach(tb => {
    const linhas = [...tb.querySelectorAll('tr')].map(tr =>
      [...tr.querySelectorAll('th,td')].map(c => limpa(c.innerText)));
    if (linhas.length < 2) return;
    let titulo = '', el = tb;
    for (let i = 0; i < 12 && el && !titulo; i++) {
      let p = el.previousElementSibling;
      while (p && !titulo) {
        const t = limpa(p.innerText);
        if (/hist[oó]rico/i.test(t)) titulo = t.slice(0, 80);
        p = p.previousElementSibling;
      }
      el = el.parentElement;
    }
    out.push({titulo, linhas});
  });
  return out;
}"""

CONSERTOS = [("SERVI�O", "SERVIÇO"), ("AN�LISE", "ANÁLISE"), ("PEND�NCIA", "PENDÊNCIA"),
             ("��O", "ÇÃO"), ("��ES", "ÇÕES"), ("S�O", "SÃO"), ("�", "·")]


def consertar(t):
    for a, b in CONSERTOS:
        t = t.replace(a, b)
    return t


def _data(txt):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", txt or "")
    return (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else (0, 0, 0)


class Navegador:
    def __init__(self, log):
        self.log = log
        self.pw = self.ctx = self.aba_login = self.aba = None
        self.ultimo_toque = 0.0
        self.cod_teste = None

    # ---------- ciclo de vida ----------
    def iniciar(self):
        if self.ctx:
            return
        from playwright.sync_api import sync_playwright  # só carrega se instalado
        PERFIL.mkdir(parents=True, exist_ok=True)
        self.pw = sync_playwright().start()
        self.ctx = self.pw.chromium.launch_persistent_context(
            str(PERFIL), channel="chrome", headless=False, locale="pt-BR",
            viewport={"width": 1100, "height": 800}, args=["--window-position=40,40"])
        self.ctx.on("page", lambda p: p.on("dialog", lambda d: d.dismiss()))
        self.aba = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.aba.on("dialog", lambda d: d.dismiss())

    def fechar(self):
        try:
            if self.ctx:
                self.ctx.close()
            if self.pw:
                self.pw.stop()
        except Exception:
            pass
        self.pw = self.ctx = self.aba_login = self.aba = None

    # ---------- login ----------
    def abrir_login(self):
        self.iniciar()
        if not self.aba_login or self.aba_login.is_closed():
            self.aba_login = self.ctx.new_page()
        self.aba_login.goto(URL_LOGIN, wait_until="domcontentloaded", timeout=60000)
        self.aba_login.bring_to_front()

    def login_concluido(self):
        """True quando a aba de login saiu da tela de login (sem tocar na aba enquanto a pessoa digita)."""
        if not self.aba_login or self.aba_login.is_closed():
            return False
        try:
            if self.aba_login.locator("input[type=password]:visible").count():
                return False
        except Exception:
            return False
        return self.logado(forcar=True)

    def logado(self, cod=None, forcar=False):
        """Abre a página de um processo; se cair na tela de entrada, não está logado."""
        cod = cod or self.cod_teste
        if not cod:
            return False
        try:
            self.iniciar()
            self.aba.goto(URL_DETALHE.format(cod), wait_until="domcontentloaded", timeout=60000)
            ok = "detalhe_documento_processo" in self.aba.url.lower()
            if ok:
                self.ultimo_toque = time.monotonic()
            return ok
        except Exception as e:
            self.log(f"navegador: {e}")
            return False

    def manter_viva(self):
        """Chamado no laço do robô: a cada 5 min recarrega um processo para a sessão não expirar."""
        if time.monotonic() - self.ultimo_toque < MANTER_VIVA_S:
            return None
        return self.logado()

    # ---------- leitura ----------
    def ler(self, cod):
        """Devolve {'movimentos': [dict...], 'pendencias': [dict...]} ou None se não estiver logado."""
        if not self.logado(cod):
            return None
        tabelas = self.aba.evaluate(JS_TABELAS)
        res = {"movimentos": [], "pendencias": []}
        for t in tabelas:
            cab = [consertar(c).upper() for c in t["linhas"][0]]
            juntos = " ".join(cab)
            if not ("DATA" in juntos and ("SITUA" in juntos or "DESPACHO" in juntos or "PEND" in juntos)):
                continue
            linhas = [dict(zip(cab, [consertar(c) for c in l])) for l in t["linhas"][1:] if any(l)]
            titulo = (t["titulo"] or "").upper()
            if "PEND" in titulo or ("PEND" in juntos and "DESPACHO MOVIMENTA" not in juntos):
                res["pendencias"] = linhas
            elif not res["movimentos"]:
                res["movimentos"] = linhas
            else:
                res["pendencias"] = linhas
        res["movimentos"].sort(key=lambda r: _data(r.get("DATA", "")), reverse=True)
        return res
