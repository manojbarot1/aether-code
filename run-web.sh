#!/bin/zsh
# Aether Lite in a browser: http://127.0.0.1:3910 (see web.py for options)
cd "$(dirname "$0")"
PY=.venv/bin/python; [[ -x $PY ]] || PY=python3
exec $PY web.py "$@"
