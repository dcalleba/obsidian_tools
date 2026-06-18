#!/bin/zsh

set -u

cd "$(dirname "$0")" || exit 1

echo "Obsidian Synchro"
echo "================"
echo
echo "Dossier projet : $(pwd)"
echo
echo "Commande : uv run obsidian-media-tool export-folder . --rewrite-links"
echo

if ! command -v uv >/dev/null 2>&1; then
  echo "Erreur : uv n'est pas disponible dans le PATH."
  echo "Installez uv ou lancez cet outil depuis un terminal ou uv est disponible."
  echo
  read "reply?Appuyez sur Entree pour fermer..."
  exit 1
fi

uv run obsidian-media-tool export-folder . --rewrite-links
exit_code=$?

echo
echo "Code de sortie : $exit_code"
read "reply?Appuyez sur Entree pour fermer..."
exit "$exit_code"
