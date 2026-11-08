"""The NEXUS 0.2 hub command surface and machine-readable outcomes."""
import argparse
import json
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

NETWORK = {"push", "remove", "todo", "comment", "reply", "answered", "decide", "propose", "withdraw", "reflect", "record", "show", "claim", "release", "outbox"}
WRITES = {"comment", "reply", "answered", "decide", "propose", "withdraw", "reflect", "record"}
SESSION_REQUIRED = WRITES | {"claim", "release"}
PICTURE_STAGES = ("01-domain", "05-erd", "07-sitemap")
# 0.3.0: a comment takes any of the 13 stages, and the agent's comment or reply says what it asks of the user.
STAGE_KEYS = ("01-domain", "02-prd", "03-user-flow", "04-functional-spec", "05-erd", "06-api", "07-sitemap",
              "08-screen-states", "09-mockup", "10-wbs", "11-development", "12-qa", "13-presentation")
ASKS = ("answer", "recommended", "checkpoint")
TRACE = re.compile(r"[A-Z][A-Z0-9]*-[0-9]{1,6}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?\Z")
ENTRY = re.compile(r"n([cpdek])_[0-9a-hjkmnp-tv-z]{12}\Z")
SESSION = re.compile(r"[A-Za-z0-9._:-]{1,100}\Z")


class CommandLine(ValueError):
    pass


def outcome(command, project, value=None, stats=None):
    value = value or {"outcome": "done"}
    row = {"command": command, "project": project, "outcome": value["outcome"],
            "answer": value.get("answer"), "problem": value.get("problem"), "failure": value.get("failure"),
            "outbox": stats or {"sent": 0, "dropped": 0, "waiting": 0}}
    if value.get("recovery") is not None:
        row["recovery"] = value["recovery"]
    return row


def scrub(value, home, env, h):
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            safe = scrub(item, home, env, h)
            if key in ("where", "link", "url", "web") and isinstance(item, str) and item.startswith(("https://", "http://")):
                if safe != item or scrub(unquote(item), home, env, h) != unquote(item):
                    continue
            cleaned[scrub(key, home, env, h)] = safe
        return cleaned
    if isinstance(value, list):
        return [scrub(item, home, env, h) for item in value]
    if not isinstance(value, str):
        return value
    for key in ("CORTHEX_NEXUS_CLIENT_ID", "CORTHEX_NEXUS_CLIENT_SECRET"):
        secret = env.get(key)
        if secret:
            value = value.replace(secret, "[redacted]")
    for folder in {str(Path(home)), str(Path.home())}:
        if folder not in ("", ".", "/", "\\"):
            pattern = r"[/\\]".join(re.escape(piece) for piece in re.split(r"[/\\]", folder))
            value = re.sub(pattern, "~", value, flags=re.I if os.name == "nt" else 0)
    return h.SECRET_TEXT.sub("[redacted]", value)


def link(value, home, env, h):
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and
                scrub(unquote(value), home, env, h) == unquote(value))
    except ValueError:
        return False


def text_value(args, name, required=False):
    value, file = getattr(args, name, None), getattr(args, name + "_file", None)
    if file is not None:
        try:
            value = sys.stdin.buffer.read().decode("utf8") if file == "-" else Path(file).read_text(encoding="utf8")
        except (UnicodeError, OSError):
            raise CommandLine("--" + name.replace("_", "-") + "-file must be readable UTF-8")
    if required and (not isinstance(value, str) or not value.strip()):
        raise CommandLine("--" + name.replace("_", "-") + " needs text")
    return value


def validate(args, env, h):
    session = (getattr(args, "session", None) or env.get("CORTHEX_NEXUS_SESSION")) if args.command in SESSION_REQUIRED | {"todo"} else None
    if args.command in SESSION_REQUIRED and not session:
        raise CommandLine("set --session or CORTHEX_NEXUS_SESSION")
    if session is not None and (not isinstance(session, str) or not SESSION.fullmatch(session)):
        raise CommandLine("a session label uses 1 to 100 ASCII letters, digits, dot, underscore, colon or hyphen")
    for field in ("commit",):
        value = getattr(args, field, None)
        if value is not None and not COMMIT.fullmatch(value):
            raise CommandLine("--commit needs a full Git commit ID")
    ident = getattr(args, "entry", None)
    if ident:
        match = ENTRY.fullmatch(ident)
        allowed = {"reply": "c", "answered": "c", "decide": "c", "withdraw": "p", "reflect": "e", "record": "k", "show": "cpek", "claim": "cdek", "release": "cdek"}[args.command]
        if not match or match.group(1) not in allowed:
            raise CommandLine("the entry ID has the wrong form for this command")
    for field, prefix in (("comment", "c"), ("discrepancy", "d")):
        value = getattr(args, field, None)
        if value and not re.fullmatch("n" + prefix + r"_[0-9a-hjkmnp-tv-z]{12}", value):
            raise CommandLine("--" + field + " has the wrong ID form")
    items = getattr(args, "item", None)
    if isinstance(items, str):
        items = [items]
    for ident in (items or []) + (getattr(args, "adds", None) or []):
        if not TRACE.fullmatch(ident):
            raise CommandLine("an item needs a trace ID")
    if args.command == "propose" and (len(set(items)) != len(items) or len(items) > 50):
        raise CommandLine("--item needs up to 50 different trace IDs")
    adds = getattr(args, "adds", None) or []
    if len(adds) > 50 or len(set(adds)) != len(adds):
        raise CommandLine("--adds needs up to 50 different trace IDs")
    part = getattr(args, "part", "")
    if part and (len(part) > 100 or not h.NAME.fullmatch(part)):
        raise CommandLine("--part needs a lowercase project part name")
    return session


def write_request(args, project, home, env, h):
    base = "/api/spaces/" + project
    command = args.command
    body = {}
    if command in ("comment", "propose"):
        body = {"part": args.part, "stage": args.stage}
        if args.commit:
            body["commit"] = args.commit
        if args.discrepancy:
            body["discrepancy"] = args.discrepancy
    if command == "comment":
        body.update(item=args.item or "", text=text_value(args, "text", True))
        if args.quote is not None:
            body["quote"] = args.quote
        if args.asks:
            body["asks"] = args.asks
        name, path = "comment", base + "/comments"
    elif command == "reply":
        body["text"] = text_value(args, "text", True)
        if args.asks:
            body["asks"] = args.asks
        name, path = "reply", base + "/comments/" + args.entry + "/replies"
    elif command == "answered":
        name, path = "answered", base + "/comments/" + args.entry + "/answered"
    elif command == "decide":
        if not link(args.link, home, env, h):
            raise CommandLine("--link needs an HTTPS address without secrets or email addresses")
        body["link"] = args.link
        text = text_value(args, "text")
        if text is not None:
            body["text"] = text
        name, path = "decision", base + "/comments/" + args.entry + "/decisions"
    elif command == "propose":
        body.update(items=args.item, reason=text_value(args, "reason", True), change=text_value(args, "change", True))
        if args.adds:
            body["adds"] = args.adds
        if args.source_file:
            body["source_text"] = text_value(SimpleNamespace(source=None, source_file=args.source_file), "source", True)
        if args.comment:
            body["comment"] = args.comment
        name, path = "proposal", base + "/proposals"
    elif command == "withdraw":
        name, path = "withdraw-proposal", base + "/proposals/" + args.entry + "/withdraw"
    else:
        body["event"] = args.event
        if getattr(args, "pr", None):
            if not link(args.pr, home, env, h):
                raise CommandLine("--pr needs an HTTPS address without secrets or email addresses")
            body["pull_request"] = args.pr
        if getattr(args, "commit", None):
            body["commit"] = args.commit
        if args.event in ("opened", "merged", "closed") and "pull_request" not in body:
            raise CommandLine("this report needs --pr")
        if args.event == "reflected" and "commit" not in body:
            raise CommandLine("reflected needs --commit")
        name, path = ("report-edit", base + "/edits/" + args.entry + "/report") if command == "reflect" else ("report-checkpoint", base + "/checkpoints/" + args.entry + "/report")
    return name, path, scrub(body, home, env, h)


def commit_replacement(snapshot, held, project, replace_held, h):
    current = held.get("default_commit")
    if current is None:
        return None
    if not isinstance(current, str) or not COMMIT.fullmatch(current):
        return "invalid held-commit answer"
    incoming = snapshot.get("repos", {}).get(".", {}).get("default", {}).get("commit")
    if not incoming:
        return "no default branch; fetch and run git remote set-head origin --auto"
    if current == incoming:
        return None
    if h.git(project.root, "cat-file", "-t", current) != "commit":
        return "the held commit is not in this checkout; fetch the default branch and push again"
    if h.run_git(project.root, ["merge-base", "--is-ancestor", current, incoming]) is not None:
        snapshot["replaces"] = current
        return None
    if h.run_git(project.root, ["merge-base", "--is-ancestor", incoming, current]) is not None:
        return "the checkout is behind the held commit; fetch the default branch and push again"
    if replace_held:
        snapshot["replaces"] = current
        return None
    return "default branch diverged: held " + current + ", incoming " + incoming + "; use --replace-held only after the user agrees"


def execute(args, home, api, env=None, client_factory=None):
    h = SimpleNamespace(**api)
    env = os.environ if env is None else env
    session = validate(args, env, h)
    transport, boxes = h.companion("transport"), h.companion("outbox")
    command = args.command
    profile = h.profile_of(home)
    config = profile.get("nexus") if isinstance(profile.get("nexus"), dict) else {}
    allowed = config.get("push") if isinstance(config.get("push"), list) else []
    raw_names = args.project if isinstance(args.project, list) else [args.project]
    names = raw_names or allowed
    if command == "outbox" and not raw_names:
        root = Path(home) / ".corthex" / "hub" / "outbox"
        names = sorted(x.name for x in root.iterdir() if x.is_dir() and h.NAME.fullmatch(x.name)) if root.is_dir() else []
    if any(not isinstance(name, str) or len(name) > 100 or not h.NAME.fullmatch(name) for name in names):
        raise CommandLine("a project name uses lowercase letters, digits and hyphens")
    if not names and command == "push":
        return [outcome(command, "", {"outcome": "refused", "failure": "no project is listed in nexus.push"})]
    request = write_request(args, names[0], home, env, h) if command in WRITES else None
    client, setup_failure = None, None
    if not (command == "outbox" and not args.send):
        try:
            base = getattr(args, "url", None) or env.get("CORTHEX_NEXUS_URL") or config.get("url")
            if not isinstance(base, str) or not base:
                raise ValueError("no NEXUS address")
            client = (client_factory or transport.Client)(base, env, version=h.VERSION)
        except ValueError:
            setup_failure = "no NEXUS address, or the configured address is invalid"
    rows = []
    for name in names:
        stats = {"sent": 0, "dropped": 0, "waiting": 0}
        if command != "remove" and not (command == "outbox" and not args.send) and name not in allowed:
            rows.append(outcome(command, name, {"outcome": "refused", "failure": "not in nexus.push"})); continue
        pending = None
        try:
            box = boxes.Outbox(home, name)
        except (ValueError, OSError):
            value = {"outcome": "failed", "failure": "outbox unavailable"}
            if command in WRITES:
                pending = boxes.new_write(name, request[0], request[1], session, request[2])
                value.update(failure="write lost: outbox could not be written", recovery=pending)
            rows.append(outcome(command, name, value, stats))
            continue
        if command in WRITES:
            pending = box.make(request[0], request[1], session, request[2])
        project = None
        if command == "push":
            selected = h.select_projects(home, [name])[0]
            if selected[1] is None:
                rows.append(outcome(command, name, {"outcome": "refused", "failure": selected[2]})); continue
            project = selected[1]
            if args.dry_run:
                if setup_failure:
                    rows.append(outcome(command, name, {"outcome": "refused", "failure": setup_failure})); continue
                snapshot = h.make_snapshot(project, h.load_status(home, name), home=home)
                h.save_snapshot(home, snapshot)
                answer = {"bytes": len(h.dump(snapshot, compact=True).encode("utf8")), "summary": snapshot["summary"],
                    "pictures": [{"part": p["part"], "stage": p["stage"]} for p in snapshot["pictures"]], "left_out": snapshot["left_out"],
                    "held_commit": "checked when sent"}
                rows.append(outcome(command, name, {"outcome": "done", "answer": answer})); continue
        value = None
        try:
            with box.lease() as lease:
                if pending is not None:
                    # Publish the original ID before any send; this command
                    # then uses exactly the same ordered drain as a retry.
                    box.save(pending, {"failure": setup_failure} if setup_failure else None, lease, count_attempt=False)
                if command != "remove":
                    stats, waiting = box.drain(client, lease, send=client is not None and not (command == "outbox" and not args.send))
                else:
                    waiting = []
                if command == "outbox":
                    value = {"outcome": "done", "answer": {"writes": waiting}}
                    if args.send and setup_failure:
                        value = {"outcome": "failed", "answer": {"writes": waiting}, "failure": setup_failure}
                    elif args.send and stats["waiting"]:
                        value = {"outcome": "kept", "answer": {"writes": waiting}, "failure": waiting[0].get("failure")}
                elif command in WRITES:
                    value = box.attempts.get(pending["write"])
                    if value is None:
                        value = {"outcome": "kept", "failure": setup_failure or "an earlier outbox write is waiting"}
                    elif value.get("retry"):
                        value = dict(value, outcome="kept")
                elif setup_failure:
                    value = {"outcome": "refused" if command == "push" else "failed", "failure": setup_failure}
                elif command == "push":
                    lease.renew()
                    held = client.call("GET", "/api/snapshots/" + name + "/held")
                    problem = held.get("problem") or {}
                    if held["outcome"] != "done" and problem.get("code") != "project_not_found":
                        value = held if problem.get("code") else {"outcome": "refused", "failure": "the server needs the 0.2 release"} if held.get("failure") == "HTTP 404" else held
                        if value.get("failure") == "no service token":
                            value = dict(value, outcome="refused", failure="no service token: set CORTHEX_NEXUS_CLIENT_ID and CORTHEX_NEXUS_CLIENT_SECRET")
                    else:
                        snapshot = h.make_snapshot(project, h.load_status(home, name), home=home)
                        h.save_snapshot(home, snapshot)
                        failure = commit_replacement(snapshot, held.get("answer") or {}, project, args.replace_held, h)
                        if failure:
                            value = {"outcome": "refused", "failure": failure}
                        else:
                            lease.renew()
                            value = client.call("POST", "/api/snapshots", snapshot)
                elif command == "remove":
                    lease.renew()
                    path = "/api/snapshots/" + name + ("/removal" if args.dry_run else "")
                    value = client.call("GET" if args.dry_run else "DELETE", path)
                    if (value.get("problem") or {}).get("code") == "project_not_found":
                        value = {"outcome": "done", "answer": {"removed": False}}
                    if value["outcome"] == "done" and not args.dry_run:
                        box.clear(lease)
                        if name in allowed:
                            value.setdefault("answer", {})["next_push"] = "brings this project back with an empty space; remove it from nexus.push to stop pushes"
                elif command == "todo":
                    value = client.call("GET", "/api/spaces/" + name + "/todo", session=session)
                    if (value.get("problem") or {}).get("code") == "space_not_found":
                        value = {"outcome": "done", "answer": {"comments": {"total": 0, "entries": []}, "discrepancies": {"total": 0, "entries": []}, "reflections": {"total": 0, "entries": []}, "checkpoints": {"total": 0, "entries": []}, "waiting_for_user": 0, "taken": 0}}
                elif command == "show":
                    kind = {"c": "comments", "p": "proposals", "e": "edits", "k": "checkpoints"}[args.entry[1]]
                    value = client.call("GET", "/api/spaces/" + name + "/" + kind + "/" + args.entry)
                else:
                    value = client.call("POST" if command == "claim" else "DELETE", "/api/spaces/" + name + "/claims/" + args.entry, session=session)
        except boxes.Busy:
            failure = "another hub is sending this project's outbox"
            value = interrupted(box, pending, value, failure, stats)
        except boxes.Lost:
            failure = "the outbox lock was taken over"
            value = interrupted(box, pending, value, failure, stats)
        except (OSError, ValueError):
            value = interrupted(box, pending, value, "outbox cleanup failed" if value is not None else "outbox unavailable", stats)
        # Lease release can itself fail. Publish exactly one outcome only
        # after that cleanup has either completed or been handled above.
        rows.append(outcome(command, name, value, stats))
    return scrub(rows, home, env, h)


def interrupted(box, pending, value, failure, stats):
    if value is not None:
        return dict(value, failure=failure)
    if pending is not None:
        attempt = box.attempts.get(pending["write"])
        if attempt is not None and not attempt.get("retry"):
            return dict(attempt, failure=failure)
        return recover(box, pending, failure, stats)
    return {"outcome": "failed", "failure": failure}


def recover(box, pending, failure, stats):
    """Unique-append recovery cannot mutate a new lease holder's file."""
    try:
        box.save(pending, {"failure": failure}, None, count_attempt=False)
        stats["waiting"] = len(box.files())
        return {"outcome": "kept", "failure": failure}
    except (OSError, ValueError, RuntimeError):
        return {"outcome": "failed", "failure": "write lost from outbox; server receipt unconfirmed", "recovery": pending}


def emit(args, rows, h):
    for row in rows:
        if args.json:
            h.say(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        else:
            h.say((row["project"] or "project") + ": " + row["command"] + " " + row["outcome"])
            if row["failure"]:
                h.say("  " + row["failure"])
            if row["problem"]:
                h.say("  " + h.one_line(row["problem"].get("code", "refused")) + ": " + h.one_line(row["problem"].get("detail", ""), 300))
            if row["answer"]:
                h.say(json.dumps(row["answer"], ensure_ascii=False, indent=2))
            if "recovery" in row:
                h.say("  Recovery copy for the calling agent, once; keep it in this session, never a log:")
                h.say(json.dumps(row["recovery"], ensure_ascii=False, indent=2))
            if any(row["outbox"].get(key) for key in ("sent", "dropped", "waiting")):
                h.say("  outbox: " + json.dumps(row["outbox"], ensure_ascii=False))
    return 3 if any(r["outcome"] == "kept" for r in rows) else 1 if any(r["outcome"] in ("failed", "refused") for r in rows) else 0


def configure(top, commands, existing, h):
    def common(parser, session=False):
        parser.add_argument("--url")
        if session:
            parser.add_argument("--session")
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    def text(parser, name, required=False):
        choice = parser.add_mutually_exclusive_group(required=required)
        choice.add_argument("--" + name)
        choice.add_argument("--" + name + "-file")
    top.add_argument("--json", action="store_true", default=False)
    for parser in existing.values():
        parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    existing["push"].add_argument("--replace-held", action="store_true")
    status = existing["status"]
    for name in ("part", "by", "where", "nexus"):
        status.add_argument("--" + name, default="" if name == "part" else None)
    status.add_argument("--repository", action="store_true")
    for name in ("todo", "comment", "reply", "answered", "decide", "propose", "withdraw", "reflect", "record", "show", "claim", "release", "outbox"):
        parser = commands.add_parser(name)
        parser.add_argument("project", nargs="*" if name == "outbox" else None)
        common(parser, name in SESSION_REQUIRED or name == "todo")
        if name in ("reply", "answered", "decide", "withdraw", "reflect", "record", "show", "claim", "release"):
            parser.add_argument("entry")
        if name in ("comment", "propose"):
            parser.add_argument("--part", default="")
            parser.add_argument("--stage", required=True, choices=STAGE_KEYS if name == "comment" else PICTURE_STAGES)
            parser.add_argument("--item", action="append" if name == "propose" else "store", required=name == "propose")
            parser.add_argument("--commit")
            if name == "comment":
                parser.add_argument("--discrepancy")
        if name in ("comment", "reply", "decide"):
            text(parser, "text", required=name != "decide")
        if name in ("comment", "reply"):
            parser.add_argument("--asks", choices=ASKS)
        if name == "comment":
            parser.add_argument("--quote")
        if name == "decide":
            parser.add_argument("--link", required=True)
        if name == "propose":
            parser.add_argument("--adds", nargs="*", default=[])
            text(parser, "reason", True); text(parser, "change", True)
            parser.add_argument("--source-file")
            target = parser.add_mutually_exclusive_group()
            target.add_argument("--comment")
            target.add_argument("--discrepancy")
        if name in ("reflect", "record"):
            parser.add_argument("event", choices=("opened", "merged", "closed", "reflected", "needs-user") if name == "reflect" else ("opened", "merged", "closed"))
            parser.add_argument("--pr", required=name == "record")
            if name == "reflect":
                parser.add_argument("--commit")
        if name == "outbox":
            parser.add_argument("--send", action="store_true")
