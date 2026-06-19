#!/bin/zsh

FILE=~/Pythons/Obsidian_tools/commands.txt
VAULT=~/OBSI_COCKPIT
DOC_DIR="$VAULT/01 Comment Faire"

CAT="$1"

while true
do
    clear
    echo "===== $CAT ====="
    #echo
    #echo "Numéro + Entrée : exécution directe"
    #echo "Entrée seule    : menu avec aide"
    #echo

    #read "?Commande n° : " direct

    #########################################
    # Exécution directe par numéro
    #########################################

    if [ -n "$direct" ]; then

        line=$(grep "^$direct|" "$FILE")

        if [ -z "$line" ]; then
            echo
            echo "Commande inconnue : $direct"
            echo
            read "?Entrée..."
            continue
        fi

    #########################################
    # Menu FZF avec aperçu de l'aide
    #########################################

    else

        sel=$(
            awk -F'|' -v cat="$CAT" '
                $5==cat {
                    print $1 "|" $2 "|" $4
                }
            ' "$FILE" |
            fzf \
                --no-sort \
                --layout=reverse \
                --delimiter='|' \
                --with-nth=1,2 \
                --preview='
                    note=$(echo {} | awk -F"|" "{print \$3}" | sed "s/^ *//;s/ *$//")
                    file="'"$DOC_DIR"'/${note}.md"

                    if [ -f "$file" ]; then
                        bat --style=plain --color=always "$file"
                    else
                        echo
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

    #########################################
    # Extraction des champs
    #########################################

    description=$(echo "$line" | cut -d'|' -f2)
    cmd=$(echo "$line" | cut -d'|' -f3)
    note=$(echo "$line" | cut -d'|' -f4)

    clear

    echo "===== $CAT ====="
    echo
    echo "Description : $description"
    echo "Commande    : $cmd"
    echo "Documentation : $note.md"
    echo
    echo "▶ Exécution..."
    echo

    eval "$cmd"

    echo
    read "?Entrée..."
done
