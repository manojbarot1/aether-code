#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python app.py
echo "$(date '+%F %T') Aether Lite exited with code $?" >> ~/.aether-lite/exit.log
