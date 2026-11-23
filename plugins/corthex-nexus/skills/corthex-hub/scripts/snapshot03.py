"""NEXUS corthex-hub/0.3: the sources of stages 03, 08 and 09, one picture per file.

A 0.3 snapshot is a 0.2 snapshot with three more picture stages. Each user flow, screen definition
and mockup page of the fetched default commit is one picture: its part, its stage, its repository
path as `key` and the file's whole text as `source.text`, which NEXUS parses itself. A translation
beside its original is not sent. The hub sends 0.3 only to a server whose held-commit answer lists
it (API-243), under a larger budget within that server's 8 MiB. Like snapshot02, this reads Git
objects only: no checkout, network, hook, filter or user executable.
"""
import os
import re
from pathlib import Path, PurePosixPath

OLD = "corthex-hub/0.2"
NEW = "corthex-hub/0.3"
# The formats this hub makes, oldest first.
KNOWN = (OLD, NEW)
FORMAT = re.compile(r"corthex-hub/([0-9]{1,3})\.([0-9]{1,3})\Z")
# A v3 server takes a snapshot of up to 8 MiB (8,388,608 bytes); this leaves room for `replaces`.
MAX_SNAPSHOT_BYTES = 8 * 1000 * 1000
# The Snapshot schema's longest source.text and picture key, and its most pictures and left_out entries.
MAX_TEXT_CHARS = 1024 * 1024
MAX_KEY_CHARS = 300
MAX_PICTURES = 1000
MAX_LEFT_OUT = 1000
TEXT_STAGES = ("03-user-flow", "08-screen-states", "09-mockup")
# A file of stage 03 or 08 is a picture when the hub reads it as defining an item of this kind; the hub's
# Markdown extensions (h.MARKDOWN) say which files those are.
DEFINES = {"03-user-flow": "flow", "08-screen-states": "screen"}
PAGES = {".html", ".htm"}


def version(name):
    """(major, minor) of a format name such as corthex-hub/0.3, or None."""
    match = FORMAT.match(name) if isinstance(name, str) else None
    return (int(match.group(1)), int(match.group(2))) if match else None


def budget(schema, old):
    """The compact UTF-8 bytes a snapshot of this format may take; old is 0.2's limit."""
    if schema == OLD:
        return old
    if schema == NEW:
        return MAX_SNAPSHOT_BYTES
    raise ValueError("unknown snapshot format: %s" % schema)


def choose(held):
    """The format to send: the newest that this hub makes and the held-commit answer lists in `formats`.

    A server of before lists none, and a project that the server does not hold has no answer to read, so
    both get 0.2, as does an answer whose formats cannot be read.
    """
    formats = held.get("formats") if isinstance(held, dict) else None
    listed = [name for name in KNOWN if isinstance(formats, list) and name in formats]
    return listed[-1] if listed else OLD


def completes(held, schema):
    """Whether the held commit, sent again in schema, completes its revision: the server holds it in an older format.

    After that send the server names schema as the commit's format, so the same commit goes again only once.
    """
    held_format = version(held.get("format")) if isinstance(held, dict) else None
    wanted = version(schema)
    return schema != OLD and held_format is not None and wanted is not None and held_format < wanted


def reading(key, name, h):
    """The hub's reading of one file of stage 03 or 08, to tell a listing such as a README by its name."""
    return h.Source(key, next(stage[3] for stage in h.STAGES if stage[0] == key), ".", name)


def defines(text, name, key, h):
    """Whether the hub reads the file as defining an item of the stage's kind, with the project's own ID formats:
    a user flow for stage 03, a screen for stage 08."""
    src = reading(key, name, h)
    h.scan_file(h.Scan(h.picture_ids), src, text)
    return any(h.picture_ids.kind(ident) == DEFINES[key] for ident in src.defined)


def leave_out(snapshot, checks, h, part, key, why, message, name=None):
    omission = {"part": part, "stage": key, "why": why}
    if name is not None:
        omission["key"] = name
    if len(snapshot["left_out"]) < MAX_LEFT_OUT:
        snapshot["left_out"].append(omission)
    warning = h.check("picture-left-out", "warn", message, stage=key, args=omission)
    if part:
        warning["part"] = part
    checks.append(warning)


def source_of(key, given, default, h):
    """(the path to read, the extensions of its pictures) of one stage; stage 09 reads the page that `page` names."""
    if key == "09-mockup":
        return (given or {}).get("page"), PAGES
    return (given.get("source") if given is not None else default), h.MARKDOWN


def pictures(snapshot, project, parts, tree, default, checks, h, home=None):
    """Add the pictures of stages 03, 08 and 09 from the default commit's tree to a 0.3 snapshot."""
    scrub = h.companion("commands").scrub
    part_of = h.companion("snapshot02").part_of
    settings = project.settings.get("stages")
    settings = settings if isinstance(settings, dict) else {}
    read = 0  # the UTF-8 bytes of the texts added so far
    for key, _, default_source, _, _ in h.STAGES:
        if key not in TEXT_STAGES:
            continue
        given = settings.get(key) if isinstance(settings.get(key), dict) else None
        if given is not None and given.get("skip") is True:
            continue
        source, extensions = source_of(key, given, default_source, h)
        if source is None:
            continue
        if not isinstance(source, str) or not source.strip():
            if key == "09-mockup":
                checks.append(h.check("mockup-page-invalid", "warn", "page must name an HTML file or a folder of them", stage=key))
            continue
        alias, rel = h.split_source(source.strip())
        if alias != ".":
            for part in parts or [""]:
                leave_out(snapshot, checks, h, part, key, "other-repository", "the picture source is in another repository")
            continue
        if h.is_absolute(rel) or "\\" in rel or ".." in PurePosixPath(rel).parts:
            if key == "09-mockup":
                checks.append(h.check("mockup-page-invalid", "warn", "page must be a relative path with forward slashes", stage=key))
            continue
        names = tree.source_files(rel, extensions)
        if key == "09-mockup" and not names:
            checks.append(h.check("mockup-page-missing", "warn", h.one_line(rel, 200) + ": no HTML page there on the default branch", stage=key))
        if len(names) > h.MAX_FILES:
            checks.append(h.check("picture-partial", "warn", names[h.MAX_FILES] + ":1: first of " +
                str(len(names) - h.MAX_FILES) + " supported sources omitted after " + str(h.MAX_FILES) + " files",
                stage=key, args={"limit": h.MAX_FILES, "omitted": len(names) - h.MAX_FILES}))
        names = names[:h.MAX_FILES]
        for index, name in enumerate(names):
            # The format's most pictures, or the budget: past that the snapshot would leave the pictures out again.
            full = len(snapshot["pictures"]) >= MAX_PICTURES
            if full or read > h.MAX_SNAPSHOT_BYTES:
                rest = len(names) - index
                checks.append(h.check("picture-partial", "warn", name + ":1: first of " + str(rest) + " files not read after the snapshot's " +
                    (str(MAX_PICTURES) + " pictures" if full else "size limit"), stage=key,
                    args={"limit": MAX_PICTURES if full else h.MAX_SNAPSHOT_BYTES, "omitted": rest}))
                break
            if key in DEFINES and reading(key, name, h).listing:
                continue
            part = part_of(name, rel, parts)
            text = tree.read(name)
            if text is None:
                if tree.sizes.get(name, 0) > h.MAX_FILE_BYTES:
                    # SPEC-001: a file over 1 MiB is left out of the snapshot, and counted, as a whole picture left out for size.
                    leave_out(snapshot, checks, h, part, key, "size", h.one_line(name, 200) + ": the file is over 1 MiB",
                              name[:MAX_KEY_CHARS])
                else:
                    checks.append(h.check("picture-partial", "warn", name + ": source object is unreadable", stage=key))
                continue
            if key in DEFINES and not defines(text, name, key, h):
                continue
            if parts and not part:
                checks.append(h.check("part-unknown", "info", name + ": document belongs to no declared part", stage=key))
            # The text is redacted as every other string of the snapshot; that can only lengthen it a little.
            text = scrub(text, home or Path.home(), os.environ, h)
            if len(text) > MAX_TEXT_CHARS or len(name) > MAX_KEY_CHARS:
                leave_out(snapshot, checks, h, part, key, "size", h.one_line(name, 200) + ": the text or its path is over the format's limit",
                          name[:MAX_KEY_CHARS])
                continue
            snapshot["pictures"].append({"part": part, "stage": key, "key": name, "commit": default["commit"],
                                         "time": default["time"], "source": {"text": text}})
            read += len(text.encode("utf-8"))
