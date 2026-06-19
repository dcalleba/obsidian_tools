#!/usr/bin/env bash

set -u

PROJECT_DIR="$HOME/Pythons/Obsidian_tools"
TITLE="${1:-MENU}"
MEMO_FILE="${2:-}"

if [ -z "$MEMO_FILE" ]; then
  echo "Usage: $0 TITRE fichier_memo.txt"
  exit 1
fi

cd "$PROJECT_DIR" || exit 1

while true; do
  clear
  echo "=== $TITLE ==="

  cmd=$(
    grep -v '^#' "$MEMO_FILE" |
    grep -v '^$' |
    fzf --no-sort --layout=reverse |
    cut -d'|' -f2-
  )

  [ -z "$cmd" ] && break

  echo
  echo "▶ $cmd"
  echo

  eval "$cmd"

  echo
  echo "Appuyez sur Entrée..."
  read -r
done
