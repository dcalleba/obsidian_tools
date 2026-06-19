#!/bin/zsh

FILE="$HOME/Pythons/Obsidian_tools/commands.txt"
VAULT="$HOME/OBSI_COCKPIT"
DOC_DIR="$VAULT/01 Comment Faire"

CAT="$1"

if [ -z "$CAT" ]; then
    echo "Catégorie manquante"
    echo "Exemple : menu_fzf.sh PYTHON"
    exit 1
fi

while true
do
    clear
    echo "===== $CAT ====="
    echo

    # read direct

    if [ -n "$direct" ]; then
        line=$(grep "^$direct|" "$FILE")

        if [ -z "$line" ]; then
            echo "Commande inconnue : $direct"
            read "?Entrée..."
            continue
        fi
    else
        sel=$(
            awk -F'|' -v cat="$CAT" '$5==cat {print $1 "|" $2 "|" $4}' "$FILE" |
            fzf \
                --no-sort \
                --layout=reverse \
                --delimiter='|' \
                --with-nth=1,2 \
                --preview='
                    note=$(echo {} | cut -d"|" -f3 | sed "s/^ *//;s/ *$//")
                    file="'"$DOC_DIR"'/${note}.md"

                    if [ -f "$file" ]; then
                        bat --style=plain --color=always "$file"
                    else
                        echo "Aide introuvable"
                        echo
                        echo "$file"
                    fi
                ' \
                --preview-window=right:60%:wrap
        )

        [ -z "$sel" ] && break

        num=$(echo "$sel" | cut -d'|' -f1 | xargs)
        line=$(grep "^$num|" "$FILE")
    fi

    description=$(echo "$line" | cut -d'|' -f2)
    cmd=$(echo "$line" | cut -d'|' -f3)
    note=$(echo "$line" | cut -d'|' -f4)

    docfile="$DOC_DIR/$note.md"

    if [ ! -f "$docfile" ]; then
        mkdir -p "$DOC_DIR"

        cat > "$docfile" << EOF
# $note

## Commande

\`\`\`bash
$cmd
\`\`\`

## Description

$description

## Notes

EOF

        zed "$docfile"
    fi

    clear
    echo "▶ $cmd"
    echo

    eval "$cmd"

    echo
    read "?Entrée..."
done
