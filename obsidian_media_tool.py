#!/usr/bin/env python3
"""
obsidian_media_tool.py

Outil spécialisé pour analyser un vault Obsidian et retrouver les médias attachés aux fichiers Markdown.

Fonctions principales :
- Scanner toutes les notes .md
- Détecter les embeds Obsidian : ![[image.png]], ![[doc.pdf#page=2]], ![[image.png|300]]
- Détecter les liens wiki simples : [[Note]]
- Détecter les liens Markdown : ![](../assets/image.png), [doc](file.pdf)
- Résoudre les médias par chemin relatif ou par nom de fichier
- Détecter les médias orphelins
- Exporter une note avec ses médias dans un dossier autonome
- Simuler les opérations sans rien modifier

Dépendances : python-dotenv.
Compatible Python 3.11+.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote, unquote, urlparse

from dotenv import load_dotenv

try:
    import pwd
except ImportError:  # pragma: no cover - module absent on Windows
    pwd = None


DEFAULT_MEDIA_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".tif",
    ".tiff",
    ".pdf",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".flac",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".webm",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".7z",
    ".rar",
}

SUPPORT_FILE_EXTENSIONS = {".base"}

IMAGE_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".tif",
    ".tiff",
}

WIKILINK_RE = re.compile(r"!?\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
HTML_IMG_RE = re.compile(r"<img\s+[^>]*src=[\"']([^\"']+)[\"'][^>]*>", re.IGNORECASE)
FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
ENV_VAULT_PATH = "OBSIDIAN_VAULT_PATH"
ENV_EXPORT_OUTPUT_DIR = "OBSIDIAN_EXPORT_OUTPUT_DIR"
COMMAND_NAMES = {
    "count-notes",
    "summary",
    "report",
    "orphans",
    "missing",
    "diagnose",
    "markdown-reports",
    "exportable-notes",
    "blocked-notes",
    "export-note",
    "export-folder",
    "terminal-dashboard",
    "terminal-history",
}
NO_VAULT_COMMAND_NAMES = {"terminal-dashboard", "terminal-history"}

ZSH_HISTORY_RE = re.compile(r"^: (?P<timestamp>\d+):(?P<duration>\d+);(?P<command>.*)$")
ABSOLUTE_PATH_RE = re.compile(
    r"(?P<path>/(?:Users|private|tmp|var|Volumes)/[^\s'\"`;|&<>]+)"
)
PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_TERMINAL_DASHBOARD_OUTPUT = (
    PROJECT_ROOT / "diagnostics" / "terminal_dashboard.md"
)
DEFAULT_TERMINAL_IGNORE_FILE = (
    PROJECT_ROOT / "diagnostics" / "terminal_history_ignored.json"
)
DEFAULT_TERMINAL_COMMAND_LINK_DIR = (
    PROJECT_ROOT / "diagnostics" / "terminal_command_links"
)
TERMINAL_COMMAND_RUNNER_NAME = "run_terminal_command.command"
TERMINAL_COMMAND_REGISTRY_NAME = "terminal_command_registry.json"


@dataclasses.dataclass(frozen=True)
class Reference:
    source_note: Path
    raw: str
    normalized_target: str
    is_embed: bool
    kind: str


@dataclasses.dataclass(frozen=True)
class ResolvedReference:
    reference: Reference
    resolved_path: Path | None
    candidates: tuple[Path, ...]
    status: str


@dataclasses.dataclass
class VaultIndex:
    vault_root: Path
    notes: list[Path]
    media: list[Path]
    media_by_name: dict[str, list[Path]]
    references_by_note: dict[Path, list[Reference]]
    resolved_by_note: dict[Path, list[ResolvedReference]]


@dataclasses.dataclass(frozen=True)
class ShellCommandEntry:
    command: str
    timestamp: dt.datetime | None
    inferred_cwd: Path | None
    family: str
    project: str


def is_hidden_or_obsidian_internal(path: Path, vault_root: Path) -> bool:
    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        return True

    parts = rel.parts
    return any(part.startswith(".") for part in parts) or ".obsidian" in parts


def iter_files(vault_root: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(vault_root):
        root_path = Path(root)

        dirs[:] = [d for d in dirs if not d.startswith(".") and d != ".obsidian"]

        for filename in files:
            path = root_path / filename
            if not is_hidden_or_obsidian_internal(path, vault_root):
                yield path


def normalize_obsidian_target(raw: str) -> str:
    """
    Normalise une cible Obsidian.

    Exemples :
    - image.png|300       -> image.png
    - doc.pdf#page=2      -> doc.pdf
    - note#heading        -> note
    - folder/image.png    -> folder/image.png
    """
    target = raw.strip()

    if "|" in target:
        target = target.split("|", 1)[0]

    if "#" in target:
        target = target.split("#", 1)[0]

    return unquote(target.strip())


def normalize_markdown_url(raw: str) -> str:
    target = raw.strip().strip("<>")

    if target.startswith("file://"):
        parsed = urlparse(target)
        target = unquote(parsed.path)
    elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return target

    if "#" in target:
        target = target.split("#", 1)[0]

    return unquote(target.strip())


def is_probably_media_target(target: str, media_extensions: set[str]) -> bool:
    if not target:
        return False

    parsed = urlparse(target)
    if parsed.scheme in {"http", "https", "mailto"} or parsed.netloc:
        return False

    suffix = Path(target).suffix.lower()
    return suffix in media_extensions


def read_text_lossy(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def extract_frontmatter_references(
    note: Path, text: str, media_extensions: set[str]
) -> list[Reference]:
    """
    Extraction volontairement simple des références de médias dans le frontmatter YAML.
    Elle couvre les cas courants : cover, image, attachment, attachments, banner, cssclasses, etc.
    """
    match = FRONTMATTER_RE.match(text)
    if not match:
        return []

    block = match.group(1)
    refs: list[Reference] = []

    for token in re.findall(r"[\w ./\\@()\-]+\.[A-Za-z0-9]{2,5}", block):
        target = normalize_obsidian_target(token)
        if is_probably_media_target(target, media_extensions):
            refs.append(
                Reference(
                    source_note=note,
                    raw=token,
                    normalized_target=target,
                    is_embed=False,
                    kind="frontmatter",
                )
            )

    return refs


def extract_references(
    note: Path, text: str, media_extensions: set[str]
) -> list[Reference]:
    refs: list[Reference] = []

    for match in WIKILINK_RE.finditer(text):
        raw_target = match.group(1)
        normalized = normalize_obsidian_target(raw_target)
        is_embed = match.group(0).startswith("!")

        if is_probably_media_target(normalized, media_extensions):
            refs.append(
                Reference(
                    source_note=note,
                    raw=raw_target,
                    normalized_target=normalized,
                    is_embed=is_embed,
                    kind="wikilink",
                )
            )

    for match in MARKDOWN_LINK_RE.finditer(text):
        raw_target = match.group(1)
        normalized = normalize_markdown_url(raw_target)

        if is_probably_media_target(normalized, media_extensions):
            refs.append(
                Reference(
                    source_note=note,
                    raw=raw_target,
                    normalized_target=normalized,
                    is_embed=match.group(0).startswith("!"),
                    kind="markdown",
                )
            )

    for match in HTML_IMG_RE.finditer(text):
        raw_target = match.group(1)
        normalized = normalize_markdown_url(raw_target)

        if is_probably_media_target(normalized, media_extensions):
            refs.append(
                Reference(
                    source_note=note,
                    raw=raw_target,
                    normalized_target=normalized,
                    is_embed=True,
                    kind="html-img",
                )
            )

    refs.extend(extract_frontmatter_references(note, text, media_extensions))
    return refs


def build_media_index(media_files: Sequence[Path]) -> dict[str, list[Path]]:
    by_name: dict[str, list[Path]] = defaultdict(list)
    for path in media_files:
        for name in {
            path.name,
            unicodedata.normalize("NFC", path.name),
            unicodedata.normalize("NFD", path.name),
        }:
            by_name[name].append(path)
    return dict(by_name)


def resolve_reference(
    vault_root: Path, ref: Reference, media_by_name: dict[str, list[Path]]
) -> ResolvedReference:
    target = ref.normalized_target

    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
        return ResolvedReference(ref, None, (), "external")

    target_path = Path(target)
    candidates: list[Path] = []

    # 1. Chemin absolu local
    if target_path.is_absolute() and target_path.exists():
        resolved = target_path.resolve()
        return ResolvedReference(ref, resolved, (resolved,), "resolved-absolute")

    # 2. Chemin relatif à la note
    relative_to_note = (ref.source_note.parent / target_path).resolve()
    if relative_to_note.exists():
        return ResolvedReference(
            ref, relative_to_note, (relative_to_note,), "resolved-relative-to-note"
        )

    # 3. Chemin relatif à la racine du vault
    relative_to_vault = (vault_root / target_path).resolve()
    if relative_to_vault.exists():
        return ResolvedReference(
            ref, relative_to_vault, (relative_to_vault,), "resolved-relative-to-vault"
        )

    # 4. Résolution Obsidian par nom de fichier
    basename = target_path.name
    candidate_names = {
        basename,
        unicodedata.normalize("NFC", basename),
        unicodedata.normalize("NFD", basename),
    }
    candidates = sorted(
        {p.resolve() for name in candidate_names for p in media_by_name.get(name, [])}
    )

    if len(candidates) == 1:
        return ResolvedReference(
            ref, candidates[0], tuple(candidates), "resolved-by-name"
        )

    if len(candidates) > 1:
        # Heuristique : choisir le fichier le plus proche en nombre de segments communs.
        source_parts = ref.source_note.parent.resolve().parts

        def score(path: Path) -> tuple[int, int]:
            media_parts = path.parent.resolve().parts
            common = sum(1 for a, b in zip(source_parts, media_parts) if a == b)
            distance = abs(len(source_parts) - len(media_parts))
            return common, -distance

        best = sorted(candidates, key=score, reverse=True)[0]
        return ResolvedReference(
            ref, best, tuple(candidates), "ambiguous-chosen-nearest"
        )

    return ResolvedReference(ref, None, (), "missing")


def build_index(vault_root: Path, media_extensions: set[str]) -> VaultIndex:
    vault_root = vault_root.resolve()
    files = list(iter_files(vault_root))

    notes = sorted([p.resolve() for p in files if p.suffix.lower() == ".md"])
    media = sorted([p.resolve() for p in files if p.suffix.lower() in media_extensions])
    media_by_name = build_media_index(media)

    references_by_note: dict[Path, list[Reference]] = {}
    resolved_by_note: dict[Path, list[ResolvedReference]] = {}

    for note in notes:
        text = read_text_lossy(note)
        refs = extract_references(note, text, media_extensions)
        resolved = [resolve_reference(vault_root, ref, media_by_name) for ref in refs]
        references_by_note[note] = refs
        resolved_by_note[note] = resolved

    return VaultIndex(
        vault_root=vault_root,
        notes=notes,
        media=media,
        media_by_name=media_by_name,
        references_by_note=references_by_note,
        resolved_by_note=resolved_by_note,
    )


def rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def referenced_media(index: VaultIndex) -> set[Path]:
    used: set[Path] = set()
    for resolved_refs in index.resolved_by_note.values():
        for item in resolved_refs:
            if item.resolved_path is not None and item.status != "external":
                used.add(item.resolved_path.resolve())
    return used


def count_notes(vault_root: Path) -> int:
    return sum(1 for path in iter_files(vault_root) if path.suffix.lower() == ".md")


def print_note_count(vault_root: Path) -> None:
    print(f"Notes Markdown : {count_notes(vault_root)}")


def write_report(index: VaultIndex, output: Path) -> None:
    used = referenced_media(index)
    orphan = sorted(set(index.media) - used)

    missing = []
    ambiguous = []

    notes_payload = []
    for note in index.notes:
        resolved_items = index.resolved_by_note.get(note, [])
        note_payload = {
            "note": rel(note, index.vault_root),
            "media": [],
        }
        for item in resolved_items:
            if item.status == "missing":
                missing.append(item)
            if item.status.startswith("ambiguous"):
                ambiguous.append(item)

            note_payload["media"].append(
                {
                    "raw": item.reference.raw,
                    "target": item.reference.normalized_target,
                    "kind": item.reference.kind,
                    "status": item.status,
                    "resolved": rel(item.resolved_path, index.vault_root)
                    if item.resolved_path
                    else None,
                    "candidates": [rel(c, index.vault_root) for c in item.candidates],
                }
            )
        notes_payload.append(note_payload)

    payload = {
        "vault": index.vault_root.as_posix(),
        "summary": {
            "notes": len(index.notes),
            "media": len(index.media),
            "referenced_media": len(used),
            "orphan_media": len(orphan),
            "missing_references": len(missing),
            "ambiguous_references": len(ambiguous),
        },
        "orphan_media": [rel(p, index.vault_root) for p in orphan],
        "notes": notes_payload,
    }

    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def find_note(index: VaultIndex, query: str) -> Path:
    query_path = Path(query)

    candidates: list[Path] = []
    if query_path.is_absolute() and query_path.exists():
        candidates = [query_path.resolve()]
    else:
        direct = (index.vault_root / query_path).resolve()
        if direct.exists():
            candidates = [direct]
        else:
            wanted = query_path.name
            if not wanted.endswith(".md"):
                wanted += ".md"
            candidates = [p for p in index.notes if p.name == wanted]

    if not candidates:
        raise FileNotFoundError(f"Note introuvable : {query}")

    if len(candidates) > 1:
        choices = "\n".join(f"- {rel(p, index.vault_root)}" for p in candidates[:20])
        raise RuntimeError(f"Nom de note ambigu : {query}\n{choices}")

    return candidates[0]


def safe_copy(src: Path, dst: Path, dry_run: bool, overwrite: bool) -> bool:
    if dst.exists() and not overwrite:
        action = "DRY-RUN skip existing" if dry_run else "SKIP existing"
        print(f"{action} {dst}")
        return False

    if dry_run:
        action = "DRY-RUN overwrite" if dst.exists() else "DRY-RUN copy"
        print(f"{action} {src} -> {dst}")
        return False

    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def is_image_path(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def detect_media_suffix(path: Path) -> str | None:
    try:
        header = path.read_bytes()[:32]
    except OSError:
        return None

    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if header.startswith(b"BM"):
        return ".bmp"
    if b"<svg" in header.lower() or header.lstrip().startswith(b"<?xml"):
        return ".svg"
    if header.startswith(b"%PDF-"):
        return ".pdf"
    return None


def is_invalid_media_path(path: Path) -> bool:
    return is_image_path(path) and detect_media_suffix(path) is None


def markdown_link_destination(path: Path) -> str:
    target = unicodedata.normalize("NFC", path.as_posix())
    return quote(target, safe="/:@")


def slugify_filename_stem(stem: str, max_length: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", stem)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "media")[:max_length].strip("-") or "media"


def portable_media_destination(src: Path, note_dest: Path) -> Path:
    digest = sha256_file(src)[:8]
    suffix = detect_media_suffix(src) or src.suffix.lower()
    stem = slugify_filename_stem(src.stem)
    return note_dest.parent / "_media" / f"{stem}-{digest}{suffix}"


def export_media_destination(
    src: Path,
    output_dir: Path,
    vault_root: Path,
    note_dest: Path,
    portable_media_names: bool,
) -> Path:
    if portable_media_names:
        return portable_media_destination(src, note_dest)
    return output_dir / rel(src, vault_root)


def universal_media_link(
    media_path: Path,
    relative_url: str,
    label: str | None = None,
    force_embed: bool = False,
) -> str:
    if force_embed or is_image_path(media_path):
        return f"![]({relative_url})"

    text = label or media_path.name
    text = text.replace("[", "\\[").replace("]", "\\]")
    return f"[{text}]({relative_url})"


def rewrite_note_links_for_export(
    text: str,
    resolved_items: Sequence[ResolvedReference],
    note_dest: Path,
    media_dest_by_src: dict[Path, Path],
) -> tuple[str, int]:
    by_kind_and_target: dict[tuple[str, str], ResolvedReference] = {}
    for item in resolved_items:
        if item.resolved_path is None:
            continue
        by_kind_and_target[(item.reference.kind, item.reference.normalized_target)] = (
            item
        )

    rewrite_count = 0

    def relative_url_for(item: ResolvedReference) -> str:
        assert item.resolved_path is not None
        media_dest = media_dest_by_src[item.resolved_path.resolve()]
        relative_path = Path(os.path.relpath(media_dest, note_dest.parent))
        return markdown_link_destination(relative_path)

    def wikilink_replacer(match: re.Match[str]) -> str:
        nonlocal rewrite_count
        raw = match.group(1)
        target = normalize_obsidian_target(raw)
        item = by_kind_and_target.get(("wikilink", target))
        if item is None or item.resolved_path is None:
            return match.group(0)

        rewrite_count += 1
        return universal_media_link(
            item.resolved_path,
            relative_url_for(item),
            force_embed=item.reference.is_embed,
        )

    def markdown_replacer(match: re.Match[str]) -> str:
        nonlocal rewrite_count
        original = match.group(0)
        is_embed = original.startswith("!")
        label_match = re.match(r"!?\[([^\]]*)\]", original)
        label = label_match.group(1) if label_match else None
        raw = match.group(1)
        target = normalize_markdown_url(raw)
        item = by_kind_and_target.get(("markdown", target))
        if item is None or item.resolved_path is None:
            return original

        rewrite_count += 1
        if is_embed or is_image_path(item.resolved_path):
            return universal_media_link(
                item.resolved_path, relative_url_for(item), force_embed=True
            )
        return universal_media_link(
            item.resolved_path, relative_url_for(item), label=label
        )

    def html_img_replacer(match: re.Match[str]) -> str:
        nonlocal rewrite_count
        raw = match.group(1)
        target = normalize_markdown_url(raw)
        item = by_kind_and_target.get(("html-img", target))
        if item is None or item.resolved_path is None:
            return match.group(0)

        rewrite_count += 1
        return universal_media_link(
            item.resolved_path, relative_url_for(item), force_embed=True
        )

    rewritten = WIKILINK_RE.sub(wikilink_replacer, text)
    rewritten = MARKDOWN_LINK_RE.sub(markdown_replacer, rewritten)
    rewritten = HTML_IMG_RE.sub(html_img_replacer, rewritten)
    return rewritten, rewrite_count


def export_note_with_media(
    index: VaultIndex,
    note_query: str,
    output_dir: Path,
    dry_run: bool,
    rewrite_links: bool,
    portable_media_names: bool,
    overwrite: bool,
) -> None:
    note = find_note(index, note_query)
    output_dir = output_dir.resolve()

    print("Mode export copie : les fichiers sources ne sont pas modifiés.")
    if dry_run:
        print("Simulation active : aucune copie ne sera effectuée.")
    if rewrite_links:
        print(
            "Réécriture active : les liens de la copie seront convertis en Markdown universel."
        )
    if portable_media_names:
        print(
            "Noms médias portables : les médias copiés seront renommés en ASCII dans _media/."
        )
    if overwrite:
        print(
            "Écrasement actif : les fichiers existants dans la sortie pourront être remplacés."
        )
    print()

    note_dest = output_dir / rel(note, index.vault_root)
    note_copied = safe_copy(note, note_dest, dry_run=dry_run, overwrite=overwrite)

    resolved_items = index.resolved_by_note.get(note, [])
    copied: set[Path] = set()
    skipped: set[Path] = set()
    handled: set[Path] = set()
    media_dest_by_src: dict[Path, Path] = {}

    for item in resolved_items:
        if item.resolved_path is None:
            print(
                f"WARN unresolved {item.status}: {rel(note, index.vault_root)} -> {item.reference.raw}"
            )
            continue

        src = item.resolved_path.resolve()
        if is_image_path(src) and detect_media_suffix(src) is None:
            print(
                f"WARN media illisible ou format non reconnu : {rel(src, index.vault_root)}"
            )

        media_dest = export_media_destination(
            src, output_dir, index.vault_root, note_dest, portable_media_names
        )
        media_dest_by_src[src] = media_dest

        if src in handled:
            continue

        if safe_copy(src, media_dest, dry_run=dry_run, overwrite=overwrite):
            copied.add(src)
        else:
            skipped.add(src)
        handled.add(src)

    if rewrite_links:
        if dry_run:
            print(f"DRY-RUN rewrite links in {note_dest}")
        elif not note_copied:
            print(
                f"SKIP rewrite links in existing note without --overwrite: {note_dest}"
            )
        else:
            original_text = read_text_lossy(note)
            rewritten_text, rewrite_count = rewrite_note_links_for_export(
                original_text,
                resolved_items,
                note_dest,
                media_dest_by_src,
            )
            note_dest.write_text(rewritten_text, encoding="utf-8")
            print(f"Liens réécrits dans la copie : {rewrite_count}")

    print(f"Note exportée : {rel(note, index.vault_root)}")
    print(f"Médias copiés : {len(copied)}")
    if skipped:
        print(f"Médias ignorés car déjà existants : {len(skipped)}")


def note_has_blocking_media_references(index: VaultIndex, note: Path) -> bool:
    for item in index.resolved_by_note.get(note, []):
        if item.status == "missing" or item.status.startswith("ambiguous"):
            return True
        if item.resolved_path is not None and is_invalid_media_path(item.resolved_path):
            return True
    return False


def find_notes_in_folder(index: VaultIndex, folder_query: str) -> list[Path]:
    folder = (index.vault_root / folder_query).resolve()
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Dossier introuvable dans le vault : {folder_query}")

    return [note for note in index.notes if note == folder or folder in note.parents]


def find_support_files_in_folder(index: VaultIndex, folder_query: str) -> list[Path]:
    folder = (index.vault_root / folder_query).resolve()
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Dossier introuvable dans le vault : {folder_query}")

    return sorted(
        path.resolve()
        for path in iter_files(folder)
        if path.suffix.lower() in SUPPORT_FILE_EXTENSIONS
    )


def export_support_files(
    index: VaultIndex,
    files: Sequence[Path],
    output_dir: Path,
    dry_run: bool,
    overwrite: bool,
) -> int:
    copied = 0
    for src in files:
        dst = output_dir / rel(src, index.vault_root)
        if safe_copy(src, dst, dry_run=dry_run, overwrite=overwrite):
            copied += 1
    return copied


def export_folder_notes(
    index: VaultIndex,
    folder_query: str,
    output_dir: Path,
    dry_run: bool,
    rewrite_links: bool,
    include_blocked: bool,
    portable_media_names: bool,
    overwrite: bool,
) -> None:
    notes = find_notes_in_folder(index, folder_query)
    support_files = find_support_files_in_folder(index, folder_query)
    valid_notes = [
        note for note in notes if not note_has_blocking_media_references(index, note)
    ]
    blocked_notes = [
        note for note in notes if note_has_blocking_media_references(index, note)
    ]

    selected_notes = notes if include_blocked else valid_notes

    print(
        "Export de dossier en mode copie : les fichiers sources ne sont pas modifiés."
    )
    if dry_run:
        print("Simulation active : aucune copie ne sera effectuée.")
    if rewrite_links:
        print(
            "Réécriture active : les liens des copies seront convertis en Markdown universel."
        )
    if portable_media_names:
        print(
            "Noms médias portables : les médias copiés seront renommés en ASCII dans _media/."
        )
    if overwrite:
        print(
            "Écrasement actif : les fichiers existants dans la sortie pourront être remplacés."
        )
    print()
    print(f"Dossier source : {folder_query}")
    print(f"Notes trouvées : {len(notes)}")
    print(f"Notes valides : {len(valid_notes)}")
    print(f"Notes bloquées : {len(blocked_notes)}")
    print(f"Notes exportées : {len(selected_notes)}")
    print(f"Fichiers .base trouvés : {len(support_files)}")
    print()

    total_media = 0
    for note in selected_notes:
        export_note_with_media(
            index,
            rel(note, index.vault_root),
            output_dir,
            dry_run=dry_run,
            rewrite_links=rewrite_links,
            portable_media_names=portable_media_names,
            overwrite=overwrite,
        )
        total_media += len(
            {
                item.resolved_path
                for item in index.resolved_by_note.get(note, [])
                if item.resolved_path is not None
            }
        )

    copied_support_files = export_support_files(
        index,
        support_files,
        output_dir.resolve(),
        dry_run=dry_run,
        overwrite=overwrite,
    )

    if blocked_notes and not include_blocked:
        print()
        print("Notes ignorées car non valides :")
        for note in blocked_notes[:50]:
            print(f"- {rel(note, index.vault_root)}")
        if len(blocked_notes) > 50:
            print(f"... {len(blocked_notes) - 50} autres")

    print()
    print(
        "Export terminé : "
        f"{len(selected_notes)} notes, "
        f"{total_media} médias référencés copiables, "
        f"{copied_support_files} fichiers .base copiés."
    )


def print_summary(index: VaultIndex) -> None:
    used = referenced_media(index)
    orphan = set(index.media) - used

    missing_count = sum(
        1
        for refs in index.resolved_by_note.values()
        for item in refs
        if item.status == "missing"
    )
    ambiguous_count = sum(
        1
        for refs in index.resolved_by_note.values()
        for item in refs
        if item.status.startswith("ambiguous")
    )

    print("Résumé du vault")
    print("---------------")
    print(f"Notes Markdown       : {len(index.notes)}")
    print(f"Fichiers médias      : {len(index.media)}")
    print(f"Médias référencés    : {len(used)}")
    print(f"Médias orphelins     : {len(orphan)}")
    print(f"Références manquantes: {missing_count}")
    print(f"Références ambiguës  : {ambiguous_count}")


def list_orphans(index: VaultIndex, limit: int | None) -> None:
    used = referenced_media(index)
    orphan = sorted(set(index.media) - used)

    for path in orphan[:limit]:
        print(rel(path, index.vault_root))

    if limit is not None and len(orphan) > limit:
        print(f"... {len(orphan) - limit} autres médias orphelins")


def list_missing(index: VaultIndex, limit: int | None) -> None:
    items = [
        item
        for refs in index.resolved_by_note.values()
        for item in refs
        if item.status == "missing"
    ]

    for item in items[:limit]:
        print(
            f"{rel(item.reference.source_note, index.vault_root)} -> {item.reference.raw}"
        )

    if limit is not None and len(items) > limit:
        print(f"... {len(items) - limit} autres références manquantes")


def top_folder(path: Path, root: Path) -> str:
    relative = rel(path, root)
    return relative.split("/", 1)[0] if "/" in relative else "(racine)"


def classify_missing_target(target: str, raw: str) -> str:
    parsed = urlparse(target)

    if parsed.scheme or parsed.netloc:
        return "url-ou-chemin-externe"
    if target.startswith("../"):
        return "chemin-parent-relatif"
    if target.startswith("./"):
        return "chemin-point-relatif"
    if target.startswith("/"):
        return "chemin-absolu-local"
    if "%" in raw:
        return "url-encode"
    if target.startswith("path/to/"):
        return "exemple-ou-placeholder"
    if target.count("(") != target.count(")") or raw.count("(") != raw.count(")"):
        return "parentheses-suspectes"
    if "/" not in target:
        return "nom-seul"
    return "autre-chemin"


def build_diagnosis(index: VaultIndex, limit: int | None) -> dict[str, object]:
    used = referenced_media(index)
    orphan = sorted(set(index.media) - used)
    missing = [
        item
        for refs in index.resolved_by_note.values()
        for item in refs
        if item.status == "missing"
    ]
    ambiguous = [
        item
        for refs in index.resolved_by_note.values()
        for item in refs
        if item.status.startswith("ambiguous")
    ]
    invalid_media = [
        item
        for refs in index.resolved_by_note.values()
        for item in refs
        if item.resolved_path is not None and is_invalid_media_path(item.resolved_path)
    ]

    missing_by_folder = Counter(
        top_folder(item.reference.source_note, index.vault_root) for item in missing
    )
    missing_by_kind = Counter(item.reference.kind for item in missing)
    missing_by_category = Counter(
        classify_missing_target(item.reference.normalized_target, item.reference.raw)
        for item in missing
    )
    orphan_by_folder = Counter(
        rel(path, index.vault_root).split("/", 1)[0]
        if "/" in rel(path, index.vault_root)
        else "(racine)"
        for path in orphan
    )

    sample_limit = limit if limit is not None else 50

    return {
        "vault": index.vault_root.as_posix(),
        "summary": {
            "notes": len(index.notes),
            "media": len(index.media),
            "referenced_media": len(used),
            "orphan_media": len(orphan),
            "missing_references": len(missing),
            "ambiguous_references": len(ambiguous),
            "invalid_media_references": len(invalid_media),
        },
        "missing_by_folder": dict(missing_by_folder.most_common()),
        "missing_by_kind": dict(missing_by_kind.most_common()),
        "missing_by_category": dict(missing_by_category.most_common()),
        "orphan_by_folder": dict(orphan_by_folder.most_common()),
        "missing_samples": [
            {
                "note": rel(item.reference.source_note, index.vault_root),
                "raw": item.reference.raw,
                "target": item.reference.normalized_target,
                "kind": item.reference.kind,
                "category": classify_missing_target(
                    item.reference.normalized_target, item.reference.raw
                ),
            }
            for item in missing[:sample_limit]
        ],
        "missing_references": [
            {
                "note": rel(item.reference.source_note, index.vault_root),
                "raw": item.reference.raw,
                "target": item.reference.normalized_target,
                "kind": item.reference.kind,
                "category": classify_missing_target(
                    item.reference.normalized_target, item.reference.raw
                ),
            }
            for item in missing
        ],
        "orphan_media": [rel(path, index.vault_root) for path in orphan],
        "invalid_media_references": [
            {
                "note": rel(item.reference.source_note, index.vault_root),
                "raw": item.reference.raw,
                "resolved": rel(item.resolved_path, index.vault_root)
                if item.resolved_path
                else None,
            }
            for item in invalid_media
        ],
        "ambiguous_samples": [
            {
                "note": rel(item.reference.source_note, index.vault_root),
                "raw": item.reference.raw,
                "target": item.reference.normalized_target,
                "chosen": rel(item.resolved_path, index.vault_root)
                if item.resolved_path
                else None,
                "candidates": [
                    rel(candidate, index.vault_root) for candidate in item.candidates
                ],
            }
            for item in ambiguous[:sample_limit]
        ],
        "ambiguous_references": [
            {
                "note": rel(item.reference.source_note, index.vault_root),
                "raw": item.reference.raw,
                "target": item.reference.normalized_target,
                "chosen": rel(item.resolved_path, index.vault_root)
                if item.resolved_path
                else None,
                "candidates": [
                    rel(candidate, index.vault_root) for candidate in item.candidates
                ],
            }
            for item in ambiguous
        ],
    }


def print_counter(title: str, values: dict[str, int], limit: int) -> None:
    print(title)
    print("-" * len(title))
    for key, count in list(values.items())[:limit]:
        print(f"{key}: {count}")
    if len(values) > limit:
        print(f"... {len(values) - limit} autres")
    print()


def diagnose(index: VaultIndex, output: Path | None, limit: int) -> None:
    diagnosis = build_diagnosis(index, limit)

    summary = diagnosis["summary"]
    assert isinstance(summary, dict)

    print("Diagnostic du vault")
    print("-------------------")
    print(f"Notes Markdown       : {summary['notes']}")
    print(f"Fichiers médias      : {summary['media']}")
    print(f"Médias référencés    : {summary['referenced_media']}")
    print(f"Médias orphelins     : {summary['orphan_media']}")
    print(f"Références manquantes: {summary['missing_references']}")
    print(f"Références ambiguës  : {summary['ambiguous_references']}")
    print(f"Médias invalides     : {summary['invalid_media_references']}")
    print()

    print_counter(
        "Références manquantes par dossier", diagnosis["missing_by_folder"], 20
    )
    print_counter("Références manquantes par type", diagnosis["missing_by_kind"], 20)
    print_counter(
        "Références manquantes par catégorie", diagnosis["missing_by_category"], 20
    )
    print_counter("Médias orphelins par dossier", diagnosis["orphan_by_folder"], 20)

    print("Exemples de références manquantes")
    print("---------------------------------")
    for item in diagnosis["missing_samples"]:
        print(f"{item['note']} -> {item['raw']} [{item['category']}]")
    print()

    print("Exemples de références ambiguës")
    print("-------------------------------")
    for item in diagnosis["ambiguous_samples"]:
        print(f"{item['note']} -> {item['raw']}")
        print(f"  choisi: {item['chosen']}")
        print(f"  candidats: {len(item['candidates'])}")
    print()

    if output is not None:
        output.write_text(
            json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"Diagnostic JSON écrit : {output}")


def markdown_table(headers: Sequence[str], rows: Iterable[Sequence[object]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        cells = [str(cell).replace("\n", " ").replace("|", "\\|") for cell in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_markdown_report(path: Path, title: str, body: str) -> None:
    path.write_text(f"# {title}\n\n{body.rstrip()}\n", encoding="utf-8")


def analyze_exportable_notes(index: VaultIndex) -> dict[str, list[dict[str, object]]]:
    exportable_with_media: list[dict[str, object]] = []
    exportable_without_media: list[dict[str, object]] = []
    blocked: list[dict[str, object]] = []

    for note in index.notes:
        items = index.resolved_by_note.get(note, [])
        media_items = [item for item in items if item.status != "external"]
        resolved_items = [
            item for item in media_items if item.resolved_path is not None
        ]
        missing_items = [item for item in media_items if item.status == "missing"]
        ambiguous_items = [
            item for item in media_items if item.status.startswith("ambiguous")
        ]
        invalid_media_items = [
            item
            for item in resolved_items
            if item.resolved_path is not None
            and is_invalid_media_path(item.resolved_path)
        ]

        payload = {
            "note": rel(note, index.vault_root),
            "media_count": len(resolved_items),
            "missing_count": len(missing_items),
            "ambiguous_count": len(ambiguous_items),
            "invalid_media_count": len(invalid_media_items),
        }

        if missing_items or ambiguous_items or invalid_media_items:
            blocked.append(payload)
        elif resolved_items:
            exportable_with_media.append(payload)
        else:
            exportable_without_media.append(payload)

    return {
        "exportable_with_media": exportable_with_media,
        "exportable_without_media": exportable_without_media,
        "blocked": blocked,
    }


def blocked_note_details(index: VaultIndex) -> list[dict[str, object]]:
    blocked: list[dict[str, object]] = []

    for note in index.notes:
        items = [
            item
            for item in index.resolved_by_note.get(note, [])
            if item.status != "external"
        ]
        missing_items = [item for item in items if item.status == "missing"]
        ambiguous_items = [
            item for item in items if item.status.startswith("ambiguous")
        ]
        invalid_media_items = [
            item
            for item in items
            if item.resolved_path is not None
            and is_invalid_media_path(item.resolved_path)
        ]

        if not (missing_items or ambiguous_items or invalid_media_items):
            continue

        note_rel = rel(note, index.vault_root)
        blocked.append(
            {
                "note": note_rel,
                "folder": top_folder(note, index.vault_root),
                "missing": missing_items,
                "ambiguous": ambiguous_items,
                "invalid": invalid_media_items,
            }
        )

    return sorted(blocked, key=lambda item: str(item["note"]).lower())


def obsidian_open_uri(index: VaultIndex, note_rel: str) -> str:
    vault_name = index.vault_root.name
    return f"obsidian://open?vault={quote(vault_name, safe='')}&file={quote(note_rel, safe='')}"


def markdown_link_label(text: str) -> str:
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def markdown_uri_link(label: str, uri: str) -> str:
    return f"[{markdown_link_label(label)}]({uri})"


def blocked_notes_markdown(index: VaultIndex) -> str:
    blocked = blocked_note_details(index)
    by_folder = Counter(str(item["folder"]) for item in blocked)
    total_missing = sum(len(item["missing"]) for item in blocked)
    total_ambiguous = sum(len(item["ambiguous"]) for item in blocked)
    total_invalid = sum(len(item["invalid"]) for item in blocked)

    lines: list[str] = [
        "Liste de travail pour corriger ou jeter les notes non exportables dans le vault source.",
        "",
        f"- Vault source : `{index.vault_root}`",
        f"- Notes bloquées : {len(blocked)}",
        f"- Références manquantes : {total_missing}",
        f"- Références ambiguës : {total_ambiguous}",
        f"- Médias invalides : {total_invalid}",
        "",
        "## Par dossier",
        "",
        markdown_table(("Dossier", "Notes bloquées"), by_folder.most_common()),
        "",
        "## Notes à traiter",
        "",
    ]

    current_folder = None
    for item in blocked:
        folder = str(item["folder"])
        note = str(item["note"])
        note_path = index.vault_root / note
        note_uri = obsidian_open_uri(index, note)

        if folder != current_folder:
            current_folder = folder
            lines.extend(["", f"### {folder}", ""])

        lines.append(f"- [ ] {markdown_uri_link(note, note_uri)}")
        lines.append(f"  - Fichier source : `{note_path}`")

        missing_items = item["missing"]
        ambiguous_items = item["ambiguous"]
        invalid_items = item["invalid"]

        if missing_items:
            lines.append("  - Références manquantes :")
            for ref in missing_items:
                lines.append(f"    - `{ref.reference.raw}`")

        if ambiguous_items:
            lines.append("  - Références ambiguës :")
            for ref in ambiguous_items:
                lines.append(f"    - `{ref.reference.raw}`")
                if ref.resolved_path is not None:
                    lines.append(
                        f"      - choix actuel : `{rel(ref.resolved_path, index.vault_root)}`"
                    )
                for candidate in ref.candidates:
                    lines.append(
                        f"      - candidat : `{rel(candidate, index.vault_root)}`"
                    )

        if invalid_items:
            lines.append("  - Médias invalides :")
            for ref in invalid_items:
                resolved = ref.resolved_path
                resolved_rel = (
                    rel(resolved, index.vault_root)
                    if resolved is not None
                    else "(introuvable)"
                )
                lines.append(f"    - `{ref.reference.raw}` -> `{resolved_rel}`")

    if not blocked:
        lines.append("Aucune note bloquée.")

    return "\n".join(lines).strip()


def exportable_notes_markdown(index: VaultIndex, limit: int | None = None) -> str:
    groups = analyze_exportable_notes(index)
    exportable_with_media = groups["exportable_with_media"]
    exportable_without_media = groups["exportable_without_media"]
    blocked = groups["blocked"]

    def limited(rows: list[dict[str, object]]) -> list[dict[str, object]]:
        return rows if limit is None else rows[:limit]

    sections = [
        f"- Notes exportables avec médias : {len(exportable_with_media)}",
        f"- Notes exportables sans média : {len(exportable_without_media)}",
        f"- Notes bloquées par références manquantes, ambiguës ou médias invalides : {len(blocked)}",
        "",
        "## Exportables avec médias",
        markdown_table(
            ("Médias", "Note"),
            (
                (item["media_count"], item["note"])
                for item in limited(exportable_with_media)
            ),
        ),
        "",
        "## Exportables sans média",
        markdown_table(
            ("Note",),
            ((item["note"],) for item in limited(exportable_without_media)),
        ),
        "",
        "## Bloquées",
        markdown_table(
            ("Manquantes", "Ambiguës", "Médias invalides", "Médias résolus", "Note"),
            (
                (
                    item["missing_count"],
                    item["ambiguous_count"],
                    item["invalid_media_count"],
                    item["media_count"],
                    item["note"],
                )
                for item in limited(blocked)
            ),
        ),
    ]

    if limit is not None:
        sections.extend(["", f"_Chaque liste est limitée à {limit} lignes._"])

    return "\n".join(sections)


def write_exportable_notes_report(
    index: VaultIndex, output: Path, limit: int | None
) -> None:
    write_markdown_report(
        output, "Notes exportables", exportable_notes_markdown(index, limit)
    )
    print(f"Liste des notes exportables écrite : {output}")


def write_blocked_notes_report(index: VaultIndex, output: Path) -> None:
    write_markdown_report(
        output, "Notes bloquées à corriger ou jeter", blocked_notes_markdown(index)
    )
    print(f"Liste des notes bloquées écrite : {output}")


def write_markdown_reports(index: VaultIndex, output_dir: Path, limit: int) -> None:
    diagnosis = build_diagnosis(index, None)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = diagnosis["summary"]
    assert isinstance(summary, dict)

    write_markdown_report(
        output_dir / "00_resume.md",
        "Résumé du diagnostic Obsidian",
        "\n".join(
            [
                f"- Vault : `{diagnosis['vault']}`",
                f"- Notes Markdown : {summary['notes']}",
                f"- Fichiers médias : {summary['media']}",
                f"- Médias référencés : {summary['referenced_media']}",
                f"- Médias orphelins : {summary['orphan_media']}",
                f"- Références manquantes : {summary['missing_references']}",
                f"- Références ambiguës : {summary['ambiguous_references']}",
                f"- Références vers médias invalides : {summary['invalid_media_references']}",
                "",
                "## Références manquantes par dossier",
                markdown_table(
                    ("Dossier", "Nombre"), diagnosis["missing_by_folder"].items()
                ),
                "",
                "## Références manquantes par catégorie",
                markdown_table(
                    ("Catégorie", "Nombre"), diagnosis["missing_by_category"].items()
                ),
                "",
                "## Médias orphelins par dossier",
                markdown_table(
                    ("Dossier", "Nombre"), diagnosis["orphan_by_folder"].items()
                ),
            ]
        ),
    )

    missing_refs = diagnosis["missing_references"]
    write_markdown_report(
        output_dir / "01_references_manquantes.md",
        "Références manquantes",
        markdown_table(
            ("Catégorie", "Type", "Note", "Cible"),
            (
                (item["category"], item["kind"], item["note"], item["raw"])
                for item in missing_refs
            ),
        ),
    )

    grouped_missing_lines = []
    current_category = None
    for item in sorted(
        missing_refs, key=lambda entry: (entry["category"], entry["note"], entry["raw"])
    ):
        if item["category"] != current_category:
            current_category = item["category"]
            grouped_missing_lines.extend(["", f"## {current_category}", ""])
        grouped_missing_lines.append(f"- `{item['note']}` -> `{item['raw']}`")

    write_markdown_report(
        output_dir / "02_references_manquantes_par_categorie.md",
        "Références manquantes par catégorie",
        "\n".join(grouped_missing_lines).strip(),
    )

    orphan_media = diagnosis["orphan_media"]
    orphan_lines = []
    current_folder = None
    for media in orphan_media:
        folder = media.split("/", 1)[0] if "/" in media else "(racine)"
        if folder != current_folder:
            current_folder = folder
            orphan_lines.extend(["", f"## {current_folder}", ""])
        orphan_lines.append(f"- `{media}`")

    write_markdown_report(
        output_dir / "03_medias_orphelins.md",
        "Médias orphelins",
        "\n".join(orphan_lines).strip(),
    )

    ambiguous_refs = diagnosis["ambiguous_references"]
    ambiguous_lines = []
    for item in ambiguous_refs:
        ambiguous_lines.append(f"## {item['note']}")
        ambiguous_lines.append("")
        ambiguous_lines.append(f"- Référence : `{item['raw']}`")
        ambiguous_lines.append(f"- Choix actuel : `{item['chosen']}`")
        ambiguous_lines.append("- Candidats :")
        for candidate in item["candidates"]:
            ambiguous_lines.append(f"  - `{candidate}`")
        ambiguous_lines.append("")

    write_markdown_report(
        output_dir / "04_references_ambigues.md",
        "Références ambiguës",
        "\n".join(ambiguous_lines).strip() or "Aucune référence ambiguë.",
    )

    invalid_media_refs = diagnosis["invalid_media_references"]
    write_markdown_report(
        output_dir / "04b_medias_invalides.md",
        "Médias invalides",
        markdown_table(
            ("Note", "Référence", "Fichier résolu"),
            (
                (item["note"], item["raw"], item["resolved"])
                for item in invalid_media_refs
            ),
        )
        if invalid_media_refs
        else "Aucun média invalide détecté.",
    )

    suspicious = [
        item
        for item in missing_refs
        if item["category"]
        in {"chemin-parent-relatif", "chemin-point-relatif", "parentheses-suspectes"}
    ]
    write_markdown_report(
        output_dir / "05_chemins_suspects.md",
        "Chemins suspects",
        markdown_table(
            ("Catégorie", "Note", "Cible"),
            ((item["category"], item["note"], item["raw"]) for item in suspicious),
        ),
    )

    top_missing = missing_refs[:limit]
    write_markdown_report(
        output_dir / "06_a_traiter_en_premier.md",
        "À traiter en premier",
        "\n".join(
            [
                "Ces éléments sont les premiers exemples du diagnostic. Ils servent de liste de départ pour améliorer le résolveur ou corriger quelques notes à la main.",
                "",
                markdown_table(
                    ("Catégorie", "Type", "Note", "Cible"),
                    (
                        (item["category"], item["kind"], item["note"], item["raw"])
                        for item in top_missing
                    ),
                ),
            ]
        ),
    )

    write_markdown_report(
        output_dir / "07_notes_exportables.md",
        "Notes exportables",
        exportable_notes_markdown(index, None),
    )

    write_markdown_report(
        output_dir / "08_notes_bloquees_a_corriger_ou_jeter.md",
        "Notes bloquées à corriger ou jeter",
        blocked_notes_markdown(index),
    )

    print(f"Rapports Markdown écrits dans : {output_dir}")


def parse_history_line(line: str) -> tuple[dt.datetime | None, str] | None:
    line = line.rstrip("\n")
    if not line.strip():
        return None

    match = ZSH_HISTORY_RE.match(line)
    if match:
        timestamp = dt.datetime.fromtimestamp(
            int(match.group("timestamp"))
        ).astimezone()
        command = match.group("command").strip()
        return timestamp, command

    command = line.strip()
    return None, command


def command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def is_history_noise(command: str) -> bool:
    stripped = command.strip()
    if not stripped:
        return True

    noise_values = {"\\", "EOF", "{", "}", "{\\", "}\\"}
    if stripped in noise_values:
        return True

    if re.fullmatch(r"\d+\.?", stripped):
        return True

    if stripped.endswith("\\"):
        first = (
            Path(command_tokens(stripped)[0]).name if command_tokens(stripped) else ""
        )
        return first not in {
            "cd",
            "git",
            "uv",
            "python",
            "python3",
            "rg",
            "fd",
            "ls",
            "cat",
            "sed",
            "curl",
        }

    if re.match(r"^['\"]?[A-Za-z0-9_.-]+['\"]?\s*:", stripped):
        return True

    return False


def command_family(command: str) -> str:
    tokens = command_tokens(command)
    if not tokens:
        return "(vide)"

    first = Path(tokens[0].rstrip(";")).name
    if first == "uv" and len(tokens) >= 3 and tokens[1] == "run":
        if tokens[2] == "-m" and len(tokens) >= 4:
            return f"uv run -m {tokens[3].rstrip(';')}"
        return f"uv run {Path(tokens[2].rstrip(';')).name}"
    if first in {"python", "python3"} and len(tokens) >= 2:
        return f"{first} {Path(tokens[1].rstrip(';')).name}"
    if first == "git" and len(tokens) >= 2:
        return f"git {tokens[1].rstrip(';')}"
    return first


def current_user_home() -> Path | None:
    for name in ("HOME", "USERPROFILE"):
        value = os.environ.get(name)
        if value:
            return Path(value)

    if pwd is not None:
        try:
            return Path(pwd.getpwuid(os.getuid()).pw_dir)
        except (KeyError, OSError):
            return None

    return None


def expand_user_path(path: Path) -> Path:
    text = path.as_posix()
    if not text.startswith("~"):
        return path

    home = current_user_home()
    if home is None:
        return path

    if text == "~":
        return home
    if text.startswith("~/"):
        return home / text[2:]
    return path


def normalize_history_path(path_text: str, base_dir: Path | None) -> Path:
    expanded = expand_user_path(Path(path_text))
    if expanded.is_absolute():
        return expanded.resolve()
    if base_dir is not None:
        return (base_dir / expanded).resolve()
    return expanded


def update_inferred_cwd(command: str, current_cwd: Path | None) -> Path | None:
    tokens = command_tokens(command)
    if not tokens or Path(tokens[0]).name != "cd":
        return current_cwd
    if len(tokens) == 1:
        return current_user_home()
    if tokens[1] == "-":
        return current_cwd
    target = expand_user_path(Path(tokens[1]))
    if not target.is_absolute() and current_cwd is None:
        return current_cwd
    new_cwd = normalize_history_path(tokens[1], current_cwd)
    if new_cwd.exists() and new_cwd.is_dir():
        return new_cwd
    return current_cwd


def command_path_hints(command: str) -> list[Path]:
    hints: list[Path] = []
    for match in ABSOLUTE_PATH_RE.finditer(command):
        raw = match.group("path").rstrip("),]")
        hints.append(expand_user_path(Path(raw)))
    return hints


def label_for_path_hint(path: Path) -> str:
    parts = path.parts
    if path == Path("/"):
        return "(racine système)"

    if "Pythons" in parts:
        index = parts.index("Pythons")
        if len(parts) > index + 1:
            return parts[index + 1]
        return "Pythons"

    if "Users" in parts:
        index = parts.index("Users")
        if len(parts) > index + 2:
            return parts[index + 2]

    return path.name or path.as_posix()


def project_label_for_command(
    command: str,
    inferred_cwd: Path | None,
    project_roots: Sequence[Path],
) -> str:
    candidates = command_path_hints(command) + (
        [inferred_cwd] if inferred_cwd is not None else []
    )
    resolved_roots = [(root.resolve(), root.resolve().name) for root in project_roots]

    for candidate in candidates:
        try:
            resolved_candidate = candidate.resolve()
        except OSError:
            resolved_candidate = candidate

        for root, label in resolved_roots:
            if resolved_candidate == root or root in resolved_candidate.parents:
                return label

    for candidate in candidates:
        if candidate.is_absolute():
            return label_for_path_hint(candidate)

    if inferred_cwd is not None:
        if inferred_cwd == Path("/"):
            return "(racine système)"
        return label_for_path_hint(inferred_cwd)
    return "(sans dossier détecté)"


def read_shell_history(
    history_path: Path,
    limit: int | None,
    project_roots: Sequence[Path],
) -> list[ShellCommandEntry]:
    history_path = expand_user_path(history_path)
    if not history_path.exists():
        raise FileNotFoundError(f"Historique introuvable : {history_path}")

    lines = history_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if limit is not None and limit > 0:
        lines = lines[-limit:]

    entries: list[ShellCommandEntry] = []
    current_cwd: Path | None = None

    for line in lines:
        parsed = parse_history_line(line)
        if parsed is None:
            continue

        timestamp, command = parsed
        if is_history_noise(command):
            continue

        project = project_label_for_command(command, current_cwd, project_roots)
        entries.append(
            ShellCommandEntry(
                command=command,
                timestamp=timestamp,
                inferred_cwd=current_cwd,
                family=command_family(command),
                project=project,
            )
        )
        current_cwd = update_inferred_cwd(command, current_cwd)

    return entries


def format_history_time(timestamp: dt.datetime | None) -> str:
    if timestamp is None:
        return ""
    return timestamp.strftime("%Y-%m-%d %H:%M")


def fenced_commands(entries: Sequence[ShellCommandEntry]) -> str:
    if not entries:
        return "_Aucune commande._"
    return "```bash\n" + "\n".join(entry.command for entry in entries) + "\n```"


def most_common_entries(
    entries: Sequence[ShellCommandEntry], top: int
) -> list[tuple[str, int]]:
    return Counter(entry.command for entry in entries).most_common(top)


def terminal_command_id(entry: ShellCommandEntry) -> str:
    cwd = entry.inferred_cwd.as_posix() if entry.inferred_cwd is not None else ""
    payload = f"{cwd}\0{entry.command}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def effective_command_cwd(
    entry: ShellCommandEntry, project_roots: Sequence[Path]
) -> Path | None:
    inferred = (
        entry.inferred_cwd.resolve()
        if entry.inferred_cwd is not None and entry.inferred_cwd.exists()
        else None
    )
    roots = [root.resolve() for root in project_roots]

    for root in roots:
        if entry.project != root.name:
            continue
        if inferred is not None and (inferred == root or root in inferred.parents):
            return inferred
        return root

    return inferred


def terminal_command_payload(
    entry: ShellCommandEntry, project_roots: Sequence[Path]
) -> dict[str, str | None]:
    run_cwd = effective_command_cwd(entry, project_roots)
    return {
        "command": entry.command,
        "cwd": run_cwd.as_posix() if run_cwd is not None else None,
        "project": entry.project,
        "family": entry.family,
        "timestamp": entry.timestamp.isoformat()
        if entry.timestamp is not None
        else None,
    }


def write_terminal_command_runner(launcher_dir: Path) -> Path:
    launcher_dir.mkdir(parents=True, exist_ok=True)
    for old_launcher in launcher_dir.glob("*.command"):
        if old_launcher.name == TERMINAL_COMMAND_RUNNER_NAME:
            continue
        if re.fullmatch(r"[0-9a-f]{16}\.command", old_launcher.name):
            old_launcher.unlink()

    launcher = launcher_dir / TERMINAL_COMMAND_RUNNER_NAME
    registry = launcher_dir / TERMINAL_COMMAND_REGISTRY_NAME
    lines = [
        "#!/bin/zsh",
        "set -e",
        "",
        f"REGISTRY={shlex.quote(registry.as_posix())}",
        'if [[ ! -f "$REGISTRY" ]]; then',
        '  echo "Registre introuvable : $REGISTRY"',
        "  read _",
        "  exit 1",
        "fi",
        "",
        "echo 'Identifiant de commande :'",
        "printf '> '",
        "read command_id",
        'if [[ -z "$command_id" ]]; then',
        "  echo 'Annulé.'",
        "  exit 0",
        "fi",
        "",
        'payload=$(python3 - "$REGISTRY" "$command_id" <<\'PY\'',
        "import json, sys",
        "registry, command_id = sys.argv[1], sys.argv[2]",
        "with open(registry, encoding='utf-8') as fh:",
        "    data = json.load(fh)",
        "item = data.get('commands', {}).get(command_id)",
        "if item is None:",
        "    raise SystemExit(f'Identifiant inconnu : {command_id}')",
        "print(json.dumps(item, ensure_ascii=False))",
        "PY",
        ")",
        'command=$(python3 -c \'import json,sys; print(json.loads(sys.argv[1])["command"])\' "$payload")',
        'cwd=$(python3 -c \'import json,sys; print(json.loads(sys.argv[1]).get("cwd") or "")\' "$payload")',
        "",
        "echo",
        "echo 'Commande sélectionnée :'",
        "printf '%s\\n' \"$command\"",
        'if [[ -n "$cwd" ]]; then',
        "  echo",
        '  echo "Dossier : $cwd"',
        "fi",
        "",
        "echo",
        "printf 'Relancer cette commande ? taper oui pour confirmer : '",
        "read confirmation",
        'if [[ "$confirmation" != "oui" ]]; then',
        "  echo 'Annulé.'",
        "  exit 0",
        "fi",
        'if [[ -n "$cwd" ]]; then',
        '  cd "$cwd"',
        "fi",
        "echo",
        'eval "$command"',
        "",
        "echo",
        "printf 'Terminé. Appuyer sur Entrée pour fermer.'",
        "read _",
    ]

    launcher.write_text("\n".join(lines) + "\n", encoding="utf-8")
    launcher.chmod(0o755)
    return launcher


def register_terminal_command(
    entry: ShellCommandEntry,
    launcher_dir: Path,
    project_roots: Sequence[Path],
) -> tuple[str, Path]:
    launcher_dir.mkdir(parents=True, exist_ok=True)
    command_id = terminal_command_id(entry)
    registry = launcher_dir / TERMINAL_COMMAND_REGISTRY_NAME
    payload: dict[str, object]
    if registry.exists():
        try:
            payload = json.loads(registry.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}

    commands = payload.get("commands")
    if not isinstance(commands, dict):
        commands = {}
        payload["commands"] = commands
    commands[command_id] = terminal_command_payload(entry, project_roots)
    registry.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return command_id, write_terminal_command_runner(launcher_dir)


def markdown_command_cell(
    entry: ShellCommandEntry,
    launcher_dir: Path | None,
    markdown_base_dir: Path,
    project_roots: Sequence[Path],
) -> str:
    command = f"`{entry.command}`"
    if launcher_dir is None:
        return command

    command_id, runner = register_terminal_command(entry, launcher_dir, project_roots)
    link = Path(os.path.relpath(runner, markdown_base_dir)).as_posix()
    return f"[▶ {command_id}]({link}) {command}"


def markdown_common_command_cell(
    command: str,
    entries: Sequence[ShellCommandEntry],
    launcher_dir: Path | None,
    markdown_base_dir: Path,
    project_roots: Sequence[Path],
) -> str:
    if launcher_dir is None:
        return f"`{command}`"

    for entry in reversed(entries):
        if entry.command == command:
            return markdown_command_cell(
                entry, launcher_dir, markdown_base_dir, project_roots
            )
    return f"`{command}`"


def shell_dashboard_markdown(
    entries: Sequence[ShellCommandEntry],
    history_path: Path,
    project_roots: Sequence[Path],
    top: int,
    recent: int,
    launcher_dir: Path | None,
    markdown_base_dir: Path,
) -> str:
    now = dt.datetime.now().astimezone()
    dated_entries = [entry for entry in entries if entry.timestamp is not None]
    today_entries = [
        entry
        for entry in dated_entries
        if entry.timestamp is not None and entry.timestamp.date() == now.date()
    ]
    unique_entries = unique_latest_entries(entries)
    unique_today_entries = unique_latest_entries(today_entries)
    recent_entries = list(unique_entries[-recent:]) if recent > 0 else unique_entries
    project_counts = Counter(entry.project for entry in entries)
    family_counts = Counter(entry.family for entry in entries)

    lines: list[str] = [
        "# Tableau de bord terminal",
        "",
        f"- Généré le : {now.strftime('%Y-%m-%d %H:%M')}",
        f"- Historique lu : `{history_path}`",
        f"- Commandes analysées : {len(entries)}",
        f"- Commandes datées : {len(dated_entries)}",
        f"- Commandes sans date : {len(entries) - len(dated_entries)}",
        f"- Commandes uniques : {len(unique_entries)}",
        f"- Commandes aujourd'hui : {len(today_entries)}",
        f"- Commandes uniques aujourd'hui : {len(unique_today_entries)}",
        "",
        "## Racines suivies",
        "",
    ]

    if project_roots:
        lines.extend(f"- `{root}`" for root in project_roots)
    else:
        lines.append("- Aucune racine fournie.")

    lines.extend(
        [
            "",
            "## Commandes fréquentes",
            "",
            "_Cette section conserve volontairement les répétitions pour montrer les commandes les plus utilisées._",
            "",
            markdown_table(
                ("Nombre", "Commande"),
                (
                    (
                        count,
                        markdown_common_command_cell(
                            command,
                            entries,
                            launcher_dir,
                            markdown_base_dir,
                            project_roots,
                        ),
                    )
                    for command, count in most_common_entries(entries, top)
                ),
            ),
            "",
            "## Familles de commandes",
            "",
            markdown_table(
                ("Nombre", "Famille"),
                ((count, family) for family, count in family_counts.most_common(top)),
            ),
            "",
            "## Projets détectés",
            "",
            markdown_table(
                ("Nombre", "Projet ou dossier"),
                (
                    (count, project)
                    for project, count in project_counts.most_common(top)
                ),
            ),
            "",
            "## Aujourd'hui",
            "",
            markdown_table(
                ("Date", "Projet", "Commande"),
                (
                    (
                        format_history_time(entry.timestamp),
                        entry.project,
                        markdown_command_cell(
                            entry, launcher_dir, markdown_base_dir, project_roots
                        ),
                    )
                    for entry in reversed(unique_today_entries[-recent:])
                ),
            )
            if unique_today_entries
            else "_Aucune commande aujourd'hui._",
            "",
            "## Dernières commandes",
            "",
        ]
    )

    if recent_entries:
        lines.append(
            markdown_table(
                ("Date", "Projet", "Famille", "Commande"),
                (
                    (
                        format_history_time(entry.timestamp),
                        entry.project,
                        entry.family,
                        markdown_command_cell(
                            entry, launcher_dir, markdown_base_dir, project_roots
                        ),
                    )
                    for entry in reversed(recent_entries)
                ),
            )
        )
    else:
        lines.append("_Aucune commande récente._")

    lines.extend(["", "## Cadres par projet", ""])
    for project, _count in project_counts.most_common(top):
        project_entries = unique_latest_entries(
            [entry for entry in entries if entry.project == project]
        )
        lines.extend(
            [
                f"### {project}",
                "",
                markdown_table(
                    ("Date", "Famille", "Commande"),
                    (
                        (
                            format_history_time(entry.timestamp),
                            entry.family,
                            markdown_command_cell(
                                entry, launcher_dir, markdown_base_dir, project_roots
                            ),
                        )
                        for entry in reversed(project_entries[-min(top, 10) :])
                    ),
                ),
                "",
            ]
        )

    lines.extend(
        [
            "## Notes",
            "",
            "- Le dossier courant est inféré à partir des commandes `cd`; certains cadres peuvent donc être approximatifs.",
            "- Ghostty affiche le terminal, mais les données viennent ici de l'historique du shell.",
            "- Les lignes sans date n'ont pas été horodatées par `zsh`; leur date ne peut pas être retrouvée après coup.",
        ]
    )

    if launcher_dir is not None:
        lines.append(
            f"- Les liens ▶ pointent vers le lanceur unique `{launcher_dir / TERMINAL_COMMAND_RUNNER_NAME}`."
        )
        lines.append(
            f"- Les commandes sont stockées dans `{launcher_dir / TERMINAL_COMMAND_REGISTRY_NAME}`."
        )
        lines.append(
            "- Le lanceur demande l'identifiant affiché dans le lien, puis confirmation avant exécution."
        )

    return "\n".join(lines).rstrip() + "\n"


def write_terminal_dashboard(
    history_path: Path,
    output: Path,
    limit: int | None,
    top: int,
    recent: int,
    project_roots: Sequence[Path],
    ignore_file: Path,
    launcher_dir: Path | None,
) -> None:
    history_path = expand_user_path(history_path)
    ignored_commands = load_ignored_terminal_commands(ignore_file)
    entries = filter_ignored_entries(
        read_shell_history(history_path, limit, project_roots),
        ignored_commands,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    actual_launcher_dir = None
    if launcher_dir is not None:
        actual_launcher_dir = (
            launcher_dir if launcher_dir.is_absolute() else output.parent / launcher_dir
        ).resolve()
    output.write_text(
        shell_dashboard_markdown(
            entries,
            history_path,
            project_roots,
            top,
            recent,
            actual_launcher_dir,
            output.parent,
        ),
        encoding="utf-8",
    )
    print(f"Tableau de bord terminal écrit : {output}")


def terminal_history_matches(
    entries: Sequence[ShellCommandEntry],
    search: str | None,
    family: str | None,
    project: str | None,
) -> list[ShellCommandEntry]:
    matches = list(entries)
    if search:
        needle = search.lower()
        matches = [entry for entry in matches if needle in entry.command.lower()]
    if family:
        needle = family.lower()
        matches = [entry for entry in matches if needle in entry.family.lower()]
    if project:
        needle = project.lower()
        matches = [entry for entry in matches if needle in entry.project.lower()]
    return matches


def unique_latest_entries(
    entries: Sequence[ShellCommandEntry],
) -> list[ShellCommandEntry]:
    by_command: dict[str, ShellCommandEntry] = {}
    for entry in entries:
        by_command[entry.command] = entry
    return list(by_command.values())


def load_ignored_terminal_commands(ignore_file: Path) -> set[str]:
    if not ignore_file.exists():
        return set()

    try:
        payload = json.loads(ignore_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()

    if isinstance(payload, dict):
        commands = payload.get("commands", [])
    else:
        commands = payload

    if not isinstance(commands, list):
        return set()

    return {command for command in commands if isinstance(command, str)}


def save_ignored_terminal_commands(ignore_file: Path, commands: set[str]) -> None:
    ignore_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "commands": sorted(commands),
    }
    ignore_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def filter_ignored_entries(
    entries: Sequence[ShellCommandEntry],
    ignored_commands: set[str],
) -> list[ShellCommandEntry]:
    if not ignored_commands:
        return list(entries)
    return [entry for entry in entries if entry.command not in ignored_commands]


def truncate_console_text(text: str, width: int) -> str:
    if width <= 1 or len(text) <= width:
        return text
    return text[: max(1, width - 1)] + "…"


def print_terminal_history(
    history_path: Path,
    limit: int | None,
    recent: int,
    search: str | None,
    family: str | None,
    project: str | None,
    project_roots: Sequence[Path],
    show_projects: bool,
    show_top: bool,
    unique: bool,
    rerun: bool,
    run_number: int | None,
    yes: bool,
    loop: bool,
    ignore_file: Path,
) -> None:
    history_path = expand_user_path(history_path)
    while True:
        ignored_commands = load_ignored_terminal_commands(ignore_file)
        entries = filter_ignored_entries(
            read_shell_history(history_path, limit, project_roots),
            ignored_commands,
        )
        matches = terminal_history_matches(entries, search, family, project)
        display_matches = unique_latest_entries(matches) if unique else matches
        selected = display_matches[-recent:] if recent > 0 else display_matches
        dated_matches = sum(1 for entry in matches if entry.timestamp is not None)
        undated_matches = len(matches) - dated_matches

        print("Historique terminal")
        print("-------------------")
        print(f"Historique : {history_path}")
        print(f"Commandes analysées : {len(entries)}")
        print(f"Commandes retenues  : {len(matches)}")
        print(f"Commandes datées    : {dated_matches}")
        print(f"Commandes sans date : {undated_matches}")
        if unique:
            print(f"Commandes uniques   : {len(display_matches)}")
        if search:
            print(f"Recherche           : {search}")
        if family:
            print(f"Famille             : {family}")
        if project:
            print(f"Projet              : {project}")
        if loop:
            print("Mode                : boucle, Entrée pour quitter")
        if undated_matches:
            print(
                "Note                : les lignes sans date n'ont pas été horodatées par zsh."
            )
        print()

        if show_top:
            print("Commandes fréquentes")
            print("--------------------")
            for command, count in most_common_entries(
                matches, min(10, recent if recent > 0 else 10)
            ):
                print(f"{count:>4}  {command}")
            print()

        if show_projects:
            print("Projets détectés")
            print("----------------")
            for label, count in Counter(
                entry.project for entry in display_matches
            ).most_common(10):
                print(f"{count:>4}  {label}")
            print()

        print("Dernières commandes")
        print("-------------------")
        if not selected:
            print("Aucune commande trouvée.")
            return

        terminal_width = shutil.get_terminal_size((120, 20)).columns
        command_width = max(30, terminal_width - 45)

        display_entries = list(reversed(selected))
        for index, entry in enumerate(display_entries, start=1):
            date_text = format_history_time(entry.timestamp) or "date inconnue"
            prefix = f"{index:>3}. {date_text}  {entry.project}  "
            print(prefix + truncate_console_text(entry.command, command_width))

        if run_number is not None:
            rerun_terminal_history_command(
                display_entries,
                run_number=run_number,
                assume_yes=yes,
                ignore_file=ignore_file,
                ignored_commands=ignored_commands,
                project_roots=project_roots,
            )
            return

        if rerun or loop:
            action = rerun_terminal_history_command(
                display_entries,
                run_number=None,
                assume_yes=yes,
                ignore_file=ignore_file,
                ignored_commands=ignored_commands,
                project_roots=project_roots,
            )
            if loop and action in {"ran", "ignored"}:
                print()
                print("---")
                print()
                continue

        return


def rerun_terminal_history_command(
    entries: Sequence[ShellCommandEntry],
    run_number: int | None,
    assume_yes: bool,
    ignore_file: Path,
    ignored_commands: set[str],
    project_roots: Sequence[Path],
) -> str:
    if not entries:
        return "cancelled"

    if run_number is None:
        print()
        try:
            choice = input(
                "Numéro à relancer, 0N pour masquer (Entrée pour quitter) : "
            ).strip()
        except EOFError:
            print("Annulé.")
            return "cancelled"
        if not choice:
            print("Annulé.")
            return "cancelled"
        if not choice.isdigit():
            print("Choix invalide.")
            return "cancelled"
        should_ignore = len(choice) > 1 and choice.startswith("0")
        index = int(choice)
    else:
        should_ignore = False
        index = run_number

    if index < 1 or index > len(entries):
        print("Choix hors liste.")
        return "cancelled"

    entry = entries[index - 1]
    if should_ignore:
        ignored_commands.add(entry.command)
        save_ignored_terminal_commands(ignore_file, ignored_commands)
        print(f"Commande masquée : {entry.command}")
        print(f"Mémoire d'exclusion : {ignore_file}")
        return "ignored"

    print()
    print("Commande sélectionnée :")
    print(entry.command)
    if not assume_yes:
        try:
            confirmation = (
                input("Relancer cette commande ? taper oui pour confirmer : ")
                .strip()
                .lower()
            )
        except EOFError:
            print("Annulé.")
            return "cancelled"
        if confirmation != "oui":
            print("Annulé.")
            return "cancelled"

    run_cwd = effective_command_cwd(entry, project_roots)
    if run_cwd is not None:
        print(f"Dossier : {run_cwd}")
    print()
    completed = subprocess.run(entry.command, shell=True, cwd=run_cwd)
    if completed.returncode != 0:
        print(f"Commande terminée avec le code {completed.returncode}")
    return "ran"


def parse_extensions(values: Sequence[str] | None) -> set[str]:
    if not values:
        return set(DEFAULT_MEDIA_EXTENSIONS)
    return {v if v.startswith(".") else f".{v}" for v in values}


def env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return Path(value).expanduser()


def build_parser() -> argparse.ArgumentParser:
    default_vault = env_path(ENV_VAULT_PATH)
    default_export_output = env_path(ENV_EXPORT_OUTPUT_DIR)

    parser = argparse.ArgumentParser(
        description="Analyse et exporte les médias attachés aux notes Obsidian."
    )
    parser.add_argument(
        "vault",
        nargs="?",
        type=Path,
        default=default_vault,
        help=f"Chemin vers la racine du vault Obsidian. Défaut : ${ENV_VAULT_PATH}",
    )
    parser.add_argument(
        "--ext",
        nargs="*",
        help="Extensions médias à prendre en compte. Par défaut : liste intégrée.",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "count-notes", help="Compte les notes Markdown sans lire leur contenu"
    )

    sub.add_parser("summary", help="Affiche un résumé du vault")

    report = sub.add_parser("report", help="Génère un rapport JSON complet")
    report.add_argument(
        "--output", type=Path, default=Path("obsidian_media_report.json")
    )

    orphans = sub.add_parser("orphans", help="Liste les médias orphelins")
    orphans.add_argument("--limit", type=int, default=200)

    missing = sub.add_parser(
        "missing", help="Liste les références de médias manquantes"
    )
    missing.add_argument("--limit", type=int, default=200)

    diagnosis = sub.add_parser(
        "diagnose", help="Diagnostique les médias orphelins et références manquantes"
    )
    diagnosis.add_argument(
        "--limit", type=int, default=50, help="Nombre d'exemples à afficher"
    )
    diagnosis.add_argument("--output", type=Path, help="Écrit aussi un diagnostic JSON")

    markdown_reports = sub.add_parser(
        "markdown-reports", help="Génère des rapports Markdown lisibles"
    )
    markdown_reports.add_argument(
        "--output-dir",
        type=Path,
        default=Path("diagnostics"),
        help="Dossier de sortie des rapports Markdown",
    )
    markdown_reports.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Nombre d'éléments dans le rapport prioritaire",
    )

    exportable = sub.add_parser(
        "exportable-notes",
        help="Liste les notes exportables sans références média bloquantes",
    )
    exportable.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/07_notes_exportables.md"),
        help="Fichier Markdown de sortie",
    )
    exportable.add_argument(
        "--limit",
        type=int,
        help="Limite le nombre de lignes par section. Par défaut : aucune limite.",
    )

    blocked = sub.add_parser(
        "blocked-notes", help="Liste les notes non exportables à corriger ou jeter"
    )
    blocked.add_argument(
        "--output",
        type=Path,
        default=Path("diagnostics/08_notes_bloquees_a_corriger_ou_jeter.md"),
        help="Fichier Markdown de sortie",
    )

    export = sub.add_parser(
        "export-note", help="Exporte une note avec ses médias attachés"
    )
    export.add_argument("note", help="Chemin ou nom de la note à exporter")
    export.add_argument(
        "--output",
        type=Path,
        default=default_export_output,
        help=f"Dossier de sortie. Défaut : ${ENV_EXPORT_OUTPUT_DIR}",
    )
    export.add_argument("--dry-run", action="store_true", help="Simule sans copier")
    export.add_argument(
        "--rewrite-links",
        action="store_true",
        help="Convertit les liens médias de la copie exportée en Markdown universel",
    )
    export.add_argument(
        "--portable-media-names",
        action="store_true",
        help="Copie les médias avec des noms ASCII stables dans _media/",
    )
    export.add_argument(
        "--overwrite",
        action="store_true",
        help="Remplace les notes et médias déjà présents dans le dossier de sortie",
    )

    export_folder = sub.add_parser(
        "export-folder", help="Exporte les notes valides d'un dossier du vault"
    )
    export_folder.add_argument(
        "folder", help="Dossier du vault à exporter, par exemple Cartes_postales_photo"
    )
    export_folder.add_argument(
        "--output",
        type=Path,
        default=default_export_output,
        help=f"Dossier de sortie. Défaut : ${ENV_EXPORT_OUTPUT_DIR}",
    )
    export_folder.add_argument(
        "--dry-run", action="store_true", help="Simule sans copier"
    )
    export_folder.add_argument(
        "--rewrite-links",
        action="store_true",
        help="Convertit les liens médias des copies exportées en Markdown universel",
    )
    export_folder.add_argument(
        "--portable-media-names",
        action="store_true",
        help="Copie les médias avec des noms ASCII stables dans _media/",
    )
    export_folder.add_argument(
        "--include-blocked",
        action="store_true",
        help="Exporte aussi les notes avec références manquantes ou ambiguës",
    )
    export_folder.add_argument(
        "--overwrite",
        action="store_true",
        help="Remplace les notes et médias déjà présents dans le dossier de sortie",
    )

    terminal_dashboard = sub.add_parser(
        "terminal-dashboard",
        help="Génère un tableau de bord Markdown depuis l'historique du shell",
    )
    terminal_dashboard.add_argument(
        "--history",
        type=Path,
        default=Path("~/.zsh_history"),
        help="Fichier d'historique à lire. Défaut : ~/.zsh_history",
    )
    terminal_dashboard.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_TERMINAL_DASHBOARD_OUTPUT,
        help="Fichier Markdown de sortie",
    )
    terminal_dashboard.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Nombre maximum de lignes récentes à analyser",
    )
    terminal_dashboard.add_argument(
        "--top",
        type=int,
        default=20,
        help="Nombre d'éléments à afficher dans les classements",
    )
    terminal_dashboard.add_argument(
        "--recent",
        type=int,
        default=40,
        help="Nombre de commandes récentes à afficher",
    )
    terminal_dashboard.add_argument(
        "--project-root",
        type=Path,
        action="append",
        default=[],
        help="Racine de projet à suivre. Peut être répété.",
    )
    terminal_dashboard.add_argument(
        "--ignore-file",
        type=Path,
        default=DEFAULT_TERMINAL_IGNORE_FILE,
        help="Fichier des commandes masquées",
    )
    terminal_dashboard.add_argument(
        "--command-link-dir",
        type=Path,
        default=DEFAULT_TERMINAL_COMMAND_LINK_DIR,
        help="Dossier des lanceurs .command liés depuis le Markdown",
    )
    terminal_dashboard.add_argument(
        "--no-command-links",
        action="store_true",
        help="N'ajoute pas de liens de relance dans le Markdown",
    )

    terminal_history = sub.add_parser(
        "terminal-history",
        help="Affiche l'historique du shell directement dans le terminal",
    )
    terminal_history.add_argument(
        "--history",
        type=Path,
        default=Path("~/.zsh_history"),
        help="Fichier d'historique à lire. Défaut : ~/.zsh_history",
    )
    terminal_history.add_argument(
        "--limit",
        type=int,
        default=5000,
        help="Nombre maximum de lignes récentes à analyser",
    )
    terminal_history.add_argument(
        "--recent",
        type=int,
        default=40,
        help="Nombre de commandes à afficher",
    )
    terminal_history.add_argument(
        "--search",
        help="Filtre sur un morceau de commande, par exemple obsidian ou uv run",
    )
    terminal_history.add_argument(
        "--family",
        help="Filtre sur une famille de commande, par exemple git ou uv run",
    )
    terminal_history.add_argument(
        "--project",
        help="Filtre sur un projet ou dossier détecté, par exemple Obsidian_tools",
    )
    terminal_history.add_argument(
        "--project-root",
        type=Path,
        action="append",
        default=[],
        help="Racine de projet à suivre. Peut être répété.",
    )
    terminal_history.add_argument(
        "--projects",
        action="store_true",
        help="Affiche aussi le classement des projets détectés",
    )
    terminal_history.add_argument(
        "--top",
        action="store_true",
        help="Affiche aussi les commandes fréquentes parmi les résultats",
    )
    terminal_history.add_argument(
        "--unique",
        action="store_true",
        help="N'affiche qu'une fois chaque commande, en gardant sa dernière apparition",
    )
    terminal_history.add_argument(
        "--rerun",
        action="store_true",
        help="Permet de relancer une commande affichée en choisissant son numéro",
    )
    terminal_history.add_argument(
        "--run-number",
        type=int,
        help="Relance directement le numéro affiché, par exemple --run-number 7",
    )
    terminal_history.add_argument(
        "--yes",
        action="store_true",
        help="Avec --run-number ou --rerun, confirme automatiquement la relance",
    )
    terminal_history.add_argument(
        "--loop",
        action="store_true",
        help="Après chaque relance, réaffiche la liste et redemande un numéro",
    )
    terminal_history.add_argument(
        "--ignore-file",
        type=Path,
        default=DEFAULT_TERMINAL_IGNORE_FILE,
        help="Fichier des commandes masquées",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    default_vault = env_path(ENV_VAULT_PATH)

    if raw_argv and raw_argv[0] in NO_VAULT_COMMAND_NAMES:
        raw_argv.insert(0, ".")
    elif raw_argv and raw_argv[0] in COMMAND_NAMES:
        if default_vault is not None:
            raw_argv.insert(0, default_vault.as_posix())
        elif "-h" not in raw_argv and "--help" not in raw_argv:
            parser.error(
                f"vault manquant : fournissez un chemin ou renseignez {ENV_VAULT_PATH} dans .env"
            )

    args = parser.parse_args(raw_argv)

    if args.command in NO_VAULT_COMMAND_NAMES:
        project_roots = args.project_root or [PROJECT_ROOT]
        if args.command == "terminal-dashboard":
            write_terminal_dashboard(
                args.history,
                args.output,
                args.limit,
                args.top,
                args.recent,
                project_roots,
                args.ignore_file,
                None if args.no_command_links else args.command_link_dir,
            )
        elif args.command == "terminal-history":
            print_terminal_history(
                args.history,
                args.limit,
                args.recent,
                args.search,
                args.family,
                args.project,
                project_roots,
                args.projects,
                args.top,
                args.unique,
                args.rerun,
                args.run_number,
                args.yes,
                args.loop,
                args.ignore_file,
            )
        return 0

    if args.vault is None:
        parser.error(
            f"vault manquant : fournissez un chemin ou renseignez {ENV_VAULT_PATH} dans .env"
        )

    vault = args.vault.expanduser().resolve()
    if not vault.exists() or not vault.is_dir():
        print(f"Vault invalide : {vault}", file=sys.stderr)
        return 2

    if args.command == "count-notes":
        print_note_count(vault)
        return 0

    media_extensions = parse_extensions(args.ext)
    index = build_index(vault, media_extensions)

    if args.command == "summary":
        print_summary(index)
        return 0

    if args.command == "report":
        write_report(index, args.output)
        print(f"Rapport écrit : {args.output}")
        return 0

    if args.command == "orphans":
        list_orphans(index, args.limit)
        return 0

    if args.command == "missing":
        list_missing(index, args.limit)
        return 0

    if args.command == "diagnose":
        diagnose(index, args.output, args.limit)
        return 0

    if args.command == "markdown-reports":
        write_markdown_reports(index, args.output_dir, args.limit)
        return 0

    if args.command == "exportable-notes":
        write_exportable_notes_report(index, args.output, args.limit)
        return 0

    if args.command == "blocked-notes":
        write_blocked_notes_report(index, args.output)
        return 0

    if args.command == "export-note":
        if args.output is None:
            parser.error(
                f"--output manquant : fournissez un dossier ou renseignez {ENV_EXPORT_OUTPUT_DIR} dans .env"
            )
        export_note_with_media(
            index,
            args.note,
            args.output,
            dry_run=args.dry_run,
            rewrite_links=args.rewrite_links,
            portable_media_names=args.portable_media_names,
            overwrite=args.overwrite,
        )
        return 0

    if args.command == "export-folder":
        if args.output is None:
            parser.error(
                f"--output manquant : fournissez un dossier ou renseignez {ENV_EXPORT_OUTPUT_DIR} dans .env"
            )
        export_folder_notes(
            index,
            args.folder,
            args.output,
            dry_run=args.dry_run,
            rewrite_links=args.rewrite_links,
            include_blocked=args.include_blocked,
            portable_media_names=args.portable_media_names,
            overwrite=args.overwrite,
        )
        return 0

    parser.error(f"Commande inconnue : {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
