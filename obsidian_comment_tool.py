#!/usr/bin/env python3
"""Retire les marqueurs de surlignage ==...== des notes Markdown."""

# ttest modif
from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv

ENV_VAULT_PATH = "OBSIDIAN_VAULT_PATH"
HIGHLIGHT_RE = re.compile(r"==(.*?)==")


@dataclass(frozen=True)
# exemple numero2 dddd
class CleanupResult:
    scanned_files: int
    modified_files: int
    removed_markers: int


def strip_highlight_markers(text: str) -> tuple[str, int]:
    """Transforme chaque ``==texte==`` en ``texte``."""
    return HIGHLIGHT_RE.subn(r"\1", text)


def iter_markdown_files(folder: Path) -> Iterable[Path]:
    """Parcourt les notes Markdown en ignorant les dossiers cachés."""
    for root, dirs, files in os.walk(folder):
        dirs[:] = [name for name in dirs if not name.startswith(".")]
        root_path = Path(root)
        for filename in files:
            if filename.lower().endswith(".md"):
                yield root_path / filename


def clean_folder(folder: Path, dry_run: bool = False) -> CleanupResult:
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(f"Dossier Obsidian invalide : {folder}")

    scanned_files = 0
    modified_files = 0
    removed_markers = 0

    for md_file in sorted(iter_markdown_files(folder)):
        scanned_files += 1
        text = md_file.read_text(encoding="utf-8")
        new_text, replacements = strip_highlight_markers(text)

        if replacements == 0:
            continue

        modified_files += 1
        removed_markers += replacements
        action = "À modifier" if dry_run else "Modifié"
        print(f"{action} : {md_file}")

        if not dry_run:
            md_file.write_text(new_text, encoding="utf-8")

    return CleanupResult(
        scanned_files=scanned_files,
        modified_files=modified_files,
        removed_markers=removed_markers,
    )


def env_vault_path() -> Path | None:
    value = os.environ.get(ENV_VAULT_PATH)
    return Path(value).expanduser() if value and value.strip() else None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Retire récursivement les marqueurs de surlignage ==...== "
            "des notes Markdown, sans supprimer leur contenu."
        )
    )
    parser.add_argument(
        "folder",
        nargs="?",
        type=Path,
        default=env_vault_path(),
        help=f"Dossier à traiter. Défaut : ${ENV_VAULT_PATH}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Liste les fichiers qui seraient modifiés sans les écrire",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.folder is None:
        parser.error(
            f"dossier manquant : fournissez un chemin ou renseignez {ENV_VAULT_PATH} dans .env"
        )

    try:
        result = clean_folder(args.folder, dry_run=args.dry_run)
    except (OSError, UnicodeError) as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 2

    mode = "Simulation terminée" if args.dry_run else "Nettoyage terminé"
    print(
        f"{mode} : {result.scanned_files} fichier(s) analysé(s), "
        f"{result.modified_files} fichier(s) concerné(s), "
        f"{result.removed_markers} surlignage(s) retiré(s)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
