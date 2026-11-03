"""Atomic repository stage records; never commits, pushes or opens a PR."""
import json
import os
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote


def safe_link(value, h, home=None):
    return h.companion("commands").link(value, home or Path.home(), os.environ, h)


def role(value, h, home=None):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= 120 and not h.CONTROL.search(value) and
            h.companion("commands").scrub(value, home or Path.home(), os.environ, h) == value)


def write(project, home, args, api, now=None):
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
                if not re.fullmatch(r"nk_[0-9a-hjkmnp-tv-z]{12}", nexus):
                    raise ValueError("--nexus must name a checkpoint ID")
                checkpoint["nexus"] = nexus
                if where is None:
                    profile = h.profile_of(home)
                    config = profile.get("nexus") if isinstance(profile.get("nexus"), dict) else {}
                    base = config.get("url")
                    if not isinstance(base, str):
                        raise ValueError("set nexus.url or --where for the checkpoint's overview link")
                    where = base.rstrip("/") + "/overview/" + quote(project.name, safe="") + "/" + quote(part or "_", safe="") + "/" + args.stage + "#" + nexus
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
                    ("nexus" in cp and (not isinstance(cp["nexus"], str) or not re.fullmatch(r"nk_[0-9a-hjkmnp-tv-z]{12}", cp["nexus"])))):
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
