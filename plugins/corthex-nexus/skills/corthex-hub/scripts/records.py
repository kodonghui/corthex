"""Atomic repository stage records; never commits, pushes or opens a PR."""
import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

CHECKPOINT = r"nk_[0-9a-hjkmnp-tv-z]{12}"
# NEXUS v3: status reads the held commit only to build a checkpoint's link, so it waits at most this long.
HELD_SECONDS = 10
UNREAD = ("could not read the NEXUS server's held commit to tell NEXUS v3 from v2 (%s), so nothing was written; "
          "pass --where with the checkpoint's https link")


def checkpoint_link(project, part, stage, checkpoint, home, h, env=None, client_factory=None):
    """The link of a checkpoint passed in NEXUS, for status --nexus without --where.

    The held-commit answer (API-243) tells the two servers apart, as it does for push: a server that lists
    corthex-hub/0.3 in formats is NEXUS v3, which shows a stage at /p/<project>/<part or _>/<stage> (its
    sitemap's SCR-145); any other answer, and a bare 404 from a server older than the held commit, keeps v2's
    overview link as it was. This is the only request that status makes: one GET to the profile's nexus.url, for a
    project in nexus.push, with the token from the environment as push sends it. When the answer cannot be read,
    status writes nothing.
    """
    env = os.environ if env is None else env
    profile = h.profile_of(home)
    config = profile.get("nexus") if isinstance(profile.get("nexus"), dict) else {}
    base = config.get("url")
    if not isinstance(base, str) or not base.strip():
        raise ValueError("set nexus.url or --where for the checkpoint's link")
    listed = config.get("push") if isinstance(config.get("push"), list) else []
    if project.name not in listed:
        raise ValueError(UNREAD % "the project is not in nexus.push")
    try:
        client = (client_factory or h.companion("transport").Client)(base, env, version=h.VERSION, timeout=HELD_SECONDS)
    except ValueError:
        raise ValueError(UNREAD % "nexus.url is not a valid NEXUS address")
    held = client.call("GET", "/api/snapshots/" + project.name + "/held")
    place = quote(project.name, safe="") + "/" + quote(part or "_", safe="") + "/" + stage
    overview = base.rstrip("/") + "/overview/" + place + "#" + checkpoint
    if held.get("outcome") != "done":
        code = (held.get("problem") or {}).get("code")
        failure = held.get("failure")
        if not code and failure == "HTTP 404":
            # A server without the held commit is older still, as push reads it ("needs the 0.2 release"): not v3.
            return overview
        code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,59}", code) else None
        reason = ("the server holds no such project" if code == "project_not_found" else
                  "the server answered " + code if code else
                  "no service token: set CORTHEX_NEXUS_CLIENT_ID and CORTHEX_NEXUS_CLIENT_SECRET" if failure == "no service token" else
                  failure if isinstance(failure, str) and failure else "no answer")
        raise ValueError(UNREAD % reason)
    formats = h.companion("snapshot03")
    if formats.choose(held.get("answer")) == formats.NEW:
        return base.rstrip("/") + "/p/" + place
    return overview


def safe_link(value, h, home=None):
    return h.companion("commands").link(value, home or Path.home(), os.environ, h)


def role(value, h, home=None):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 120 and not h.CONTROL.search(value) and
            h.companion("commands").scrub(value, home or Path.home(), os.environ, h) == value)


def guard_home():
    """Per-user serialization also spans separate --home configuration roots."""
    return Path.home()


def directory_identity(path):
    if os.name != "nt":
        info = path.stat()
        return info.st_dev, info.st_ino
    # Python's Windows stat device width differs between supported runtimes.
    # Use the same native API in all of them, including directory aliases.
    import ctypes
    from ctypes import wintypes
    class Information(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                    ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                    ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                    ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                    ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.GetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.POINTER(Information))
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.CreateFileW(str(path), 0, 7, None, 3, 0x02000000, None)
    if handle is None or handle == ctypes.c_void_p(-1).value:
        raise OSError("the repository record directory identity is unavailable")
    try:
        info = Information()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise OSError("the repository record directory identity is unavailable")
        return info.volume, info.index_high, info.index_low
    finally:
        kernel.CloseHandle(handle)


def guard_path(target, repository=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    key = (":".join(str(value) for value in directory_identity(target.parent)) + ":" + target.name).encode("utf8")
    root = guard_home().resolve()
    for name in (".corthex", "hub", "record-locks"):
        root = root / name
        root.mkdir(mode=0o700, exist_ok=True)
        info = root.lstat()
        if root.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("the repository record guard must not follow a redirected directory")
    if repository is not None:
        try:
            root.resolve().relative_to(repository.resolve())
        except ValueError:
            pass
        else:
            raise ValueError("the repository record guard must stay outside the repository")
    return root / (hashlib.sha256(key).hexdigest() + ".guard")


def write(project, home, args, api, now=None, client_factory=None):
    h = SimpleNamespace(**api)
    settings = project.settings
    raw_parts = settings.get("parts")
    parts = raw_parts if (isinstance(raw_parts, list) and 1 <= len(raw_parts) <= 50 and
                          all(isinstance(x, str) and len(x) <= 100 and h.NAME.fullmatch(x) for x in raw_parts) and
                          len(set(raw_parts)) == len(raw_parts)) else []
    part = getattr(args, "part", "") or ""
    if part and part not in parts:
        raise ValueError("--part must name a part declared in the project settings")
    # Without --repository the original device status remains available until
    # the checkout actually has repository records. Do not infer from Git.
    folder = project.root / ".corthex" / "stages"
    global_file = project.root / ".corthex" / "stages.json"
    existing = global_file.exists() or any((folder / (p + ".json")).exists() for p in parts)
    if not getattr(args, "repository", False) and not existing:
        if part:
            raise ValueError("part records need --repository for their first write")
        return None
    if parts and not part:
        raise ValueError("use --part for a repository record in a project with parts")
    target = folder / (part + ".json") if part else global_file
    if not h.inside(target.resolve(), project.root.resolve()):
        raise ValueError("the records path leaves the project repository")
    current_path = target
    while current_path != project.root:
        if current_path.is_symlink():
            raise ValueError("repository records must not follow a symbolic link")
        current_path = current_path.parent
    def link(nexus):
        # NEXUS v3: the server's held commit says which link to build; update() asks once every local check passed.
        return checkpoint_link(project, part, args.stage, nexus, home, h, client_factory=client_factory)

    boxes = h.companion("outbox")
    try:
        with boxes.guard(guard_path(target, project.root)):
            return update(project, home, args, h, target, part, now, link)
    except boxes.Busy:
        raise ValueError("another hub is recording this file; try status again")


def update(project, home, args, h, target, part, now, link=None):
    if target.exists():
        data = h.load_json(target)
        if (not isinstance(data, dict) or type(data.get("format")) is not int or data.get("format") != 1 or
                data.get("project") != project.name or data.get("part", "") != part or not isinstance(data.get("stages"), dict)):
            raise ValueError("existing repository records are invalid; preserve and repair them before writing")
    else:
        data = {"format": 1, "project": project.name}
        if part:
            data["part"] = part
        data["stages"] = {}
    now = now or h.now_text()
    stages = data["stages"]
    old = stages.get(args.stage, {})
    if not isinstance(old, dict) and not args.reset:
        raise ValueError("the existing stage record is invalid")
    if args.reset:
        stages.pop(args.stage, None)
        entry = {}
    else:
        state = args.state or old.get("state", "in_progress")
        if state not in h.STATES:
            raise ValueError("the existing stage state is invalid; set --state or repair it before writing")
        checkpoints = old.get("checkpoints", [])
        if not isinstance(checkpoints, list):
            raise ValueError("the existing checkpoint list is invalid")
        checkpoints = checkpoints[:]
        approval = getattr(args, "checkpoint", None)
        by = getattr(args, "by", None)
        where = getattr(args, "where", None)
        nexus = getattr(args, "nexus", None)
        if any(x is not None for x in (by, where, nexus, args.date)) and not approval:
            raise ValueError("--by, --date, --where and --nexus accompany --checkpoint")
        if approval:
            if not role(by, h, home) or not args.date:
                raise ValueError("a repository checkpoint needs --by ROLE and --date YYYY-MM-DD")
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
                    raise ValueError()
                date.fromisoformat(args.date)
            except ValueError:
                raise ValueError("--date must be a valid YYYY-MM-DD")
            checkpoint = {"approved": h.one_line(approval, 2000), "by": by}
            if nexus:
                if not re.fullmatch(CHECKPOINT, nexus):
                    raise ValueError("--nexus must name a checkpoint ID")
                checkpoint["nexus"] = nexus
            if where is not None:
                if not safe_link(where, h, home):
                    raise ValueError("--where must be an HTTPS link without secrets or email addresses")
                checkpoint["where"] = where
            checkpoint["date"] = args.date
            checkpoints.append(checkpoint)
        if state == "done" and not any(isinstance(cp, dict) and cp.get("approved") and
                                       h.companion("snapshot02").calendar_date(cp.get("date")) for cp in checkpoints):
            raise ValueError("record done with its checkpoint and date")
        for cp in checkpoints:
            if (not isinstance(cp, dict) or not isinstance(cp.get("approved"), str) or not cp["approved"].strip() or
                    len(cp["approved"]) > 2000 or not role(cp.get("by"), h, home) or
                    not h.companion("snapshot02").calendar_date(cp.get("date")) or
                    ("where" in cp and not safe_link(cp["where"], h, home)) or
                    ("nexus" in cp and (not isinstance(cp["nexus"], str) or not re.fullmatch(CHECKPOINT, cp["nexus"])))):
                raise ValueError("the existing checkpoint list is invalid; preserve and repair it before writing")
        if getattr(args, "next") is None and not isinstance(old.get("next", ""), str):
            raise ValueError("the existing next action is invalid; set --next or repair it before writing")
        entry = {"state": state, "checkpoints": checkpoints,
                 "next": h.one_line(getattr(args, "next"), 300) if getattr(args, "next") is not None else old.get("next", "")}
        checks = [] if args.clear_checks else old.get("checks", [])
        if not isinstance(checks, list):
            raise ValueError("the existing review findings are invalid")
        checks = checks[:]
        for level, message in args.check or ():
            if level not in h.LEVELS:
                raise ValueError("a check level must be error, warn or info")
            checks.append({"level": level, "message": h.one_line(message, 300), "at": now[:10]})
        if checks:
            entry["checks"] = checks
        if approval and nexus and where is None:
            # A checkpoint passed in NEXUS without --where: its link comes from the server, read last, after every local check.
            where = link(nexus) if link is not None else None
            if where is None:
                raise ValueError("set nexus.url or --where for the checkpoint's link")
            if not safe_link(where, h, home):
                raise ValueError("--where must be an HTTPS link without secrets or email addresses")
            checkpoints[-1] = {"approved": checkpoint["approved"], "by": by, "nexus": nexus, "where": where, "date": args.date}
        entry["updated"] = now
        entry = h.companion("commands").scrub(entry, home, os.environ, h)
        stages[args.stage] = entry
    # Rebuild only the envelope, preserving every other stage and part file.
    ordered = {"format": 1, "project": project.name}
    if part:
        ordered["part"] = part
    ordered["stages"] = {key: stages[key] for key in h.STAGE_KEYS if key in stages}
    unknown = set(stages) - set(h.STAGE_KEYS)
    if unknown:
        raise ValueError("the existing file contains unknown stages; preserve and repair it before writing")
    h.companion("outbox").atomic(target, ordered)
    return entry, target
