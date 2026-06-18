#!/bin/zsh

set -u

cd "$(dirname "$0")" || exit 1

echo "Obsidian Media Tool"
echo "==================="
echo
echo "Dossier projet : $(pwd)"
echo

if ! command -v uv >/dev/null 2>&1; then
  echo "Erreur : uv n'est pas disponible dans le PATH."
  echo "Installez uv ou lancez cet outil depuis un terminal ou uv est disponible."
  echo
  read "reply?Appuyez sur Entree pour fermer..."
  exit 1
fi

if [ -x ".venv/bin/obsidian-media-tool" ]; then
  runner=(.venv/bin/obsidian-media-tool)
else
  runner=(uv run obsidian-media-tool)
fi

if [ "$#" -eq 0 ]; then
  echo "Aucun vault fourni."
  echo
  read "vault_path?Glissez-collez le dossier du vault Obsidian, puis appuyez sur Entree : "
  echo
  if [ -z "$vault_path" ]; then
    "${runner[@]}" --help
    exit_code=$?
    echo
    echo "Code de sortie : $exit_code"
    read "reply?Appuyez sur Entree pour fermer..."
    exit "$exit_code"
  fi
  set -- "$vault_path"
fi

if [ "$#" -eq 1 ]; then
  vault_path="$1"
  echo "Vault : $vault_path"
  echo
  echo "Action :"
  echo "  1) Resume du vault"
  echo "  2) Rapport JSON complet"
  echo "  3) Medias orphelins"
  echo "  4) References manquantes"
  echo "  5) Diagnostic"
  echo "  6) Rapports Markdown"
  echo "  7) Notes exportables"
  echo "  8) Exporter un dossier de notes valides"
  echo
  read "choice?Choix [1-8] : "
  echo

  case "$choice" in
    1|"")
      "${runner[@]}" "$vault_path" summary
      ;;
    2)
      "${runner[@]}" "$vault_path" report
      ;;
    3)
      "${runner[@]}" "$vault_path" orphans
      ;;
    4)
      "${runner[@]}" "$vault_path" missing
      ;;
    5)
      "${runner[@]}" "$vault_path" diagnose
      ;;
    6)
      "${runner[@]}" "$vault_path" markdown-reports
      ;;
    7)
      "${runner[@]}" "$vault_path" exportable-notes
      ;;
    8)
      read "folder_path?Dossier du vault à exporter : "
      "${runner[@]}" "$vault_path" export-folder "$folder_path" --output exports --rewrite-links --portable-media-names
      ;;
    *)
      echo "Choix invalide : $choice"
      false
      ;;
  esac
else
  "${runner[@]}" "$@"
fi

exit_code=$?
echo
echo "Code de sortie : $exit_code"
read "reply?Appuyez sur Entree pour fermer..."
exit "$exit_code"
