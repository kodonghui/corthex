"""Normalize only the reviewed 0.6.0 changes, before the 0.5.1 and older layers.

0.6.0 adds the corthex-hub/0.3 snapshot (TASK-428 to TASK-430 of NEXUS v3): make_snapshot takes the
format and its budget, fit takes the budget, the snapshot command takes --format, a saved 0.3 snapshot
is read back, snapshot02 calls snapshot03 for a 0.3 snapshot and names the key of a picture it leaves
out, the two push paths choose the format from the held-commit answer and the push job sends a commit
held in an older format again, and the version fields move from 0.5.1 to 0.6.0. The new snapshot03.py
is not a pinned runtime file. These pairs run first, so the later layers meet the 0.5.1 bytes that
they were made for. They are made from the whole diff against the 0.5.1 runtime.
"""

REVIEWED_060 = {
    'hub.py': (
        (b'VERSION = "0.6.0"\n',
         b'VERSION = "0.5.1"\n'),
        (b'    if name not in {"snapshot02", "snapshot03", "domain", "erd", "sitemap", "records", "transport", "outbox", "commands", "ci", "publication_v2"}:\n',
         b'    if name not in {"snapshot02", "domain", "erd", "sitemap", "records", "transport", "outbox", "commands", "ci", "publication_v2"}:\n'),
        (b'def make_snapshot(project, status=None, now=None, home=None, schema=SCHEMA):\n'
         b'    """The snapshot of one project: settings, repositories, stages, items and checks, in 0.2 or in 0.3 (snapshot03)."""\n',
         b'def make_snapshot(project, status=None, now=None, home=None):\n'
         b'    """The snapshot of one project: settings, repositories, stages, items and checks."""\n'),
        (b'        "schema": schema,\n',
         b'        "schema": SCHEMA,\n'),
        (b'    # 0.6.0: corthex-hub/0.3 adds the sources of stages 03, 08 and 09 and has a larger budget (snapshot03).\n'
         b'    limit = companion("snapshot03").budget(schema, MAX_SNAPSHOT_BYTES)\n'
         b'    snapshot = companion("snapshot02").augment(snapshot, project, home, dict(globals(), MAX_SNAPSHOT_BYTES=limit), parse_picture)\n'
         b'    return fit(snapshot, limit)\n',
         b'    snapshot = companion("snapshot02").augment(snapshot, project, home, globals(), parse_picture)\n'
         b'    return fit(snapshot)\n'),
        (b'def fit(snapshot, limit=None):\n',
         b'def fit(snapshot):\n'),
        (b'    limit = MAX_SNAPSHOT_BYTES if limit is None else limit\n',
         b''),
        (b'        if len(dump(result, compact=True).encode("utf-8")) <= limit:\n',
         b'        if len(dump(result, compact=True).encode("utf-8")) <= MAX_SNAPSHOT_BYTES:\n'),
        (b'        if data and data.get("schema") in ("corthex-hub/0.1", SCHEMA, "corthex-hub/0.3") and isinstance(data.get("project"), dict):\n',
         b'        if data and data.get("schema") in ("corthex-hub/0.1", SCHEMA) and isinstance(data.get("project"), dict):\n'),
        (b'        snapshot = make_snapshot(project, load_status(home, project.name), home=home, schema=args.format)\n',
         b'        snapshot = make_snapshot(project, load_status(home, project.name), home=home)\n'),
        (b'    snap.add_argument("--format", choices=(SCHEMA, "corthex-hub/0.3"), default=SCHEMA,\n'
         b'                      help="the snapshot format (default: %(default)s); a push picks it from the server\'s answer")\n',
         b''),
    ),
    'commands.py': (
        (b'    answer = held.get("answer") or {}\n'
         b'    # 0.6.0: the newest format that the server lists; a commit held in an older one goes again once (API-243).\n'
         b'    formats = h.companion("snapshot03")\n'
         b'    snapshot = h.make_snapshot(project, h.load_status(home, own), home=home, schema=formats.choose(answer))\n',
         b'    snapshot = h.make_snapshot(project, h.load_status(home, own), home=home)\n'),
        (b'    h.save_snapshot(home, snapshot)\n'
         b'    current = answer.get("default_commit")\n',
         b'    h.save_snapshot(home, snapshot)\n'
         b'    answer = held.get("answer") or {}\n'
         b'    current = answer.get("default_commit")\n'),
        (b'            (incoming == current and not formats.completes(answer, snapshot["schema"]) or\n'
         b'             incoming != current and h.git(project.root, "cat-file", "-t", current) == "commit" and\n',
         b'            (incoming == current or h.git(project.root, "cat-file", "-t", current) == "commit" and\n'),
        (b'                        # 0.6.0: the newest format that the server lists; a first push has no answer to read, so 0.2.\n'
         b'                        snapshot = h.make_snapshot(project, h.load_status(home, name), home=home,\n'
         b'                                                   schema=h.companion("snapshot03").choose(held.get("answer")))\n',
         b'                        snapshot = h.make_snapshot(project, h.load_status(home, name), home=home)\n'),
    ),
    'snapshot02.py': (
        (b'        if snapshot["schema"] != "corthex-hub/0.2":\n'
         b'            # 0.6.0: corthex-hub/0.3 adds the sources of stages 03, 08 and 09, one picture per file (snapshot03).\n'
         b'            h.companion("snapshot03").pictures(snapshot, project, parts, tree, default, checks, h, home)\n',
         b''),
        (b'        if "key" in biggest:\n'
         b'            omission["key"] = biggest["key"]\n',
         b''),
        (b'        snapshot["checks"].append(h.check("picture-left-out", "warn", "a whole picture is left out to keep the snapshot under its size limit", stage=biggest["stage"], args=omission))\n',
         b'        snapshot["checks"].append(h.check("picture-left-out", "warn", "a whole picture is left out to keep the snapshot under 1 MB", stage=biggest["stage"], args=omission))\n'),
    ),
    'transport.py': (
        (b'    def __init__(self, base, env, version="0.6.0", timeout=30, publisher=None):\n',
         b'    def __init__(self, base, env, version="0.5.1", timeout=30, publisher=None):\n'),
    ),
}
