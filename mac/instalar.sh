#!/bin/bash
# Instala o robô Sigam no Mac: copia o script, pede o token do Telegram,
# cria o agendamento (a cada 10 min) e roda um teste.
set -e
PASTA="$HOME/SigamMonitor"
REPO="https://raw.githubusercontent.com/RMat63/sigam-monitor/main/mac"
PLIST="$HOME/Library/LaunchAgents/br.com.mateus.sigam.plist"
PY="/usr/bin/python3"

echo "== Robô Sigam: instalação =="
if ! "$PY" -c "import ssl" >/dev/null 2>&1; then
  echo "O Python do Mac ainda não está instalado."
  echo "Vai abrir uma janela pedindo para instalar as 'ferramentas de linha de comando'."
  echo "Clique em INSTALAR, espere terminar e rode este comando de novo."
  xcode-select --install || true
  exit 1
fi

mkdir -p "$PASTA"
curl -fsSL "$REPO/sigam_monitor.py" -o "$PASTA/sigam_monitor.py"

if [ ! -s "$PASTA/config.json" ]; then
  TOKEN=$(osascript -e 'text returned of (display dialog "Cole aqui o token do seu bot do Telegram (o texto que o BotFather mandou):" default answer "" with title "Robô Sigam" with hidden answer)')
  TOKEN=$(echo "$TOKEN" | tr -d '[:space:]')
  if [ -z "$TOKEN" ]; then echo "Token vazio. Rode de novo."; exit 1; fi
  if ! curl -fsS "https://api.telegram.org/bot$TOKEN/getMe" >/dev/null 2>&1; then
    echo ""
    echo "== O Telegram NÃO reconheceu esse token. =="
    echo "Abra a conversa com o BotFather, mande /mybots, escolha o seu bot,"
    echo "toque em 'API Token', copie o token inteiro e rode o comando de novo."
    exit 1
  fi
  umask 077
  printf '{"telegram_token": "%s", "telegram_chat_id": "8431141453"}\n' "$TOKEN" > "$PASTA/config.json"
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>br.com.mateus.sigam</string>
  <key>ProgramArguments</key><array><string>$PY</string><string>$PASTA/sigam_monitor.py</string></array>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$PASTA/robo.log</string>
  <key>StandardErrorPath</key><string>$PASTA/robo.log</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/br.com.mateus.sigam" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"

echo "Rodando o primeiro teste..."
"$PY" "$PASTA/sigam_monitor.py" --teste && echo "== Pronto! Confira o seu Telegram. ==" || echo "== Teste falhou: veja acima. =="
