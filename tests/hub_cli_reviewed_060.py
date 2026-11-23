"""Normalize only the reviewed 0.6.0 changes, before the 0.5.1 and older layers.

0.6.0 adds the corthex-hub/0.3 snapshot (TASK-428 to TASK-430 of NEXUS v3): make_snapshot takes the
format and its budget, fit takes the budget, the snapshot command takes --format, a saved 0.3 snapshot
is read back, snapshot02 calls snapshot03 for a 0.3 snapshot and names the key of a picture it leaves
out, the two push paths choose the format from the held-commit answer and the push job sends a commit
held in an older format again, and the version fields move from 0.5.1 to 0.6.0. SECRET_TEXT becomes
SecretText, which finds the same matches as the one pattern in time that grows with the text: the
redaction itself. The budget loop measures each picture once and keeps at most 1,000 left_out entries.
The new snapshot03.py is not a pinned runtime file. These pairs run first, so the later layers meet the 0.5.1 bytes that
they were made for. They are made from the whole diff against the 0.5.1 runtime.
"""

REVIEWED_060 = {
    'hub.py': (
        (b'VERSION = "0.6.0"\n',
         b'VERSION = "0.5.1"\n'),
        (b'SECRET_KEYS = (r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{20,}|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"\n'
         b'               r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})|-----BEGIN [A-Z ]*PRIVATE KEY-----")\n'
         b'EMAIL_TEXT = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}"\n'
         b'\n'
         b'\n'
         b'class SecretText:\n'
         b'    """The matches of one pattern, SECRET_KEYS or EMAIL_TEXT, found leftmost first as re.sub finds them.\n'
         b'\n'
         b'    0.6.0: a 0.3 page can hold a long run of the characters an address starts with, such as an encoded image.\n'
         b"    Tried at every place in such a run, the pattern takes time that grows with the square of the run's length.\n"
         b'    An address can start only where its run starts, or where the match before it ended, so `fast` tries it\n'
         b'    there and `pattern` is tried once where a match ended: the same matches, in time that grows with the text.\n'
         b'    """\n'
         b'\n'
         b'    def __init__(self):\n'
         b'        self.pattern = re.compile(SECRET_KEYS + "|" + EMAIL_TEXT)\n'
         b'        self.fast = re.compile(SECRET_KEYS + r"|(?<![A-Za-z0-9._%+-])" + EMAIL_TEXT)\n'
         b'\n'
         b'    def finditer(self, text):\n'
         b'        found = self.fast.search(text)\n'
         b'        while found:\n'
         b'            yield found\n'
         b'            found = self.pattern.match(text, found.end()) or self.fast.search(text, found.end())\n'
         b'\n'
         b'    def search(self, text):\n'
         b'        return self.fast.search(text)\n'
         b'\n'
         b'    def sub(self, replacement, text):\n'
         b'        """text with each match replaced by replacement, which is plain text."""\n'
         b'        parts, last = [], 0\n'
         b'        for found in self.finditer(text):\n'
         b'            parts += [text[last:found.start()], replacement]\n'
         b'            last = found.end()\n'
         b'        return "".join(parts) + text[last:]\n'
         b'\n'
         b'\n'
         b'SECRET_TEXT = SecretText()\n',
         b'SECRET_TEXT = re.compile(\n'
         b'    r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{20,}|(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}"\n'
         b'    r"|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})|-----BEGIN [A-Z ]*PRIVATE KEY-----"\n'
         b'    r"|[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}"\n'
         b')\n'),
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
        (b"    # 0.6.0: a 0.3 snapshot can hold many pictures, so each one's size is measured once and the snapshot's is kept\n"
         b'    # as they go; the second loop checks the exact size, as the only loop did before.\n'
         b'    measure = lambda value: len(h.dump(value, compact=True).encode("utf-8"))\n'
         b'    total = measure(snapshot)\n'
         b'    sizes = {id(picture): measure(picture) for picture in snapshot["pictures"]} if total > h.MAX_SNAPSHOT_BYTES else {}\n'
         b'    while snapshot["pictures"] and total > h.MAX_SNAPSHOT_BYTES:\n'
         b'        biggest = max(snapshot["pictures"], key=lambda p: sizes[id(p)])\n'
         b'        total += drop(snapshot, biggest, h, measure) - sizes[id(biggest)]\n'
         b'    while snapshot["pictures"] and measure(snapshot) > h.MAX_SNAPSHOT_BYTES:\n'
         b'        drop(snapshot, max(snapshot["pictures"], key=measure), h, measure)\n',
         b'    while snapshot["pictures"] and len(h.dump(snapshot, compact=True).encode("utf-8")) > h.MAX_SNAPSHOT_BYTES:\n'
         b'        biggest = max(snapshot["pictures"], key=lambda p: len(h.dump(p, compact=True).encode("utf-8")))\n'
         b'        snapshot["pictures"].remove(biggest)\n'
         b'        omission = {"part": biggest["part"], "stage": biggest["stage"], "why": "size"}\n'
         b'        snapshot["left_out"].append(omission)\n'
         b'        snapshot["checks"].append(h.check("picture-left-out", "warn", "a whole picture is left out to keep the snapshot under 1 MB", stage=biggest["stage"], args=omission))\n'),
        (b'\n'
         b'\n'
         b'def drop(snapshot, biggest, h, measure):\n'
         b'    """Leave a whole picture out for size; the bytes this adds to the compact snapshot, the picture\'s own aside."""\n'
         b'    added = -1 if len(snapshot["pictures"]) > 1 else 0\n'
         b'    snapshot["pictures"].remove(biggest)\n'
         b'    omission = {"part": biggest["part"], "stage": biggest["stage"], "why": "size"}\n'
         b'    if "key" in biggest:\n'
         b'        omission["key"] = biggest["key"]\n'
         b"    # 0.6.0: at most the format's 1,000 entries; an omission past them is named by its check only.\n"
         b'    if len(snapshot["left_out"]) < h.companion("snapshot03").MAX_LEFT_OUT:\n'
         b'        added += measure(omission) + (1 if snapshot["left_out"] else 0)\n'
         b'        snapshot["left_out"].append(omission)\n'
         b'    check = h.check("picture-left-out", "warn", "a whole picture is left out to keep the snapshot under its size limit", stage=biggest["stage"], args=omission)\n'
         b'    added += measure(check) + (1 if snapshot["checks"] else 0)\n'
         b'    snapshot["checks"].append(check)\n'
         b'    return added\n',
         b''),
    ),
    'transport.py': (
        (b'    def __init__(self, base, env, version="0.6.0", timeout=30, publisher=None):\n',
         b'    def __init__(self, base, env, version="0.5.1", timeout=30, publisher=None):\n'),
    ),
}
