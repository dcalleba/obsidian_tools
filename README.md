# Obsidian Tools

Outils Python independants pour travailler sur un vault Obsidian.

## Workspace du projet

Ouvrir ce projet avec le workspace VS Code/Codex suivant:

```text
/Users/danielcallebaut/Pythons/Obsidian_tools/Obsidian_tools.code-workspace
```

Ne pas utiliser un workspace BDJ ou un dossier de configuration BDJ pour ce projet, notamment:

```text
/Users/danielcallebaut/Pythons/BDJ/config
```

Les consignes Codex sont dans `AGENTS.md`. Le debut du fichier contient un socle commun reutilisable pour les prochains workspaces; la seconde partie contient les regles propres a `Obsidian_tools`.

## Installation locale avec uv

```bash
uv sync
```

## Utilisation

Afficher l'aide :

```bash
uv run obsidian-media-tool --help
```

Configurer les dossiers par défaut dans `.env` :

```dotenv
OBSIDIAN_VAULT_PATH=/chemin/vers/vault
OBSIDIAN_EXPORT_OUTPUT_DIR=exports
```

Avec `OBSIDIAN_VAULT_PATH` renseigné, le chemin du vault devient optionnel :

```bash
uv run obsidian-media-tool summary
```

Retirer les marqueurs de surlignage `==...==` de toutes les notes Markdown
d'un dossier, en conservant le texte surligné :

```bash
uv run obsidian-remove-comments /chemin/vers/dossier --dry-run
uv run obsidian-remove-comments /chemin/vers/dossier
```

Le parcours est récursif et ignore les dossiers cachés, notamment `.obsidian`.
Avec `OBSIDIAN_VAULT_PATH` renseigné, le chemin peut être omis.

Compter les notes Markdown sans lire leur contenu :

```bash
uv run obsidian-media-tool /chemin/vers/vault count-notes
```

Afficher un resume d'un vault :

```bash
uv run obsidian-media-tool /chemin/vers/vault summary
```

Generer un rapport JSON :

```bash
uv run obsidian-media-tool /chemin/vers/vault report --output obsidian_media_report.json
```

Lister les medias orphelins :

```bash
uv run obsidian-media-tool /chemin/vers/vault orphans
```

Diagnostiquer les references manquantes, ambiguës et medias orphelins :

```bash
uv run obsidian-media-tool /chemin/vers/vault diagnose --output obsidian_media_diagnosis.json
```

Generer des rapports Markdown lisibles :

```bash
uv run obsidian-media-tool /chemin/vers/vault markdown-reports --output-dir diagnostics
```

Generer un tableau de bord Markdown depuis l'historique du terminal :

```bash
uv run obsidian-media-tool terminal-dashboard --output diagnostics/terminal_dashboard.md
```

Le tableau de bord ajoute des liens `▶` vers un lanceur `.command` local unique et un registre JSON de commandes.
Le lanceur demande l'identifiant affiché dans le lien, puis confirmation avant execution.
Pour générer le Markdown sans ces liens :

```bash
uv run obsidian-media-tool terminal-dashboard --no-command-links
```

Afficher l'historique directement dans Ghostty :

```bash
uv run obsidian-media-tool terminal-history --search obsidian
```

Afficher les résultats sans doublons :

```bash
uv run obsidian-media-tool terminal-history --search obsidian --unique
```

Relancer une commande affichée depuis Ghostty :

```bash
uv run obsidian-media-tool terminal-history --search obsidian --unique --rerun
```

Relancer directement le numéro 7 d'une même liste :

```bash
uv run obsidian-media-tool terminal-history --search obsidian --unique --run-number 7
```

Garder la liste ouverte après chaque relance :

```bash
uv run obsidian-media-tool terminal-history --search obsidian --unique --loop
```

Dans le mode interactif, taper `01` au lieu de `1` masque la commande 1 pour les prochains affichages.
Les commandes masquées sont conservées dans `diagnostics/terminal_history_ignored.json`.

Pour que les prochaines commandes Ghostty soient horodatées par `zsh`, ajouter dans `~/.zshrc` :

```zsh
setopt EXTENDED_HISTORY
setopt INC_APPEND_HISTORY
```

Les commandes déjà enregistrées sans date restent sans date : `zsh` ne permet pas de reconstruire leur horodatage après coup.

Lister les notes exportables sans references media bloquantes :

```bash
uv run obsidian-media-tool /chemin/vers/vault exportable-notes --output diagnostics/07_notes_exportables.md
```

Exporter une note avec ses medias :

```bash
uv run obsidian-media-tool /chemin/vers/vault export-note "Ma note.md" --output /chemin/sortie
```

Avec `OBSIDIAN_EXPORT_OUTPUT_DIR` renseigné, `--output` devient optionnel pour `export-note` et `export-folder`.

L'export copie la note et ses medias dans le dossier de sortie. Les fichiers originaux restent en place dans le vault source.
Par défaut, un fichier `.md` ou média déjà présent dans le dossier de sortie n'est pas écrasé.
Pour remplacer les fichiers existants, ajouter `--overwrite`.

Exporter en convertissant les liens medias de la copie en Markdown universel :

```bash
uv run obsidian-media-tool /chemin/vers/vault export-note "Ma note.md" --output /chemin/sortie --rewrite-links
```

Forcer le remplacement d'une note ou de médias déjà exportés :

```bash
uv run obsidian-media-tool /chemin/vers/vault export-note "Ma note.md" --output /chemin/sortie --rewrite-links --overwrite
```

Exporter toutes les notes valides d'un dossier, en gardant les originaux dans le vault source :

```bash
uv run obsidian-media-tool /chemin/vers/vault export-folder "Cartes_postales_photo" --output exports --rewrite-links
```

L'export de dossier copie aussi les fichiers `.base` présents dans le dossier exporté, en conservant leur chemin relatif.

Si un lecteur Markdown n'affiche pas les images avec des noms accentues, utiliser les noms medias portables :

```bash
uv run obsidian-media-tool /chemin/vers/vault export-folder "Cartes_postales_photo" --output exports --rewrite-links --portable-media-names
```

Simuler un export sans rien copier :

```bash
uv run obsidian-media-tool /chemin/vers/vault export-note "Ma note.md" --output /chemin/sortie --dry-run
```
