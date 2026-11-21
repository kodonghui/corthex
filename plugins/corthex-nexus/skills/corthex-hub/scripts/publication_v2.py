"""Explicit v2 publication from a registered repository's immutable Git tree."""

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import PurePosixPath

PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,79}")
COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
MEDIA = {".md": "text/markdown", ".json": "application/json", ".yaml": "application/yaml",
         ".yml": "application/yaml", ".txt": "text/plain", ".js": "text/plain", ".css": "text/plain",
         ".html": "text/html", ".sql": "application/sql"}
SOURCE_INDEX = ".corthex/nexus-v2-sources.json"
BODY_MAX = 20 * 1024 * 1024
FILE_MAX = 2 * 1024 * 1024
PUBLISHER_ENV = "CORTHEX_NEXUS_PUBLISHER_TOKEN"


def canonical(value):
    # The envelope has ASCII field names and only strings, arrays, objects
    # and null values. Keep UTF-8 source characters and the exact array order.
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def preview_digest(project_id, body):
    snapshot = {name: value for name, value in body.items() if name != "consent_id"}
    return digest(canonical({"format": "nexus.preview/1", "project_id": project_id, "snapshot": snapshot}))


def control(char):
    return unicodedata.category(char).startswith("C")


def read_blob(tree, path, h, max_bytes=FILE_MAX):
    if (not isinstance(path, str) or not path or len(path) > 1024 or
            any(part.lower() in ("", ".", "..", ".git") for part in path.split("/")) or
            any(control(c) for c in path) or "\\" in path or
            h.secret_path(tree.root / path, tree.root)):
        raise ValueError("a v2 source is outside the allowed repository paths")
    oid = tree.files.get(path)
    if oid is None or tree.sizes[path] > max_bytes:
        raise ValueError("a v2 source is missing or too large at the chosen commit")
    raw = h.run_git(tree.root, ["cat-file", "blob", oid])
    if raw is None:
        raise ValueError("a committed source cannot be read")
    try:
        return raw, raw.decode("utf8")
    except UnicodeError as error:
        raise ValueError("a v2 source must be exact UTF-8 text") from error


def envelope(project, project_id, base, consent, pinned_commit, h):
    if not PROJECT_ID.fullmatch(project_id or "") or (base is not None and not COMMIT.fullmatch(base)):
        raise ValueError("use the NEXUS project ID and an exact held commit")
    if consent is not None and (base is not None or not PROJECT_ID.fullmatch(consent)):
        raise ValueError("first-publication consent belongs to a new project")
    snapshots = h.companion("snapshot02")
    tree, head = snapshots.default_tree(project, {"repos": {}}, h)
    if not tree:
        raise ValueError("fetch the registered origin default branch before preparing a publication")
    commit = head["commit"]
    if pinned_commit is not None:
        if not COMMIT.fullmatch(pinned_commit) or h.run_git(project.root, ["merge-base", "--is-ancestor", pinned_commit, commit]) is None:
            raise ValueError("the pinned commit is not on the locally held default branch")
        commit = pinned_commit
        tree = snapshots.ObjectTree(project.root, commit, h)
    if base and h.run_git(project.root, ["merge-base", "--is-ancestor", base, commit]) is None:
        raise ValueError("the candidate is not a descendant of the held commit")
    _, text = read_blob(tree, SOURCE_INDEX, h, 256 * 1024)
    try:
        index = json.loads(text)
    except ValueError as error:
        raise ValueError("the committed v2 source index is invalid") from error
    if not isinstance(index, dict) or index.get("format") != "nexus.sources/1" or not isinstance(index.get("artifacts"), list):
        raise ValueError("the committed v2 source index is invalid")
    slots, artifact_files, parts = set(), 0, set()
    artifacts = []
    for row in index["artifacts"]:
        if not isinstance(row, dict) or set(row) != {"part", "stage", "files"}:
            raise ValueError("a v2 source index row is invalid")
        part, stage, paths = row["part"], row["stage"], row["files"]
        if (not isinstance(part, str) or not 0 < len(part) <= 80 or not part.strip() or part in (".", "..") or
                any(ch in part for ch in "/\\?#%") or any(control(ch) for ch in part) or
                stage not in h.STAGE_KEYS or not isinstance(paths, list) or (part, stage) in slots):
            raise ValueError("a v2 source index row is invalid")
        slots.add((part, stage))
        parts.add(part)
        if len(parts) > 20 or len(slots) > 260:
            raise ValueError("the source index exceeds the publication limits")
        files = []
        if any(not isinstance(path, str) for path in paths) or len(set(paths)) != len(paths):
            raise ValueError("a v2 source path is invalid or repeated")
        for path in paths:
            artifact_files += 1
            if artifact_files > 1000:
                raise ValueError("the source index exceeds the publication limits")
            media = MEDIA.get(PurePosixPath(path).suffix.lower())
            if not media:
                raise ValueError("a v2 source file format is unsupported")
            raw, value = read_blob(tree, path, h)
            files.append({"path": path, "media_type": media, "content_utf8": value, "sha256": digest(raw)})
        artifacts.append({"part": part, "stage": stage, "source_files": files})
    body = {"format": "nexus.publish/1", "commit": commit, "base_commit": base, "consent_id": consent, "artifacts": artifacts}
    if len(canonical(body)) > BODY_MAX:
        raise ValueError("the publication exceeds 20 MiB")
    return body


def send(base, project_id, body, env, h, client_factory=None, pause=time.sleep):
    token = env.get(PUBLISHER_ENV) or ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise ValueError("set the project-scoped publisher credential in " + PUBLISHER_ENV)
    if body["base_commit"] is None and body["consent_id"] is None:
        raise ValueError("record the owner's first-publication consent for this preview")
    path = "/api/v2/projects/" + project_id + "/publications"
    key = digest(canonical({"project_id": project_id, "body": body}))
    transport = h.companion("transport")
    client = (client_factory or transport.Client)(base, env, version=h.VERSION, timeout=16, publisher=token)
    for attempt in range(3):
        result = client.call("POST", path, body, write=key)
        if result["outcome"] == "done":
            receipt = result.get("answer") or {}
            receipt_id = receipt.get("id")
            revision = receipt.get("revision")
            snapshot_digest = receipt.get("snapshot_digest")
            if (receipt.get("sent") is not True or receipt.get("held_commit") != body["commit"] or
                    not isinstance(receipt_id, str) or not PROJECT_ID.fullmatch(receipt_id) or
                    type(revision) is not int or revision < 1 or
                    not isinstance(snapshot_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", snapshot_digest)):
                raise ValueError("the server receipt does not match the selected commit")
            return {name: receipt[name] for name in ("id", "sent", "held_commit", "revision", "snapshot_digest")}
        if not result.get("retry") or attempt == 2:
            break
        pause(2 ** attempt)
    code = (result.get("problem") or {}).get("code", "")
    if code not in {"unmerged_commit", "older_publication", "consent_required", "idempotency_conflict",
                    "source_verification_unavailable", "upstream_timeout", "rate_limited", "sign_in_required",
                    "operation_forbidden", "not_found", "invalid_input", "payload_too_large"}:
        code = "unable_to_confirm_publication"
    raise ValueError(code)


def configure(commands):
    for name in ("preview-v2", "publish-v2"):
        command = commands.add_parser(name, help="prepare a source envelope" if name == "preview-v2" else "send a verified source envelope")
        command.add_argument("project")
        command.add_argument("--project-id", required=True, help="the ID shown by the owner application")
        command.add_argument("--base-commit", help="the commit currently held by NEXUS")
        command.add_argument("--commit", help="pin a commit on the registered origin default branch")
        command.add_argument("--json", action="store_true", help="emit a JSON receipt")
        if name == "publish-v2":
            command.add_argument("--consent", help="the owner-recorded consent ID for this first publication")


def main(args, home, h):
    env = os.environ
    routing = h.companion("commands").where(args, home, env, h)
    if args.project not in routing.allowed:
        raise ValueError("the project is outside the configured publication allowlist")
    candidates = h.select_projects(home, [args.project], None)
    if len(candidates) != 1 or candidates[0][0] != args.project or candidates[0][1] is None:
        raise ValueError("open the registered project checkout before preparing a publication")
    body = envelope(candidates[0][1], args.project_id, args.base_commit, getattr(args, "consent", None), args.commit, h)
    if args.command == "preview-v2":
        answer = {"project_id": args.project_id, "commit": body["commit"], "base_commit": body["base_commit"],
                  "preview_digest": preview_digest(args.project_id, body),
                  "artifacts": [{"part": row["part"], "stage": row["stage"],
                                 "paths": [file["path"] for file in row["source_files"]]} for row in body["artifacts"]]}
    else:
        if not routing.url:
            raise ValueError("configure the NEXUS address before publishing")
        answer = send(routing.url, args.project_id, body, env, h)
    answer = h.companion("commands").scrub(answer, home, env, h)
    h.say(h.dump(answer, compact=args.json))
    return 0
