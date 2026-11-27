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
         b'    """The files that a stage\'s source selects, as snapshot02\'s source_files reads them, for the translation rule."""\n'
         b'\n'
         b'    def __init__(self, root, base, extensions, h):\n'
         b'        self.root, self.base, self.extensions, self.h = root, base, extensions, h\n'
         b'\n'
         b'    def __contains__(self, rel):\n'
         b'        rel = PurePosixPath(rel)\n'
         b'        name = rel.as_posix()\n'
         b'        if self.base and name != self.base and not name.startswith(self.base + "/") or rel.suffix.lower() not in self.extensions:\n'
         b'            return False\n'
         b'        path = self.root.joinpath(*rel.parts)\n'
         b'        return path.is_file() and not self.h.secret_path(path, self.root)\n'
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
         b'    original = h.original_of(PurePosixPath(path), Beside(root, base, pictures.EXTENSIONS[stage], h))\n'
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
        (b"    # NEXUS v3: status builds a checkpoint's link offline from this device's record of the server.\n"
         b'    h.companion("records").remember_server(home, url, formats.choose(answer) == formats.NEW, h)\n',
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
        (b'                        if held["outcome"] == "done":\n'
         b'                            formats = h.companion("snapshot03")\n'
         b"                            # NEXUS v3: status builds a checkpoint's link offline from this device's record of the server.\n"
         b'                            h.companion("records").remember_server(home, place.url, formats.choose(held.get("answer")) == formats.NEW, h)\n'
         b'                        snapshot =h.make_snapshot(project, h.load_status(home, name), home=home,\n',
         b'                        snapshot = h.make_snapshot(project, h.load_status(home, name), home=home,\n'),
        (b'                    todo = value.get("answer") if value.get("outcome") == "done" else None\n'
         b'                    if isinstance(todo, dict) and "read_at" in todo:\n'
         b"                        # NEXUS v3's to-do always has steps and v2's never has; status builds its links from this record.\n"
         b'                        h.companion("records").remember_server(home, place.url, "steps" in todo, h)\n',
         b''),
        (b'            parser.add_argument("--source-path", help="with --source-file outside the project\'s checkout: the file\'s path in the repository")\n',
         b''),
    ),
    'records.py': (
        (b'import sys\n',
         b''),
        (b'from urllib.parse import quote, urlsplit\n'
         b'\n'
         b'CHECKPOINT = r"nk_[0-9a-hjkmnp-tv-z]{12}"\n'
         b'NO_LINK = ("%s %s: checkpoint %s is recorded without its link, because no server command on this device has read the "\n'
         b'           "NEXUS server at %s yet; pass --where with the checkpoint\'s https link, or run todo once against that server")\n'
         b'\n'
         b'\n'
         b'def server_url(url):\n'
         b'    """A NEXUS address as the hub\'s record of servers names it: lowercase scheme and host, no trailing /, or None."""\n'
         b'    parts = urlsplit(url.strip()) if isinstance(url, str) else None\n'
         b'    if parts is None or not parts.scheme or not parts.netloc:\n'
         b'        return None\n'
         b'    return parts.scheme.lower() + "://" + parts.netloc.lower() + parts.path.rstrip("/")\n'
         b'\n'
         b'\n'
         b'def server_file(home, url, h):\n'
         b'    folder = h.hub_dir(Path(home)) / "servers"\n'
         b'    path = folder / (hashlib.sha256(url.encode("utf8")).hexdigest()[:32] + ".json")\n'
         b'    return None if folder.is_symlink() or path.is_symlink() else path\n'
         b'\n'
         b'\n'
         b'def remember_server(home, url, v3, h):\n'
         b'    """Keep what a server command read of the NEXUS server at url: whether it is v3, and when. No token, no project data.\n'
         b'\n'
         b"    push and push --job read it from the held commit's formats (API-243); todo, whose answer has no formats, from\n"
         b"    the steps that v3's to-do always has and v2's never has. A failed write is ignored: the command's own work stands.\n"
         b'    """\n'
         b'    url = server_url(url)\n'
         b'    try:\n'
         b'        path = server_file(home, url, h) if url else None\n'
         b'        if path is not None:\n'
         b'            h.companion("outbox").atomic(path, {"format": 1, "url": url, "v3": v3 is True, "read": h.now_text()})\n'
         b'    except OSError:\n'
         b'        pass\n'
         b'\n'
         b'\n'
         b'def known_server(home, url, h):\n'
         b'    """True for NEXUS v3, False for an older server, None without a record of the server at url on this device."""\n'
         b'    url = server_url(url)\n'
         b'    path = server_file(home, url, h) if url else None\n'
         b'    try:\n'
         b'        data = json.loads(path.read_text(encoding="utf8")) if path is not None and path.is_file() else None\n'
         b'    except (OSError, ValueError):\n'
         b'        return None\n'
         b'    if not isinstance(data, dict) or data.get("url") != url or type(data.get("v3")) is not bool:\n'
         b'        return None\n'
         b'    return data["v3"]\n'
         b'\n'
         b'\n'
         b'def checkpoint_link(project, part, stage, checkpoint, home, h):\n'
         b'    """The link of a checkpoint passed in NEXUS, for status --nexus without --where, made offline.\n'
         b'\n'
         b"    status contacts no server. The link follows the last read of the profile's nexus.url by push, push --job or\n"
         b"    todo: NEXUS v3 shows a stage at /p/<project>/<part or _>/<stage> (its sitemap's SCR-145), and an older server\n"
         b"    keeps v2's overview link as it was. Without a record of that server, there is no link (None).\n"
         b'    """\n'
         b'    profile = h.profile_of(home)\n'
         b'    config = profile.get("nexus") if isinstance(profile.get("nexus"), dict) else {}\n'
         b'    base = config.get("url")\n'
         b'    if not isinstance(base, str) or not base.strip():\n'
         b'        raise ValueError("set nexus.url or --where for the checkpoint\'s link")\n'
         b'    v3 = known_server(home, base, h)\n'
         b'    if v3 is None:\n'
         b'        sys.stderr.write(NO_LINK % (project.name, stage, checkpoint, base.rstrip("/")) + "\\n")\n'
         b'        return None\n'
         b'    place = quote(project.name, safe="") + "/" + quote(part or "_", safe="") + "/" + stage\n'
         b'    return base.rstrip("/") + ("/p/" + place if v3 else "/overview/" + place + "#" + checkpoint)\n',
         b'from urllib.parse import quote\n'),
        (b'    def link(nexus):\n'
         b"        # NEXUS v3: the link follows this device's last read of the server; status itself contacts none.\n"
         b'        return checkpoint_link(project, part, args.stage, nexus, home, h)\n'
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
         b'            # A checkpoint passed in NEXUS without --where: its link, when this device knows the server, comes last.\n'
         b'            where = link(nexus) if link is not None else None\n'
         b'            if where is not None:\n'
         b'                if not safe_link(where, h, home):\n'
         b'                    raise ValueError("--where must be an HTTPS link without secrets or email addresses")\n'
         b'                checkpoints[-1] = {"approved": checkpoint["approved"], "by": by, "nexus": nexus, "where": where, "date": args.date}\n',
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
