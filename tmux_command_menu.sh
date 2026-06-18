#!/usr/bin/env bash

cd ~/Pythons/Obsidian_tools || exit 1

while true; do
  clear
  echo "=== Menu commandes UV ==="

  cmd=$(grep -v '^#' tmux_memo.txt | grep -v '^$' | fzf --no-sort)

  if [ -z "$cmd" ]; then
    break
  fi

  echo
  echo "▶ $cmd"
  echo

  eval "$cmd"

  echo
  echo "Appuyez sur Entrée pour revenir au menu..."
  read -r
done
