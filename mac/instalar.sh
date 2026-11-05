#!/bin/bash
# Instala o robô do Sigam neste Mac. Uso: bash instalar.sh
set -e
cd "$HOME/sigam-monitor"
echo "1/4 Preparando o Python..."
python3 -m venv .venv
./.venv/bin/pip install -q --upgrade pip
./.venv/bin/pip install -q -r requirements.txt
echo "2/4 Baixando o navegador do robô (~150 MB)..."
./.venv/bin/python -m playwright install chromium
echo "3/4 Token do Telegram"
if ! security find-generic-password -s sigam-telegram -a robo >/dev/null 2>&1; then
  echo "Cole o token do BotFather e tecle Enter (o texto não aparece na tela):"
  read -rs TOKEN
  security add-generic-password -s sigam-telegram -a robo -w "$TOKEN"
  unset TOKEN
  echo "Token guardado no Chaveiro do Mac."
else
  echo "Token já estava no Chaveiro."
fi
echo "4/4 Ativando o agendamento..."
mkdir -p "$HOME/Library/LaunchAgents"
cp mac/br.mateus.sigam.plist "$HOME/Library/LaunchAgents/"
launchctl unload "$HOME/Library/LaunchAgents/br.mateus.sigam.plist" 2>/dev/null || true
launchctl load "$HOME/Library/LaunchAgents/br.mateus.sigam.plist"
echo "Rodando o primeiro teste..."
export TELEGRAM_TOKEN="$(security find-generic-password -s sigam-telegram -a robo -w)"
MODO=reconhecer ./.venv/bin/python monitor.py && echo "PRONTO. Confira o Telegram."
