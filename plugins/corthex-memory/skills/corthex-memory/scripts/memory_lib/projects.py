"""Read-only project discovery by directory identity, never repository settings.

Callers first pass the store/configuration gate, then handle ProjectError's safe
code through diagnostics. locate() also serves the later worker-start decision
for a registered but disabled project; find() requires current consent/enabling.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .store import json_document

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,59}\Z")
KINDS = {"prompt", "answer", "boundary"}


class ProjectError(RuntimeError):
    def __init__(self, code, clash=()):
        self.code, self.clash = code, tuple(sorted(clash))
        super().__init__(code)


def directory(raw):
    if not isinstance(raw, (str, Path)) or not str(raw).strip():
        return None
    try:
        path = Path(raw).expanduser().resolve(strict=True)
        return path if path.is_dir() else None
    except (OSError, RuntimeError, ValueError):
        return None


def identity(path):
    try:
        info = path.stat()
        return info.st_dev, info.st_ino
    except OSError:
        return None


def ancestors(folder):
    return [(path, identity(path)) for path in (folder,) + tuple(folder.parents)]


@dataclass(frozen=True)
class Project:
    name: str
    folder: object
    cwd: Path
    matched: Path
    alias: object

    def left_out(self, configuration, kind):
        if kind not in KINDS:
            raise ValueError("invalid entry kind")
        choices = configuration.values["projects"].get(self.name, {}).get("left_out", {})
        if kind in choices.get("kinds", []):
            return True
        if self.folder is None:
            return False
        parents = {key for _, key in ancestors(self.cwd) if key is not None}
        for relative in choices.get("folders", []):
            # Configuration validation already rejects absolute/traversing
            # names. Resolve existing exclusions so links and volume case work
            # exactly like discovery; a missing exclusion cannot contain cwd.
            target = directory(self.folder.joinpath(*relative.split("/")))
            if target is not None and identity(target) in parents:
                return True
        return False


def entries(registry):
    try:
        raw = registry.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        data = json_document(raw)
        if not isinstance(data, dict) or not isinstance(data.get("projects"), list):
            raise ValueError("invalid project list")
    except (OSError, ValueError, UnicodeError):
        raise ProjectError("no-project-list") from None
    return [entry for entry in data["projects"] if isinstance(entry, dict)
            and isinstance(entry.get("name"), str) and NAME.fullmatch(entry["name"])]


def locate(cwd=None, registry=None):
    """Deepest registered directory wins; equal winners must name one project.

    Walk cwd's real ancestors rather than comparing path spelling (including
    WindowsPath's case-folding equality). Each root is compared by stat identity.
    The registry's primary path and repos both participate; duplicate aliases of
    one project are harmless. No memory file, project settings or Git is read.
    """
    if cwd is None:
        try:
            cwd = Path.cwd()
        except OSError:
            return None
    folder = directory(cwd)
    if folder is None:
        return None
    registry = Path(registry) if registry is not None else Path.home() / ".corthex" / "projects.json"
    roots = {}
    for entry in entries(registry):
        primary = directory(entry.get("path"))
        places = [(primary, None)]
        repos = entry.get("repos", {})
        if isinstance(repos, dict):
            places.extend((directory(raw), alias) for alias, raw in sorted(repos.items())
                          if isinstance(alias, str))
        for root, alias in places:
            key = identity(root) if root is not None else None
            if key is not None:
                roots.setdefault(key, {}).setdefault(entry["name"], (primary, alias))
    chain = ancestors(folder)
    if chain[0][1] is None:
        return None
    for path, key in chain:
        matching = roots.get(key, {})
        if len(matching) > 1:
            raise ProjectError("project-clash", matching)
        if matching:
            name, (primary, alias) = next(iter(matching.items()))
            return Project(name, primary, folder, path, alias)
    return None


def find(configuration, cwd=None, registry=None):
    if not configuration.consented():
        return None
    project = locate(cwd, registry)
    return project if project is not None and configuration.enabled(project.name) else None
