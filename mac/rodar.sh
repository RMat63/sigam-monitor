#!/bin/bash
# Executado pelo launchd a cada 15 min. Decide se é horário de verificar e roda o robô.
cd "$HOME/sigam-monitor" || exit 1
H=$(date +%H); M=$(date +%M); D=$(date +%u)   # D: 1=seg ... 7=dom
H=$((10#$H)); M=$((10#$M))
if [ "$D" -le 5 ]; then
  { [ "$H" -lt 7 ] || [ "$H" -ge 20 ]; } && exit 0
else
  { [ $((H % 2)) -ne 0 ] || [ "$M" -ge 15 ] || [ "$H" -lt 7 ] || [ "$H" -ge 21 ]; } && exit 0
fi
export TELEGRAM_TOKEN="$(security find-generic-password -s sigam-telegram -a robo -w 2>/dev/null)"
[ -z "$TELEGRAM_TOKEN" ] && { echo "$(date) sem token no Chaveiro" >> log.txt; exit 1; }
git pull -q --ff-only >/dev/null 2>&1   # pega atualizações do robô, se houver
./.venv/bin/python monitor.py >> log.txt 2>&1
tail -n 2000 log.txt > log.tmp && mv log.tmp log.txt
