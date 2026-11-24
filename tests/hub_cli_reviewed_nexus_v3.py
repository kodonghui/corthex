"""Normalize only the reviewed NEXUS v3 changes of 0.6.0, before the rest of 0.6.0 and the older layers.

Three changes for NEXUS v3, made before 0.6.0 is published. status --nexus without --where reads the
held commit (API-243) once, from the profile's nexus.url, for a project in nexus.push, and records v3's
stage address, /p/<project>/<part or _>/<stage>, when the answer lists corthex-hub/0.3, or v2's overview
link as before; an answer it cannot read writes nothing (records.py). propose sends source_path with
source_text (API-256): the repository path of --source-file in the checkout, or --source-path for a file
outside it, checked against the stage's source, part, extensions and translations first (commands.py).
snapshot02.py names the extensions each picture stage reads, which propose also checks. These pairs run
first, so the 0.6.0 layer meets the bytes it was made for. They are made from the whole diff against them.
"""

REVIEWED_NEXUS_V3 = {
    'commands.py': (
        (b'from pathlib import Path, PurePosixPath\n',
         b'from pathlib import Path\n'),
        (b'# NEXUS v3 (API-256): source_text comes with source_path, the repository path of the file that it is the whole\n'
         b'# proposed text of, as the picture names its files. The hub checks the path before it sends or keeps anything.\n'
         b'SOURCE_PATH_CHARS = 300\n',
         b''),
        (b'def checkout_path(file, root):\n'
         b'    """The repository path, with / on every platform, of a resolved file in the resolved checkout root; None outside it."""\n'
         b'    try:\n'
         b'        parts = file.relative_to(root).parts\n'
         b'    except ValueError:\n'
         b'        return None\n'
         b'    return "/".join(parts) or None\n'
         b'\n'
         b'\n'
         b'def repository_path(value):\n'
         b'    """--source-path as a repository path: / for \\\\ on every platform, relative, plain and 1 to 300 characters."""\n'
         b'    path = value.replace("\\\\", "/")\n'
         b'    if not path or len(path) > SOURCE_PATH_CHARS:\n'
         b'        raise CommandLine("--source-path needs a repository path of 1 to 300 characters")\n'
         b'    if any(ord(c) < 32 or ord(c) == 127 for c in path):\n'
         b'        raise CommandLine("--source-path must not hold control characters")\n'
         b'    if path.startswith("/") or re.match(r"[A-Za-z]:", path):\n'
         b'        raise CommandLine("--source-path is relative to the repository\'s root, with no leading / and no drive letter")\n'
         b'    if any(piece in ("", ".", "..") for piece in path.split("/")):\n'
         b'        raise CommandLine("--source-path must not hold empty, . or .. segments")\n'
         b'    return path\n'
         b'\n'
         b'\n'
         b'class Beside:\n'
         b'    """The files of a checkout, for the hub\'s rule that a translation beside its original is not a source."""\n'
         b'\n'
         b'    def __init__(self, root):\n'
         b'        self.root = root\n'
         b'\n'
         b'    def __contains__(self, rel):\n'
         b'        return self.root.joinpath(*PurePosixPath(rel).parts).is_file()\n'
         b'\n'
         b'\n'
         b'def source_path(args, project, h):\n'
         b'    """API-256\'s source_path for --source-file, checked as the stage\'s picture reads its files (snapshot02).\n'
         b'\n'
         b"    The path is --source-file's in the project's checkout, or --source-path for a file outside it. It must be under\n"
         b"    the stage's source in the project's settings, belong to the command's part, end in an extension that the\n"
         b'    stage reads and not be a translation beside its original. A failure is a wrong command line: nothing is sent or kept.\n'
         b'    """\n'
         b'    if project is None:\n'
         b'        raise CommandLine("--source-file needs the project\'s checkout on this device, to check the file\'s path")\n'
         b'    given = repository_path(args.source_path) if args.source_path is not None else None\n'
         b'    root = h.plain_path(Path(project.root).resolve())\n'
         b'    found = None if args.source_file == "-" else checkout_path(h.plain_path(Path(args.source_file).resolve()), root)\n'
         b'    if found is not None and given is not None and found != given:\n'
         b'        raise CommandLine("--source-path names %s, but --source-file is %s in the project\'s checkout: leave out --source-path, "\n'
         b'                          "or name the same path" % (given, found))\n'
         b'    path = found or given\n'
         b'    if path is None:\n'
         b'        raise CommandLine("--source-file is outside the project\'s checkout: add --source-path with the file\'s path in the "\n'
         b'                          "repository, such as db/schema.sql")\n'
         b'    if len(path) > SOURCE_PATH_CHARS:\n'
         b'        raise CommandLine("the file\'s repository path has more than 300 characters, more than NEXUS takes")\n'
         b'    stage, pictures = args.stage, h.companion("snapshot02")\n'
         b'    stages = project.settings.get("stages")\n'
         b'    entry = stages.get(stage) if isinstance(stages, dict) else None\n'
         b'    source = entry.get("source") if isinstance(entry, dict) else next(row[2] for row in h.STAGES if row[0] == stage)\n'
         b'    if isinstance(entry, dict) and entry.get("skip") is True:\n'
         b'        raise CommandLine("%s is skipped in the project\'s settings, so NEXUS has no picture of it" % stage)\n'
         b'    if not isinstance(source, str) or not source:\n'
         b'        raise CommandLine("%s has no source in the project\'s settings, so NEXUS has no picture of it" % stage)\n'
         b'    alias, folder = h.split_source(source)\n'
         b'    if alias != ".":\n'
         b'        raise CommandLine("%s\'s source is in another repository, which the hub does not send, so NEXUS has no picture of it" % stage)\n'
         b'    if h.is_absolute(folder) or "\\\\" in folder or ".." in PurePosixPath(folder).parts:\n'
         b'        raise CommandLine("%s\'s source in the project\'s settings is not a path in the repository" % stage)\n'
         b'    base = folder.rstrip("/")\n'
         b'    base = "" if base == "." else base\n'
         b'    if base and path != base and not path.startswith(base + "/"):\n'
         b'        raise CommandLine("%s is not under %s\'s source in the project\'s settings, %s" % (path, stage, source))\n'
         b'    if PurePosixPath(path).suffix.lower() not in pictures.EXTENSIONS[stage]:\n'
         b'        raise CommandLine("%s is not a file that %s\'s picture reads, which ends in %s" %\n'
         b'                          (path, stage, " or ".join(sorted(pictures.EXTENSIONS[stage]))))\n'
         b'    if h.secret_path(root.joinpath(*PurePosixPath(path).parts), root):\n'
         b'        raise CommandLine("%s has a name that looks like a secret\'s, so the picture never reads it and the hub does not send it" % path)\n'
         b'    original =h.original_of(PurePosixPath(path), Beside(root))\n'
         b'    if original is not None:\n'
         b'        raise CommandLine("%s is a translation of %s, which the picture reads instead: propose on the original" %\n'
         b'                          (path, original.as_posix()))\n'
         b'    part, wanted = pictures.part_of(path, folder, pictures.parts_of(project.settings, [], h)), args.part or ""\n'
         b'    if part != wanted:\n'
         b'        raise CommandLine("%s belongs to %s, not to %s" % (path, "the part " + part if part else "no part",\n'
         b'                                                           "--part " + wanted if wanted else "the project as a whole: add --part " + part))\n'
         b'    return path\n'
         b'\n'
         b'\n',
         b''),
        (b'def write_request(args, project, home, env, h, url=None, checkout=None):\n',
         b'def write_request(args, project, home, env, h, url=None):\n'),
        (b'            body["source_path"] = source_path(args, checkout, h)\n'
         b'        elif args.source_path is not None:\n'
         b'            raise CommandLine("--source-path goes only with --source-file")\n',
         b''),
        (b'def project_checkout(name, home, h, place):\n'
         b'    """(the project\'s checkout on this device or None, why not), from the list of projects or the current folder."""\n'
         b'    if place.source == "environment":\n'
         b'        own, project, _ = place.own\n'
         b'        if project is None or name != own:\n'
         b'            return None, "no project in this checkout" if project is None else "not this checkout\'s project: the checkout holds %s, not %s" % (own, name)\n'
         b'        return project, None\n'
         b'    _, project, failure = h.select_projects(home, [name])[0]\n'
         b'    if project is None:\n'
         b'        here = h.select_projects(home, [], None)[0]\n'
         b'        project = here[1] if here[0] == name else None\n'
         b'    return project, failure\n'
         b'\n'
         b'\n',
         b''),
        (b'    project, failure = project_checkout(name, home, h, place)\n'
         b'    if project is None:\n'
         b'        return outcome("can-send", name, {"outcome": "refused", "failure": failure})\n',
         b'    if place.source == "environment":\n'
         b'        own, project, _ = place.own\n'
         b'        if project is None or name != own:\n'
         b'            failure = "no project in this checkout" if project is None else "not this checkout\'s project: the checkout holds %s, not %s" % (own, name)\n'
         b'            return outcome("can-send", name, {"outcome": "refused", "failure": failure})\n'
         b'    else:\n'
         b'        _, project, failure = h.select_projects(home, [name])[0]\n'
         b'        if project is None:\n'
         b'            here = h.select_projects(home, [], None)[0]\n'
         b'            project = here[1] if here[0] == name else None\n'
         b'        if project is None:\n'
         b'            return outcome("can-send", name, {"outcome": "refused", "failure": failure})\n'),
        (b"    # NEXUS v3: a proposal's source path is checked against the project's checkout and settings before anything goes.\n"
         b'    checkout = None\n'
         b'    if command == "propose" and args.source_file:\n'
         b'        checkout, reason = project_checkout(names[0], home, h, place)\n'
         b'        if checkout is None:\n'
         b'            raise CommandLine("--source-file needs the project\'s checkout on this device, to check the file\'s path: " + reason)\n'
         b'    request = write_request(args, names[0], home, env, h, place.url, checkout) if command in WRITES else None\n',
         b'    request = write_request(args, names[0], home, env, h, place.url) if command in WRITES else None\n'),
        (b'            parser.add_argument("--source-path", help="with --source-file outside the project\'s checkout: the file\'s path in the repository")\n',
         b''),
    ),
    'records.py': (
        (b'\n'
         b'CHECKPOINT = r"nk_[0-9a-hjkmnp-tv-z]{12}"\n'
         b"# NEXUS v3: status reads the held commit only to build a checkpoint's link, so it waits at most this long.\n"
         b'HELD_SECONDS = 10\n'
         b'UNREAD = ("could not read the NEXUS server\'s held commit to tell NEXUS v3 from v2 (%s), so nothing was written; "\n'
         b'          "pass --where with the checkpoint\'s https link")\n'
         b'\n'
         b'\n'
         b'def checkpoint_link(project, part, stage, checkpoint, home, h, env=None, client_factory=None):\n'
         b'    """The link of a checkpoint passed in NEXUS, for status --nexus without --where.\n'
         b'\n'
         b'    The held-commit answer (API-243) tells the two servers apart, as it does for push: a server that lists\n'
         b'    corthex-hub/0.3 in formats is NEXUS v3, which shows a stage at /p/<project>/<part or _>/<stage> (its\n'
         b"    sitemap's SCR-145); any other answer, and a bare 404 from a server older than the held commit, keeps v2's\n"
         b"    overview link as it was. This is the only request that status makes: one GET to the profile's nexus.url, for a\n"
         b'    project in nexus.push, with the token from the environment as push sends it. When the answer cannot be read,\n'
         b'    status writes nothing.\n'
         b'    """\n'
         b'    env = os.environ if env is None else env\n'
         b'    profile = h.profile_of(home)\n'
         b'    config = profile.get("nexus") if isinstance(profile.get("nexus"), dict) else {}\n'
         b'    base = config.get("url")\n'
         b'    if not isinstance(base, str) or not base.strip():\n'
         b'        raise ValueError("set nexus.url or --where for the checkpoint\'s link")\n'
         b'    listed = config.get("push") if isinstance(config.get("push"), list) else []\n'
         b'    if project.name not in listed:\n'
         b'        raise ValueError(UNREAD % "the project is not in nexus.push")\n'
         b'    try:\n'
         b'        client = (client_factory or h.companion("transport").Client)(base, env, version=h.VERSION, timeout=HELD_SECONDS)\n'
         b'    except ValueError:\n'
         b'        raise ValueError(UNREAD % "nexus.url is not a valid NEXUS address")\n'
         b'    held = client.call("GET", "/api/snapshots/" + project.name + "/held")\n'
         b'    place = quote(project.name, safe="") + "/" + quote(part or "_", safe="") + "/" + stage\n'
         b'    overview = base.rstrip("/") + "/overview/" + place + "#" + checkpoint\n'
         b'    if held.get("outcome") != "done":\n'
         b'        code = (held.get("problem") or {}).get("code")\n'
         b'        failure = held.get("failure")\n'
         b'        if not code and failure == "HTTP 404":\n'
         b'            # A server without the held commit is older still, as push reads it ("needs the 0.2 release"): not v3.\n'
         b'            return overview\n'
         b'        code = code if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,59}", code) else None\n'
         b'        reason = ("the server holds no such project" if code == "project_not_found" else\n'
         b'                  "the server answered " + code if code else\n'
         b'                  "no service token: set CORTHEX_NEXUS_CLIENT_ID and CORTHEX_NEXUS_CLIENT_SECRET" if failure == "no service token" else\n'
         b'                  failure if isinstance(failure, str) and failure else "no answer")\n'
         b'        raise ValueError(UNREAD % reason)\n'
         b'    formats = h.companion("snapshot03")\n'
         b'    if formats.choose(held.get("answer")) == formats.NEW:\n'
         b'        return base.rstrip("/") + "/p/" + place\n'
         b'    return overview\n',
         b''),
        (b'def write(project, home, args, api, now=None, client_factory=None):\n',
         b'def write(project, home, args, api, now=None):\n'),
        (b'    def link(nexus):\n'
         b"        # NEXUS v3: the server's held commit says which link to build; update() asks once every local check passed.\n"
         b'        return checkpoint_link(project, part, args.stage, nexus, home, h, client_factory=client_factory)\n'
         b'\n',
         b''),
        (b'            return update(project, home, args, h, target, part, now, link)\n',
         b'            return update(project, home, args, h, target, part, now)\n'),
        (b'def update(project, home, args, h, target, part, now, link=None):\n',
         b'def update(project, home, args, h, target, part, now):\n'),
        (b'                if not re.fullmatch(CHECKPOINT, nexus):\n',
         b'                if not re.fullmatch(r"nk_[0-9a-hjkmnp-tv-z]{12}", nexus):\n'),
        (b'                checkpoint["nexus"] = nexus\n',
         b'                checkpoint["nexus"] = nexus\n'
         b'                if where is None:\n'
         b'                    profile = h.profile_of(home)\n'
         b'                    config = profile.get("nexus") if isinstance(profile.get("nexus"), dict) else {}\n'
         b'                    base = config.get("url")\n'
         b'                    if not isinstance(base, str):\n'
         b'                        raise ValueError("set nexus.url or --where for the checkpoint\'s overview link")\n'
         b'                    where = base.rstrip("/") + "/overview/" + quote(project.name, safe="") + "/" + quote(part or "_", safe="") + "/" + args.stage + "#" + nexus\n'),
        (b'                    ("nexus" in cp and (not isinstance(cp["nexus"], str) or not re.fullmatch(CHECKPOINT, cp["nexus"])))):\n',
         b'                    ("nexus" in cp and (not isinstance(cp["nexus"], str) or not re.fullmatch(r"nk_[0-9a-hjkmnp-tv-z]{12}", cp["nexus"])))):\n'),
        (b'        if approval and nexus and where is None:\n'
         b'            # A checkpoint passed in NEXUS without --where: its link comes from the server, read last, after every local check.\n'
         b'            where = link(nexus) if link is not None else None\n'
         b'            if where is None:\n'
         b'                raise ValueError("set nexus.url or --where for the checkpoint\'s link")\n'
         b'            if not safe_link(where, h, home):\n'
         b'                raise ValueError("--where must be an HTTPS link without secrets or email addresses")\n'
         b'            checkpoints[-1] = {"approved": checkpoint["approved"], "by": by, "nexus": nexus, "where": where, "date": args.date}\n',
         b''),
    ),
    'snapshot02.py': (
        (b"# The extensions of the files that each picture stage reads; propose checks a proposal's source_path by them.\n"
         b'EXTENSIONS = {"01-domain": {".md", ".markdown"}, "05-erd": {".sql"}, "07-sitemap": {".yaml", ".yml"}}\n',
         b''),
        (b'            names = tree.source_files(rel, EXTENSIONS[key])\n',
         b'            names = tree.source_files(rel, {"01-domain": {".md", ".markdown"}, "05-erd": {".sql"}, "07-sitemap": {".yaml", ".yml"}}[key])\n'),
    ),
}
