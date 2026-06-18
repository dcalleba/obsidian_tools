# Codex - Workspace Obsidian_tools

Cette note sert de rappel pour travailler avec Codex sans melanger avec BDJ.

## Ouvrir le workspace

Ouvrir uniquement le workspace Obsidian Tools:

```text
/Users/danielcallebaut/Pythons/Obsidian_tools/Obsidian_tools.code-workspace
```

Depuis un terminal:

```bash
code /Users/danielcallebaut/Pythons/Obsidian_tools/Obsidian_tools.code-workspace
```

Dans VS Code, l'explorateur doit montrer le projet `Obsidian_tools`, pas `BDJ`.

Ne pas ouvrir Codex ou VS Code depuis un workspace BDJ, et ne pas utiliser:

```text
/Users/danielcallebaut/Pythons/BDJ/config
```

## Nouveau chat Codex

Pour un travail Obsidian Tools, demarrer un nouveau chat Codex et commencer par:

```text
Utilise ce workspace Obsidian_tools uniquement.
Ne reprends pas le contexte BDJ ou BDJ11.
Lis AGENTS.md avant d'agir.
```

`AGENTS.md` est organise en deux parties:

1. socle commun replicable pour les prochains workspaces;
2. regles particulieres du projet `Obsidian_tools`.

Ne pas continuer un ancien chat BDJ11 pour ce projet.

## Separation pratique

La separation complete repose sur trois choses:

1. Ouvrir le workspace `Obsidian_tools.code-workspace`, pas le dossier `Pythons` ni `BDJ`.
2. Demarrer un nouveau chat Codex.
3. Garder les demandes, diagnostics et exports dans ce projet.

Si Codex affiche un contexte BDJ ou `/config`, arreter et rouvrir le workspace:

```text
/Users/danielcallebaut/Pythons/Obsidian_tools/Obsidian_tools.code-workspace
```

L'historique des chats peut rester visible dans l'interface, mais il ne faut pas reprendre un chat d'un autre projet.

## Commandes utiles

```bash
uv run obsidian-media-tool --help
uv run obsidian-media-tool /chemin/vers/vault summary
uv run obsidian-media-tool /chemin/vers/vault diagnose --output obsidian_media_diagnosis.json
uv run obsidian-media-tool /chemin/vers/vault markdown-reports --output-dir diagnostics
```
