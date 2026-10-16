#!/bin/zsh
cd "$(dirname "$0")"
.venv/bin/python v2/ide.py
echo "$(date '+%F %T') Aether Code exited with code $?" >> ~/.aether-lite/exit.log
