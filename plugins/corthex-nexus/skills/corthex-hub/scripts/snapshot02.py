"""NEXUS 0.2 Git-object sources, settings and repository stage records.

The caller supplies the hub's existing redaction/check helpers. No checkout,
network, Git hook, filter or user executable is used to read source objects.
"""
import json
import os
import re
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from urllib.parse import urlsplit, urlunsplit

PICTURE_STAGES = ("01-domain", "05-erd", "07-sitemap")
DEFAULT_ASK_BEFORE = ["external messages", "deploys", "payments", "deletions", "publishing"]
PART = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")


def canonical_origin(raw, h):
    """Canonical HTTPS identity from a public HTTPS or SSH origin address."""
    if not isinstance(raw, str) or not raw or any(ord(c) < 33 for c in raw):
        return ""
    scp = re.fullmatch(r"(?:[^/@:]+@)?([A-Za-z0-9.-]+):([^?#]+)", raw)
    if scp and "://" not in raw:
        raw = "https://" + scp.group(1) + "/" + scp.group(2)
    try:
        p = urlsplit(raw)
        if p.scheme not in ("http", "https", "ssh") or not p.hostname or p.query or p.fragment:
            return ""
        port = p.port
        host = p.hostname.lower()
        if ":" in host:
            host = "[" + host + "]"
        # SSH's transport port is not the HTTPS repository's port.
        if port and p.scheme != "ssh" and port not in (80, 443):
            host += ":" + str(port)
        path = p.path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        if not path or path == "/" or any(x in (".", "..") for x in path.split("/")):
            return ""
        address = urlunsplit(("https", host, path, "", ""))
        return address if h.companion("commands").link(address, Path.home(), os.environ, h) else ""
    except ValueError:
        return ""


class ObjectTree:
    def __init__(self, root, commit, h):
        self.root, self.commit, self.h = root, commit, h
        self.files = {}
        self.sizes = {}
        raw = h.run_git(root, ["ls-tree", "-r", "-l", "-z", "--full-tree", commit])
        if raw is None:
            raise ValueError("the fetched default branch tree cannot be read")
        for entry in raw.split(b"\0"):
            head, sep, name = entry.partition(b"\t")
            fields = head.split()
            if not sep or len(fields) != 4 or fields[0] not in (b"100644", b"100755") or fields[1] != b"blob" or not fields[3].isdigit():
                continue
            try:
                rel = name.decode("utf-8")
                oid = fields[2].decode("ascii")
            except UnicodeError:
                continue
            path = PurePosixPath(rel)
            if (path.is_absolute() or ".." in path.parts or "\\" in rel or
                    any(ord(c) < 32 for c in rel) or not COMMIT.fullmatch(oid)):
                continue
            self.files[rel] = oid
            self.sizes[rel] = int(fields[3])

    def read(self, rel):
        oid = self.files.get(rel)
        if not oid or self.h.secret_path(self.root / rel, self.root):
            return None
        if self.sizes[rel] > self.h.MAX_FILE_BYTES:
            return None
        data = self.h.run_git(self.root, ["cat-file", "blob", oid])
        return data.decode("utf-8-sig", "replace") if data is not None else None

    def source_files(self, source, extensions):
        rel = source.rstrip("/")
        if rel == ".":
            rel = ""
        selected = [name for name in sorted(self.files)
                    if (not rel or name == rel or name.startswith(rel + "/")) and
                    PurePosixPath(name).suffix.lower() in extensions and
                    not self.h.secret_path(self.root / name, self.root)]
        paths = set(Path(name) for name in selected)
        # A translation next to its original is not another picture source.
        return [name for name in selected if not self.h.original_of(Path(name), paths)]


def default_tree(project, snapshot, h):
    origin = canonical_origin(h.git(project.root, "config", "--get", "remote.origin.url"), h)
    ref = h.git(project.root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if not origin or not ref or not ref.startswith("refs/remotes/origin/") or ref.endswith("/HEAD"):
        return None, None
    commit = h.git(project.root, "rev-parse", "--verify", ref + "^{commit}")
    if not COMMIT.fullmatch(commit or ""):
        return None, None
    time = h.git(project.root, "show", "-s", "--format=%cI", commit)
    if not zoned_time(time):
        return None, None
    info = snapshot["repos"].setdefault(".", {})
    info["url"] = origin
    info["default"] = {"branch": ref[len("refs/remotes/origin/"):], "commit": commit, "time": time}
    try:
        return ObjectTree(project.root, commit, h), info["default"]
    except ValueError:
        info.pop("default", None)
        return None, None


def zoned_time(value):
    try:
        return (isinstance(value, str) and len(value) <= 40 and
                re.fullmatch(r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})", value) is not None and
                datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00")).utcoffset() is not None)
    except ValueError:
        return False


def calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def parts_of(settings, checks, h):
    parts = settings.get("parts")
    if parts is None:
        return []
    if (not isinstance(parts, list) or not 1 <= len(parts) <= 50 or
            any(not isinstance(p, str) or len(p) > 100 or not PART.fullmatch(p) for p in parts) or
            len(set(parts)) != len(parts)):
        checks.append(h.check("parts-invalid", "warn", "parts must name 1 to 50 different lowercase project parts"))
        return []
    return parts[:]


def part_of(rel, source, parts):
    base = source.rstrip("/")
    name = rel if base in ("", ".") else rel[len(base) + 1:] if rel.startswith(base + "/") else PurePosixPath(rel).name
    matches = [p for p in parts if name == p or any(name.startswith(p + sep) for sep in ("/", ".", "-"))]
    return max(matches, key=len) if matches else ""


def ask_before(settings, home, checks, h):
    path = (Path(home) if home is not None else Path.home()) / ".corthex" / "profile.json"
    profile = h.load_json(path)
    if path.exists() and profile is None:
        checks.append(h.check("ask-before-invalid", "warn", "the profile cannot be read; the default ask_before list applies"))
    profile = profile or {}

    def read(owner, name, fallback):
        if "ask_before" not in owner:
            return fallback
        value = owner["ask_before"]
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            checks.append(h.check("ask-before-invalid", "warn", name + " ask_before is not a list of strings; the next list applies"))
            return fallback
        entries = list(dict.fromkeys(h.one_line(x, 120) for x in value if x.strip()))
        if len(entries) > 30:
            checks.append(h.check("ask-before-long", "info", name + " ask_before has more than 30 entries; the first 30 are kept"))
        return entries[:30], name

    inherited = read(profile, "profile", (DEFAULT_ASK_BEFORE[:], "default"))
    entries, source = read(settings, "project", inherited)
    listed = [x.casefold() for x in entries]

    def kept(entry):
        # A project entry keeps an inherited one when it repeats it, alone or with a qualifier after it,
        # as "deletions (repositories, data)" keeps "deletions".
        word = entry.casefold()
        return any(x == word or (x.startswith(word) and x[len(word):len(word) + 1] in (" ", "(")) for x in listed)

    return {"entries": entries, "source": source,
            "left_out": [x for x in inherited[0] if not kept(x)] if source == "project" else []}


def record_check(checks, h, rel, reason, stage=None, part=""):
    row = h.check("records-invalid", "warn", rel + ": " + reason, stage=stage, args={"source": rel})
    if part:
        row["part"] = part
    checks.append(row)


def read_record(text, project, part, rel, checks, h):
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None
    if (not isinstance(data, dict) or type(data.get("format")) is not int or data.get("format") != 1 or data.get("project") != project or
            data.get("part", "") != part or not isinstance(data.get("stages"), dict)):
        record_check(checks, h, rel, "not a format-1 record for this project and part", part=part)
        return {}
    result = {}
    for stage, raw in data["stages"].items():
        if stage not in h.STAGE_KEYS:
            record_check(checks, h, rel, "unknown stage key", part=part)
            continue
        if (not isinstance(raw, dict) or raw.get("state") not in h.STATES or
                not isinstance(raw.get("checkpoints"), list) or not isinstance(raw.get("next"), str) or not zoned_time(raw.get("updated"))):
            record_check(checks, h, rel, "invalid recorded state, checkpoints, next action or timestamp", stage, part)
            continue
        checkpoints = []
        for cp in raw.get("checkpoints", []) if isinstance(raw.get("checkpoints"), list) else []:
            if not isinstance(cp, dict):
                continue
            approved, role = h.one_line(cp.get("approved"), 2000), h.one_line(cp.get("by"), 120)
            recorded_date = cp.get("date")
            if not approved or not role or not calendar_date(recorded_date):
                record_check(checks, h, rel, "checkpoint needs approval, role and date", stage, part)
                continue
            row = {"approved": approved, "by": role, "date": recorded_date}
            raw_link = cp.get("where")
            link = raw_link if h.companion("commands").link(raw_link, Path.home(), os.environ, h) else None
            if link:
                row["where"] = link
            if re.fullmatch(r"nk_[0-9a-hjkmnp-tv-z]{12}", cp.get("nexus", "") if isinstance(cp.get("nexus"), str) else ""):
                row["nexus"] = cp["nexus"]
            checkpoints.append(row)
        state = raw["state"]
        if state == "done" and not checkpoints:
            state = "in_progress"
            record_check(checks, h, rel, "done needs a checkpoint and its date", stage, part)
        row = {"state": state, "checkpoints": checkpoints, "next": h.one_line(raw.get("next"), 300)}
        if zoned_time(raw.get("updated")):
            row["updated"] = raw["updated"]
        for review in raw.get("checks", []) if isinstance(raw.get("checks"), list) else []:
            if not isinstance(review, dict) or review.get("level") not in h.LEVELS:
                continue
            message = h.one_line(review.get("message"), 300)
            if not message:
                continue
            refs = [x for x, _, _ in h.picture_ids.find(message)]
            for value in review.get("refs", []) if isinstance(review.get("refs"), list) else []:
                if isinstance(value, str) and h.picture_ids.whole(value):
                    refs.append(value)
            refs = list(dict.fromkeys(refs))
            finding = h.check("review", review["level"], message, refs, stage, by="review")
            if part:
                finding["part"] = part
            if isinstance(review.get("at"), str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", review["at"]):
                finding["at"] = review["at"]
            checks.append(finding)
        result[stage] = row
    return result


def records(snapshot, project, parts, tree, default, checks, h):
    files = [(p, ".corthex/stages/" + p + ".json") for p in parts] if parts else [("", ".corthex/stages.json")]
    present = [(part, rel) for part, rel in files if tree and rel in tree.files]
    if parts and tree:
        for rel in tree.files:
            if re.fullmatch(r"\.corthex/stages/[^/]+\.json", rel) and PurePosixPath(rel).stem not in parts:
                record_check(checks, h, rel, "part is not declared in project settings")
    if not present:
        snapshot["records"] = {"from": "status-file"}
        checks.append(h.check("records-in-status-file", "info", "stage records come from this device's status file; move them to the repository"))
        for key, stage in snapshot["stages"].items():
            if stage.get("state") == "done" and not (stage.get("checkpoint") and calendar_date(stage.get("checkpoint_date"))):
                stage["state"] = "in_progress"
                record_check(checks, h, "device status file", "done needs a checkpoint and its date", key)
        return
    snapshot["records"] = {"from": "repository", "commit": default["commit"], "time": default["time"]}
    snapshot["checks"][:] = [c for c in snapshot["checks"] if c.get("by") != "review"]
    for stage in snapshot["stages"].values():
        for name in ("checkpoint", "checkpoint_date", "checkpoints", "next", "updated", "parts"):
            stage.pop(name, None)
        stage["state"] = "skipped" if stage.get("skip") else "unknown"
        if parts:
            stage["parts"] = {}
    for part, rel in present:
        for key, record in read_record(tree.read(rel), project.name, part, rel, checks, h).items():
            if parts:
                snapshot["stages"][key]["parts"][part] = record
            else:
                snapshot["stages"][key].update(record)
                if record["checkpoints"]:
                    last = record["checkpoints"][-1]
                    snapshot["stages"][key].update(checkpoint=last["approved"], checkpoint_date=last["date"])
def augment(snapshot, project, home, api, parse_picture):
    h = SimpleNamespace(**api)
    h.picture_ids = h.IdFormat(project.settings.get("ids"))
    checks = []
    parts = parts_of(project.settings, checks, h)
    if parts:
        snapshot["project"]["parts"] = parts
    snapshot["ask_before"] = ask_before(project.settings, home, checks, h)
    if "on_nexus" in project.settings and not isinstance(project.settings["on_nexus"], bool):
        # 0.4.0: on_nexus says only whether the project is expected on a NEXUS server (SPEC-190).
        checks.append(h.check("on-nexus-invalid", "warn", "on_nexus is not true or false, so it counts as not set"))
    tree, default = default_tree(project, snapshot, h)
    snapshot["pictures"], snapshot["left_out"] = [], []
    records(snapshot, project, parts, tree, default, checks, h)
    if tree is None:
        checks.append(h.check("pictures-not-sent", "warn", "no readable origin default branch; run git remote set-head origin --auto after fetching"))
    else:
        for key, _, default_source, _, _ in h.STAGES:
            if key not in PICTURE_STAGES:
                continue
            stages = project.settings.get("stages")
            given = stages.get(key) if isinstance(stages, dict) else None
            source = given.get("source") if isinstance(given, dict) else default_source
            if isinstance(given, dict) and given.get("skip") is True:
                continue
            if not isinstance(source, str) or not source:
                continue
            alias, rel = h.split_source(source)
            if alias != ".":
                for part in parts or [""]:
                    snapshot["left_out"].append({"part": part, "stage": key, "why": "other-repository"})
                    warning = h.check("picture-left-out", "warn", "the picture source is in another repository", stage=key, args={"part": part, "why": "other-repository"})
                    if part:
                        warning["part"] = part
                    checks.append(warning)
                continue
            if h.is_absolute(rel) or "\\" in rel or ".." in PurePosixPath(rel).parts:
                continue
            groups = {}
            names = tree.source_files(rel, {"01-domain": {".md", ".markdown"}, "05-erd": {".sql"}, "07-sitemap": {".yaml", ".yml"}}[key])
            if len(names) > h.MAX_FILES:
                checks.append(h.check("picture-partial", "warn", names[h.MAX_FILES] + ":1: first of " +
                    str(len(names) - h.MAX_FILES) + " supported sources omitted after " + str(h.MAX_FILES) + " files",
                    stage=key, args={"limit": h.MAX_FILES, "omitted": len(names) - h.MAX_FILES}))
            for name in names[:h.MAX_FILES]:
                text = tree.read(name)
                if text is None:
                    checks.append(h.check("picture-partial", "warn", name + ": source object is unreadable or exceeds 1 MB", stage=key))
                    continue
                part = part_of(name, rel, parts)
                if parts and not part:
                    checks.append(h.check("part-unknown", "info", name + ": document belongs to no declared part", stage=key))
                groups.setdefault(part, []).append((name, text))
            for part, documents in groups.items():
                picture = parse_picture(key, documents, checks, h, part)
                if picture is not None:
                    snapshot["pictures"].append({"part": part, "stage": key, "commit": default["commit"], "time": default["time"], "source": picture})
    snapshot["checks"].extend(checks)
    snapshot = h.companion("commands").scrub(snapshot, home or Path.home(), os.environ, h)
    while snapshot["pictures"] and len(h.dump(snapshot, compact=True).encode("utf-8")) > h.MAX_SNAPSHOT_BYTES:
        biggest = max(snapshot["pictures"], key=lambda p: len(h.dump(p, compact=True).encode("utf-8")))
        snapshot["pictures"].remove(biggest)
        omission = {"part": biggest["part"], "stage": biggest["stage"], "why": "size"}
        snapshot["left_out"].append(omission)
        snapshot["checks"].append(h.check("picture-left-out", "warn", "a whole picture is left out to keep the snapshot under 1 MB", stage=biggest["stage"], args=omission))
    snapshot["summary"] = h.summary(snapshot["items"], snapshot["checks"], snapshot["stages"])
    return snapshot
