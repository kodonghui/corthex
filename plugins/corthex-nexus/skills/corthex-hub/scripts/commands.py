"""The NEXUS 0.2 hub command surface and machine-readable outcomes."""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit

NETWORK = {"push", "remove", "todo", "comment", "reply", "answered", "decide", "propose", "withdraw", "reflect", "record", "show", "claim", "release", "outbox"}
# 0.4.0: can-send says whether a session can send, and never contacts the server (API-179).
ANSWERED = NETWORK | {"can-send"}
TOKEN = ("CORTHEX_NEXUS_CLIENT_ID", "CORTHEX_NEXUS_CLIENT_SECRET")
REMARKS = {"push-variable-ignored": "CORTHEX_NEXUS_PUSH is ignored, since this device has a profile or a list of projects",
           "server-older": "the server is of before the design revision, so the hub did what it could in the older form",
           "sent-as-reply": "the stage had an open checkpoint request, so the request went as a reply on it"}
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
PART = re.compile(r"(?:[a-z0-9]+(?:-[a-z0-9]+)*)?\Z")
# 0.4.0: the session reads file (TBL-125) keeps each session's last read of the agent to-do, by the
# server's time, so that todo --if-due reads again only once a day has passed (SPEC-191).
TIME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z\Z")
HOUR, DAY, WEEK = 60 * 60, 24 * 60 * 60, 7 * 24 * 60 * 60
# Each list's time of the unread rule: a withdrawn checkpoint counts from its withdrawal.
SINCE = (("comments", "last_at"), ("discrepancies", "opened_at"), ("reflections", "made_at"), ("checkpoints", "passed_at"))
# 0.4.0: a project's first push waits for the user's yes, which --first carries (SPEC-111, REQ-107).
FIRST_PUSH = "first push needs --first"
# 0.4.0: a checkpoint request is taken only in form, and the hub reads the to-do before it (SPEC-197, SPEC-191).
READ_FIRST = "read the to-do first"
UNKNOWN_STAGE = "the comment's stage could not be read, so nothing was kept; send the request again"
NOTES = {READ_FIRST: "entries came in since the session's read before: answer those on the stage, or name them in the request as open, and send it again",
         FIRST_PUSH: "the first push of this project to this server waits for the user's yes: push it with --first only after the user agrees"}


class CommandLine(ValueError):
    pass


def outcome(command, project, value=None, stats=None, remarks=()):
    value = value or {"outcome": "done"}
    row = {"command": command, "project": project, "outcome": value["outcome"],
            "answer": value.get("answer"), "problem": value.get("problem"), "failure": value.get("failure"),
            "outbox": stats or {"sent": 0, "dropped": 0, "waiting": 0},
            "remarks": list(dict.fromkeys(list(remarks) + list(value.get("remarks") or ())))}
    if command == "todo":
        # API-138: whether the hub read the server, the session's read before, and what is new since.
        row.update(read=value.get("read", False), since=value.get("since"), new=value.get("new"))
    for key in ("new", "address"):
        if key in value and key not in row:
            row[key] = value[key]
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
    if getattr(args, "first", False) and len(args.project) != 1:
        raise CommandLine("--first takes exactly one project, the one that the user agreed to push for the first time")
    return session


def look_first(args, project, home, env, h, url):
    """SPEC-197: the thing to look at first, a trace ID, an https address or the stage's page; None for a reply's stage."""
    value = args.look_first
    if TRACE.fullmatch(value) and len(value) <= 30:
        return value
    if value == "stage":
        if args.command == "reply":
            return "stage"
        try:
            base = h.companion("transport").Client(url, env, version=h.VERSION).base if isinstance(url, str) and url else None
        except ValueError:
            base = None
        if base is None:
            raise CommandLine("--look-first stage needs the NEXUS address: name an item's trace ID or an https address instead")
        return base + "/p/" + project + "/" + (args.part or "_") + "/" + args.stage
    if link(value, home, env, h):
        return value
    raise CommandLine("--look-first needs an item's trace ID, an https address without secrets or email addresses, or the word stage")


def checkpoint_form(args, body, home, env, h):
    """SPEC-197: a checkpoint request has no --item, at most 10 lines and 1,200 characters after redaction, and --look-first."""
    wrong = []
    if args.command == "comment" and args.item:
        wrong.append("leave out --item, since a checkpoint request is on the stage as a whole")
    text = scrub(body["text"], home, env, h)
    lines = text.count("\n") + 1
    if lines > 10 or len(text) > 1200:
        wrong.append("the text has %d line%s and %d characters after redaction; shorten it to at most 10 lines and 1,200 characters" %
                     (lines, "" if lines == 1 else "s", len(text)))
    if args.look_first is None:
        wrong.append("add --look-first with an item's trace ID, an https address or the word stage")
    if wrong:
        raise CommandLine("a checkpoint request is out of form: " + "; ".join(wrong))


def write_request(args, project, home, env, h, url=None):
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
    if command in ("comment", "reply"):
        if args.look_first is not None and args.asks != "checkpoint":
            raise CommandLine("--look-first goes only with --asks checkpoint")
        if args.asks == "checkpoint":
            checkpoint_form(args, body, home, env, h)
            body["look_first"] = look_first(args, project, home, env, h, url)
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


def where(args, home, env, h):
    """Where the address and the push list come from: the profile, or a session's environment (SPEC-192)."""
    url = getattr(args, "url", None)
    if h.environment_mode(home):
        listed = [x.strip() for x in (env.get("CORTHEX_NEXUS_PUSH") or "").split(",") if x.strip()]
        return SimpleNamespace(source="environment", allowed=listed, push="CORTHEX_NEXUS_PUSH", url=url or env.get("CORTHEX_NEXUS_URL"),
                               url_name="CORTHEX_NEXUS_URL", remarks=[], own=h.select_projects(home, [], None)[0])
    profile = h.profile_of(home)
    config = profile.get("nexus") if isinstance(profile.get("nexus"), dict) else {}
    allowed = config.get("push") if isinstance(config.get("push"), list) else []
    # A variable left in a shell never widens what a device with a profile sends.
    ignored = ["push-variable-ignored"] if (env.get("CORTHEX_NEXUS_PUSH") or "").strip() else []
    return SimpleNamespace(source="profile", allowed=allowed, push="nexus.push", url=url or env.get("CORTHEX_NEXUS_URL") or config.get("url"),
                           url_name="CORTHEX_NEXUS_URL" if not url and env.get("CORTHEX_NEXUS_URL") else "nexus.url", remarks=ignored, own=None)


def can_send(args, home, env, h, place):
    """API-179: whether the session can send for the project, by the names of what is missing (SPEC-190)."""
    name = args.project
    if place.source == "environment":
        own, project, _ = place.own
        if project is None or name != own:
            failure = "no project in this checkout" if project is None else "not this checkout's project: the checkout holds %s, not %s" % (own, name)
            return outcome("can-send", name, {"outcome": "refused", "failure": failure})
    else:
        _, project, failure = h.select_projects(home, [name])[0]
        if project is None:
            here = h.select_projects(home, [], None)[0]
            project = here[1] if here[0] == name else None
        if project is None:
            return outcome("can-send", name, {"outcome": "refused", "failure": failure})
    missing, local = [], False
    try:
        if not isinstance(place.url, str) or not place.url.strip():
            raise ValueError("no NEXUS address")
        local = h.companion("transport").Client(place.url, env, version=h.VERSION).local
    except ValueError:
        missing.append(place.url_name)
    if name not in place.allowed:
        missing.append(place.push)
    if not local:
        missing += [key for key in TOKEN if not env.get(key)]
    answer = {"can_send": not missing, "missing": missing,
              "expected": project.settings.get("on_nexus") is True or name in place.allowed, "source": place.source}
    return outcome("can-send", name, {"outcome": "done", "answer": answer})


def reads_file(home, project):
    """TBL-125's file, reads/<project>.json under the hub's folder, or None where a link would lead elsewhere."""
    folder = Path(home) / ".corthex" / "hub" / "reads"
    path = folder / (project + ".json")
    return None if folder.is_symlink() or path.is_symlink() else path


def session_reads(home, project, boxes):
    """The session reads, the newest first, or None when the file is missing or not valid (the contract's SessionReads)."""
    path = reads_file(home, project)
    try:
        data = json.loads(path.read_text(encoding="utf8")) if path is not None else None
    except (OSError, ValueError):
        return None
    if not (isinstance(data, dict) and set(data) == {"format", "project", "reads"} and type(data["format"]) is int and
            data["format"] == 1 and data["project"] == project and isinstance(data["reads"], list)):
        return None
    for entry in data["reads"]:
        if not (isinstance(entry, dict) and "at" in entry and not set(entry) - {"session", "at"} and isinstance(entry["at"], str) and
                TIME.fullmatch(entry["at"]) and boxes.timestamp(entry["at"]) is not None and
                ("session" not in entry or isinstance(entry["session"], str) and SESSION.fullmatch(entry["session"]))):
            return None
    return data["reads"]


def last_read(reads, session):
    """The session's kept time; sessions without a label share the entry that names none."""
    return next((entry["at"] for entry in reads or () if entry.get("session") == session), None)


def read_due(reads, session, now, boxes):
    """SPEC-191: due when nothing is kept for the session, or its time is more than a day old or more than an hour ahead."""
    at = last_read(reads, session)
    if at is None:
        return True
    stamp = boxes.timestamp(at)
    return now - stamp > DAY or stamp - now > HOUR


def keep_read(home, project, session, at, boxes):
    """Keep an answered read's time for the session through a temporary file and a move, without a lock (TBL-125).

    An entry goes 7 days after its time. Of two hubs that write at once one entry may be lost, and that
    session then reads once more.
    """
    path, now = reads_file(home, project), time.time()
    if path is None or not (isinstance(at, str) and TIME.fullmatch(at) and boxes.timestamp(at) is not None):
        return
    others = [entry for entry in session_reads(home, project, boxes) or ()
              if entry.get("session") != session and now - boxes.timestamp(entry["at"]) <= WEEK]
    mine = {"at": at} if session is None else {"session": session, "at": at}
    try:
        boxes.atomic(path, {"format": 1, "project": project, "reads": sorted([mine] + others, key=lambda entry: entry["at"], reverse=True)})
    except OSError:
        pass


def new_entries(answer, since, boxes):
    """API-138: each list's IDs whose time is at or after since, all of them when since is null (SPEC-191)."""
    start = boxes.timestamp(since) if since is not None else None
    new = {}
    for key, field in SINCE:
        listed = answer.get(key) if isinstance(answer.get(key), dict) else {}
        new[key] = []
        for entry in listed.get("entries") if isinstance(listed.get("entries"), list) else ():
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                continue
            when = entry.get("withdrawn_at") if key == "checkpoints" and entry.get("state") == "withdrawn" else entry.get(field)
            stamp = boxes.timestamp(when) if isinstance(when, str) else None
            # An entry whose time cannot be read is told rather than hidden.
            if start is None or stamp is None or stamp >= start:
                new[key].append(entry["id"])
    return new


def read_todo(client, home, project, session, kept, boxes):
    """Read the agent to-do, keep the answer's read_at for the session, and say what is new since its read before."""
    value = client.call("GET", "/api/spaces/" + project + "/todo", session=session)
    if (value.get("problem") or {}).get("code") == "space_not_found":
        return {"outcome": "done", "answer": {"comments": {"total": 0, "entries": []}, "discrepancies": {"total": 0, "entries": []}, "reflections": {"total": 0, "entries": []}, "checkpoints": {"total": 0, "entries": []}, "waiting_for_user": 0, "taken": 0},
                "read": True, "since": kept, "new": {key: [] for key, _ in SINCE}}
    if value["outcome"] != "done" or not isinstance(value.get("answer"), dict):
        return value
    answer = value["answer"]
    if "read_at" not in answer:
        # A server of before the design revision records no read, so nothing is kept (How versions meet).
        return dict(value, read=True, since=None, new=None, remarks=["server-older"])
    keep_read(home, project, session, answer["read_at"], boxes)
    return dict(value, read=True, since=kept, new=new_entries(answer, kept, boxes))


def comment_stage(client, lease, project, comment, read):
    """The part and stage of the comment that a reply asks again on, from the to-do or else from the server."""
    listed = ((read.get("answer") or {}).get("comments") or {}).get("entries")
    found = next((entry for entry in listed if isinstance(entry, dict) and entry.get("id") == comment), None) if isinstance(listed, list) else None
    if found is None:
        lease.renew()
        shown = client.call("GET", "/api/spaces/" + project + "/comments/" + comment)
        found = shown.get("answer") if shown["outcome"] == "done" else None
    if (not isinstance(found, dict) or found.get("stage") not in STAGE_KEYS or not isinstance(found.get("part"), str) or
            len(found["part"]) > 100 or not PART.fullmatch(found["part"])):
        return None
    return found["part"], found["stage"]


def keepable(pending):
    """A write that can wait in the outbox: a reply whose thing to look at first is its stage needs that stage first."""
    return None if pending is not None and pending["body"].get("look_first") == "stage" else pending


def ask_checkpoint(box, client, lease, home, name, session, pending, kept, boxes, origin):
    """Send a checkpoint request after the outbox and a read of the to-do, or hold it back once (SPEC-191, SPEC-197).

    Returns the outcome, the outbox's counts and the remarks. When the read gets no answer the request waits
    in the outbox, as any write does; a reply that names its stage then cannot, and nothing is kept.
    """
    stats, _ = box.drain(client, lease)
    replied = bool(box.replies)
    unresolved = keepable(pending) is None
    if stats["waiting"]:
        if unresolved:
            return {"outcome": "failed", "failure": UNKNOWN_STAGE}, stats, []
        box.save(pending, None, lease, count_attempt=False)
        stats["waiting"] = len(box.files())
        return {"outcome": "kept", "failure": "an earlier outbox write is waiting"}, stats, []
    lease.renew()
    read = read_todo(client, home, name, session, kept, boxes)
    if read["outcome"] != "done" and not read.get("retry"):
        # The server answered the read with a refusal: the request is not sent, and not kept.
        return {"outcome": read["outcome"], "problem": read.get("problem"), "failure": read.get("failure")}, stats, []
    if read["outcome"] != "done":
        if unresolved:
            return {"outcome": "failed", "failure": UNKNOWN_STAGE}, stats, []
        box.save(pending, read, lease, count_attempt=False)
        stats["waiting"] = len(box.files())
        return {"outcome": "kept", "failure": boxes.failure_of(read)}, stats, []
    remarks = list(read.get("remarks") or ())
    if read.get("new") and any(read["new"].values()):
        return {"outcome": "refused", "failure": READ_FIRST, "new": read["new"]}, stats, remarks
    body = dict(pending["body"])
    if unresolved:
        where = comment_stage(client, lease, name, pending["path"].split("/")[-2], read)
        if where is None:
            return {"outcome": "failed", "failure": UNKNOWN_STAGE}, stats, remarks
        body["look_first"] = origin + "/p/" + name + "/" + (where[0] or "_") + "/" + where[1]
    if "server-older" in remarks:
        # How versions meet: the old form, whose last line is the thing to look at first.
        body["text"] = body["text"] + "\n" + body.pop("look_first")
    pending = dict(pending, body=body)
    box.save(pending, None, lease, count_attempt=False)
    sent, _ = box.drain(client, lease)
    stats = {"sent": stats["sent"] + sent["sent"], "dropped": stats["dropped"] + sent["dropped"], "waiting": sent["waiting"],
             "notices": stats["notices"] + sent["notices"]}
    value = box.attempts.get(box.replies.get(pending["write"], pending["write"]))
    if value is None:
        value = {"outcome": "kept", "failure": "an earlier outbox write is waiting"}
    elif value.get("retry"):
        value = dict(value, outcome="kept")
    if replied or box.replies:
        remarks.append("sent-as-reply")
    return value, stats, remarks


def execute(args, home, api, env=None, client_factory=None):
    h = SimpleNamespace(**api)
    env = os.environ if env is None else env
    session = validate(args, env, h)
    transport, boxes = h.companion("transport"), h.companion("outbox")
    command = args.command
    place = where(args, home, env, h)
    if command == "can-send":
        return scrub([can_send(args, home, env, h, place)], home, env, h)
    allowed = place.allowed
    raw_names = args.project if isinstance(args.project, list) else [args.project]
    names = raw_names or allowed
    if place.source == "environment":
        own = place.own[0] if place.own[1] is not None else None
        if not raw_names and own is None:
            return [outcome(command, "", {"outcome": "refused", "failure": "no project in this checkout"})]
        names = raw_names or [own]
    elif command == "outbox" and not raw_names:
        root = Path(home) / ".corthex" / "hub" / "outbox"
        names = sorted(x.name for x in root.iterdir() if x.is_dir() and h.NAME.fullmatch(x.name)) if root.is_dir() else []
    if any(not isinstance(name, str) or len(name) > 100 or not h.NAME.fullmatch(name) for name in names):
        raise CommandLine("a project name uses lowercase letters, digits and hyphens")
    if not names and command == "push":
        return [outcome(command, "", {"outcome": "refused", "failure": "no project is listed in nexus.push"})]
    request = write_request(args, names[0], home, env, h, place.url) if command in WRITES else None
    asks_checkpoint = request is not None and request[2].get("asks") == "checkpoint"
    reaches = not (command == "outbox" and not args.send)
    remarks = place.remarks if reaches else []
    client, setup_failure = None, None
    if reaches:
        try:
            base = place.url
            if not isinstance(base, str) or not base:
                raise ValueError("no NEXUS address")
            client = (client_factory or transport.Client)(base, env, version=h.VERSION)
        except ValueError:
            setup_failure = "no NEXUS address, or the configured address is invalid"
    rows = []
    for name in names:
        stats = {"sent": 0, "dropped": 0, "waiting": 0}
        if place.source == "environment" and name != place.own[0]:
            failure = ("no project in this checkout" if place.own[1] is None else
                       "not this checkout's project: the checkout holds %s, not %s" % (place.own[0], name))
            rows.append(outcome(command, name, {"outcome": "refused", "failure": failure})); continue
        # In a session's environment every command that reaches the server needs the push list, removal too.
        if reaches and (command != "remove" or place.source == "environment") and name not in allowed:
            rows.append(outcome(command, name, {"outcome": "refused", "failure": "not in " + place.push}, remarks=remarks)); continue
        pending = None
        try:
            box = boxes.Outbox(home, name)
        except (ValueError, OSError):
            value = {"outcome": "failed", "failure": "outbox unavailable"}
            if command in WRITES and request[2].get("look_first") != "stage":
                pending = boxes.new_write(name, request[0], request[1], session, request[2])
                value.update(failure="write lost: outbox could not be written", recovery=pending)
            rows.append(outcome(command, name, value, stats, remarks))
            continue
        if command in WRITES:
            pending = box.make(request[0], request[1], session, request[2])
        project = None
        if command == "push":
            selected = h.select_projects(home, [name])[0]
            if selected[1] is None:
                rows.append(outcome(command, name, {"outcome": "refused", "failure": selected[2]}, remarks=remarks)); continue
            project = selected[1]
            if args.dry_run:
                if setup_failure:
                    rows.append(outcome(command, name, {"outcome": "refused", "failure": setup_failure}, remarks=remarks)); continue
                snapshot = h.make_snapshot(project, h.load_status(home, name), home=home)
                h.save_snapshot(home, snapshot)
                answer = {"bytes": len(h.dump(snapshot, compact=True).encode("utf8")), "summary": snapshot["summary"],
                    "pictures": [{"part": p["part"], "stage": p["stage"]} for p in snapshot["pictures"]], "left_out": snapshot["left_out"],
                    "held_commit": "checked when sent", "first_push": "checked when sent"}
                rows.append(outcome(command, name, {"outcome": "done", "answer": answer}, remarks=remarks)); continue
        kept, extra = None, []
        if command == "todo" or asks_checkpoint:
            reads = session_reads(home, name, boxes)
            kept = last_read(reads, session)
            if command == "todo" and getattr(args, "if_due", False) and not read_due(reads, session, time.time(), boxes):
                # Not due: no server and no outbox (SPEC-191).
                rows.append(outcome(command, name, {"outcome": "done", "read": False, "since": kept}, remarks=remarks)); continue
        value = None
        try:
            with box.lease() as lease:
                if asks_checkpoint and client is not None:
                    value, stats, extra = ask_checkpoint(box, client, lease, home, name, session, pending, kept, boxes, place.url.rstrip("/"))
                elif asks_checkpoint and keepable(pending) is None:
                    # A reply that names its stage as the thing to look at first cannot wait unresolved.
                    value = {"outcome": "failed", "failure": setup_failure}
                if value is None and pending is not None:
                    # Publish the original ID before any send; this command
                    # then uses exactly the same ordered drain as a retry.
                    box.save(pending, {"failure": setup_failure} if setup_failure else None, lease, count_attempt=False)
                if value is None and command != "remove":
                    stats, waiting = box.drain(client, lease, send=client is not None and not (command == "outbox" and not args.send))
                    extra = ["sent-as-reply"] if box.replies else []
                else:
                    waiting = []
                if value is not None:
                    pass
                elif command == "outbox":
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
                    elif problem.get("code") == "project_not_found" and not getattr(args, "first", False):
                        # The server holds no such project, also after a removal: its first push waits for the user's yes.
                        value = {"outcome": "refused", "failure": FIRST_PUSH}
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
                    value = read_todo(client, home, name, session, kept, boxes)
                elif command == "show":
                    kind = {"c": "comments", "p": "proposals", "e": "edits", "k": "checkpoints"}[args.entry[1]]
                    value = client.call("GET", "/api/spaces/" + name + "/" + kind + "/" + args.entry)
                else:
                    value = client.call("POST" if command == "claim" else "DELETE", "/api/spaces/" + name + "/claims/" + args.entry, session=session)
        except boxes.Busy:
            failure = "another hub is sending this project's outbox"
            value = interrupted(box, keepable(pending), value, failure, stats)
        except boxes.Lost:
            failure = "the outbox lock was taken over"
            value = interrupted(box, keepable(pending), value, failure, stats)
        except (OSError, ValueError):
            value = interrupted(box, keepable(pending), value, "outbox cleanup failed" if value is not None else "outbox unavailable", stats)
        # Lease release can itself fail. Publish exactly one outcome only
        # after that cleanup has either completed or been handled above.
        if command == "todo" and "since" not in value:
            value = dict(value, since=kept)
        rows.append(outcome(command, name, value, stats, remarks + extra))
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
                if row["failure"] in NOTES:
                    h.say("  " + NOTES[row["failure"]])
            if row["problem"]:
                h.say("  " + h.one_line(row["problem"].get("code", "refused")) + ": " + h.one_line(row["problem"].get("detail", ""), 300))
            if row["answer"]:
                h.say(json.dumps(row["answer"], ensure_ascii=False, indent=2))
            if row["command"] == "todo":
                h.say("  read: " + ("yes" if row["read"] else "no"))
                if row["since"]:
                    h.say("  since: " + row["since"])
                if row["new"] is not None:
                    h.say("  new: " + json.dumps(row["new"], ensure_ascii=False))
            elif row.get("new") is not None:
                # A checkpoint request held back names what came in since the session's read before.
                h.say("  new: " + json.dumps(row["new"], ensure_ascii=False))
            for remark in row.get("remarks") or ():
                h.say("  " + remark + ": " + REMARKS.get(remark, ""))
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
    existing["push"].add_argument("--first", action="store_true", help="allow the project's first push, after the user's yes for it")
    status = existing["status"]
    for name in ("part", "by", "where", "nexus"):
        status.add_argument("--" + name, default="" if name == "part" else None)
    status.add_argument("--repository", action="store_true")
    sendable = commands.add_parser("can-send", help="say whether this session can send for a project, without contacting the server")
    sendable.add_argument("project")
    sendable.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
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
            parser.add_argument("--look-first", help="with --asks checkpoint: an item's trace ID, an https address, or the word stage for the stage's page")
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
        if name == "todo":
            parser.add_argument("--if-due", action="store_true", help="read only when the session's last read is more than a day old")
        if name == "outbox":
            parser.add_argument("--send", action="store_true")
