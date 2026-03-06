#!/usr/bin/env bash
# DocManager – Startskript
# Wechselt ins Projektverzeichnis und startet die Anwendung.

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$DIR/main.py" "$@"
