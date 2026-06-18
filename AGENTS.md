# AGENTS.md - Socle commun + Obsidian_tools

Ce fichier sert a deux niveaux:

1. fournir une base d'instructions reutilisable pour les prochains workspaces;
2. fixer les regles particulieres du projet `Obsidian_tools`.

La premiere partie peut etre reprise dans un autre projet en adaptant seulement les chemins, commandes et fichiers de reference de la seconde partie.

---

# 1. Socle commun replicable

## Role du fichier

`AGENTS.md` est la consigne locale que Codex doit lire avant d'agir dans un workspace.

Il doit permettre de repondre vite a quatre questions:

- Quel est le bon workspace?
- Quel est le perimetre du projet?
- Quelles conventions priment?
- Comment valider un changement?

## Priorite de lecture

1. Lire `AGENTS.md` a la racine du workspace.
2. Lire les fichiers de conventions ou README mentionnes dans la partie projet.
3. Lire les fichiers impactes avant toute modification.
4. En cas de conflit, appliquer la regle la plus specifique au workspace courant.

## Regles d'execution agent

- Travailler depuis la racine du workspace courant.
- Ne pas melanger les historiques, decisions ou fichiers de plusieurs projets.
- Garder les changements petits, cibles et verifiables.
- Ne pas renommer, deplacer ou supprimer des fichiers structurants sans demande explicite.
- Preferer les solutions simples, robustes et operationnelles au quotidien.
- Ne pas introduire d'architecture, d'orchestration ou de refactor large sans besoin explicite.
- Utiliser les outils du projet pour executer et valider.
- Proposer ou lancer au moins une validation ciblee apres changement quand c'est possible.
- Signaler clairement ce qui n'a pas pu etre valide.

## Regles de separation entre projets

- Un workspace correspond a un projet et a un contexte de travail.
- Ne pas ouvrir, modifier ou utiliser un autre projet sauf demande explicite.
- Si une demande semble viser un autre projet, demander confirmation avant d'agir.
- Si l'editeur ou Codex affiche un chemin d'un autre projet, revenir au workspace attendu avant de continuer.

## Preference de solution

- Commencer par la solution la plus simple qui resout vraiment le probleme.
- Respecter les patterns existants du depot avant d'en creer de nouveaux.
- Ajouter une abstraction seulement si elle reduit une complexite reelle.
- Limiter les changements aux fichiers concernes par la demande.
- Documenter uniquement les points qui aident la maintenance ou l'usage.

## Validation type

Chaque projet devrait definir:

- une commande d'aide ou de smoke test;
- une commande de test ou de validation ciblee;
- les dossiers generes a ignorer;
- les fichiers de configuration importants.

---

# 2. Regles particulieres - Obsidian_tools

## Workspace officiel

Ce fichier s'applique uniquement au projet:

```text
/Users/danielcallebaut/Pythons/Obsidian_tools
```

Workspace VS Code/Codex a utiliser:

```text
/Users/danielcallebaut/Pythons/Obsidian_tools/Obsidian_tools.code-workspace
```

Ne pas partir d'un workspace BDJ, notamment pas depuis:

```text
/Users/danielcallebaut/Pythons/BDJ/config
```

## Perimetre

Ce projet est separe de BDJ.

Sujet principal:

- outils Python pour analyser un vault Obsidian;
- diagnostic des medias et references;
- export de notes ou dossiers Obsidian;
- generation de rapports Markdown/JSON;
- amelioration de `obsidian_media_tool.py`;
- documentation du workflow Obsidian/Codex propre a ce workspace.

Hors sujet par defaut:

- BDJ;
- BDJ11;
- dashboard BDJ;
- scheduler BDJ;
- pipelines BDJ;
- anciens workspaces Obsidian situes dans BDJ.

Ne pas ouvrir, modifier ou utiliser `/Users/danielcallebaut/Pythons/BDJ` sauf demande explicite.

## Conventions de travail

- Considerer `/Users/danielcallebaut/Pythons/Obsidian_tools` comme racine du workspace.
- Utiliser le workspace `/Users/danielcallebaut/Pythons/Obsidian_tools/Obsidian_tools.code-workspace`.
- Ne pas utiliser un workspace, dossier ou configuration provenant de BDJ, y compris `/Users/danielcallebaut/Pythons/BDJ/config`.
- Lire `README.md`, `pyproject.toml` et les fichiers impactes avant modification.
- Utiliser `uv run` pour executer ou valider.
- Ne pas melanger l'historique ou les decisions avec les chats BDJ/BDJ11.
- Si une demande mentionne BDJ ou BDJ11 par erreur, demander confirmation avant d'agir.

## Preference de solution pour ce projet

- Privilegier une CLI Python simple et fiable.
- Garder `obsidian_media_tool.py` comprehensible avant de decouper en modules.
- Produire des rapports lisibles et reproductibles.
- Preserver les fichiers originaux du vault source lors des exports.
- Preferer les options explicites (`--dry-run`, `--rewrite-links`, `--portable-media-names`) aux comportements implicites risquants.
- Eviter les dependances externes tant que la bibliotheque standard suffit.

## Fichiers importants

```text
README.md
pyproject.toml
obsidian_media_tool.py
Obsidian_tools.code-workspace
.vscode/settings.json
docs/
diagnostics/
exports/
```

`diagnostics/` et `exports/` sont des sorties generees. Ne pas les traiter comme code source sauf demande explicite.

## Validations utiles

Afficher l'aide:

```bash
uv run obsidian-media-tool --help
```

Diagnostic d'un vault:

```bash
uv run obsidian-media-tool /chemin/vers/vault diagnose --output obsidian_media_diagnosis.json
```

Generation de rapports Markdown:

```bash
uv run obsidian-media-tool /chemin/vers/vault markdown-reports --output-dir diagnostics
```

Export d'une note:

```bash
uv run obsidian-media-tool /chemin/vers/vault export-note "Ma note.md" --output exports --rewrite-links
```

Export d'un dossier:

```bash
uv run obsidian-media-tool /chemin/vers/vault export-folder "Nom du dossier" --output exports --rewrite-links
```

## Controle de contexte

Avant une modification importante, verifier rapidement:

```bash
pwd
rg -n "BDJ|/Users/danielcallebaut/Pythons/BDJ|BDJ/config" .
uv run obsidian-media-tool --help
```

Les mentions BDJ attendues dans ce projet doivent etre uniquement des consignes de separation, pas des dependances techniques.
