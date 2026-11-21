"""Reviewed 0.5.0 additions, normalized before the retained 0.4.0 CLI audit.

The differences cover hub dispatch/parser/version, the transport version and
initializing a native guard under its lock. The CI helper and
its stdin/redaction/PR tests are additive. The original runtime-pin hashes
still cover the network payloads, snapshot fields and push JSON receipts.
"""

REVIEWED_050 = {'hub.py': ((b'#!/usr/bin/env python3\n"""CORTHEX hub: one page with the stages, checks and trace links of e'
             b'very project.\n\nThe 20 commands have --help. Snapshot/build/status work locally. Explicit'
             b'\nserver commands use only the configured NEXUS address and permitted projects.\nIt reads prof'
             b'ile/registration/project settings and stage sources; pictures and\nrepository records come fr'
             b'om the fetched default commit. Generated files and\n',
             b'#!/usr/bin/env python3\n"""CORTHEX hub: one page with the stages, checks and trace links of e'
             b'very project.\n\nThe 19 commands have --help. Snapshot/build/status work locally. Explicit'
             b'\nserver commands use only the configured NEXUS address and permitted projects.\nIt reads prof'
             b'ile/registration/project settings and stage sources; pictures and\nrepository records come fr'
             b'om the fetched default commit. Generated files and\n'),
            (b'from pathlib import Path\nfrom types import SimpleNamespace\n\nVERSION = "0.5.0"\nSCHEMA = "'
             b'corthex-hub/0.2"\nPAGE_SCHEMA = "corthex-hub-page/0.2"\nTEMPLATE = Path(__file__).resolve().pa'
             b'rent.parent / "assets" / "hub.html"\n',
             b'from pathlib import Path\nfrom types import SimpleNamespace\n\nVERSION = "0.4.0"\nSCHEMA = "'
             b'corthex-hub/0.2"\nPAGE_SCHEMA = "corthex-hub-page/0.2"\nTEMPLATE = Path(__file__).resolve().pa'
             b'rent.parent / "assets" / "hub.html"\n'),
            (b'_COMPANIONS = {}\n\ndef companion(name):\n    if name not in {"snapshot02", "domain", "erd"'
             b', "sitemap", "records", "transport", "outbox", "commands", "ci"}:\n        raise ValueError("'
             b'unknown hub companion")\n    if name not in _COMPANIONS:\n        path = Path(__file__).resolv'
             b'e().with_name(name + ".py")\n',
             b'_COMPANIONS = {}\n\ndef companion(name):\n    if name not in {"snapshot02", "domain", "erd"'
             b', "sitemap", "records", "transport", "outbox", "commands"}:\n        raise ValueError("unknow'
             b'n hub companion")\n    if name not in _COMPANIONS:\n        path = Path(__file__).resolve().wi'
             b'th_name(name + ".py")\n'),
            (b'    drop.add_argument("--url", help="the server address (default: CORTHEX_NEXUS_URL, then ne'
             b'xus.url in the profile)")\n    drop.add_argument("--dry-run", action="store_true", help="the '
             b'same: remove never sends a removal")\n    companion("commands").configure(top, commands, {"sn'
             b'apshot":snap, "status":stat, "build":build, "push":send_cmd, "remove":drop}, None)\n    compa'
             b'nion("ci").configure(commands)\n    return top\n\n\n',
             b'    drop.add_argument("--url", help="the server address (default: CORTHEX_NEXUS_URL, then ne'
             b'xus.url in the profile)")\n    drop.add_argument("--dry-run", action="store_true", help="the '
             b'same: remove never sends a removal")\n    companion("commands").configure(top, commands, {"sn'
             b'apshot":snap, "status":stat, "build":build, "push":send_cmd, "remove":drop}, None)\n    retur'
             b'n top\n\n\n'),
            (b'    home = Path(args.home).expanduser().resolve() if args.home else Path.home()\n    commands'
             b' = {"snapshot": run_snapshot, "status": run_status, "build": run_build, "push": run_push, "r'
             b'emove": run_remove}\n    try:\n        if args.command == "setup-ci":\n            return c'
             b'ompanion("ci").main(args, home, SimpleNamespace(**globals()))\n        if args.command in com'
             b'panion("commands").ANSWERED:\n            helper = SimpleNamespace(**globals())\n            r'
             b'ows = companion("commands").execute(args, home, globals())\n            result = companion("c'
             b'ommands").emit(args, rows, helper)\n            companion("ci").after_first(args, home, rows,'
             b' helper)\n            return result\n        return commands[args.command](args, home)\n   '
             b' except companion("commands").CommandLine as error:\n        command_parser.error(str(error))'
             b'\n',
             b'    home = Path(args.home).expanduser().resolve() if args.home else Path.home()\n    commands'
             b' = {"snapshot": run_snapshot, "status": run_status, "build": run_build, "push": run_push, "r'
             b'emove": run_remove}\n    try:\n        if args.command in companion("commands").ANSWERED:\n'
             b'            helper = SimpleNamespace(**globals())\n            return companion("commands").e'
             b'mit(args, companion("commands").execute(args, home, globals()), helper)\n        return comma'
             b'nds[args.command](args, home)\n    except companion("commands").CommandLine as error:\n       '
             b' command_parser.error(str(error))\n')),
 'transport.py': ((b'\n\nclass Client:\n    def __init__(self, base, env, version="0.5.0", timeout=30):\n    '
                   b'    parsed = urllib.parse.urlsplit(base)\n        local = parsed.hostname in ("localh'
                   b'ost", "127.0.0.1", "::1")\n        if (parsed.scheme not in ("https", "http") or not '
                   b'parsed.hostname or\n',
                   b'\n\nclass Client:\n    def __init__(self, base, env, version="0.4.0", timeout=30):\n    '
                   b'    parsed = urllib.parse.urlsplit(base)\n        local = parsed.hostname in ("localh'
                   b'ost", "127.0.0.1", "::1")\n        if (parsed.scheme not in ("https", "http") or not '
                   b'parsed.hostname or\n'),),
 'outbox.py': ((
     b'def guard(path):\n'
     b'    with guard_file(path) as handle:\n'
     b'        handle.seek(0)\n',
     b'def guard(path):\n'
     b'    with guard_file(path) as handle:\n'
     b'        handle.seek(0, 2)\n'
     b'        if not handle.tell():\n'
     b'            handle.write(b"\\0")\n'
     b'            handle.flush()\n'
     b'        handle.seek(0)\n'), (
     b'        try:\n'
     b'            # Windows can lock a byte past EOF. Initialize the guard only\n'
     b'            # while holding that lock so two new hubs cannot race the write.\n'
     b'            if os.fstat(handle.fileno()).st_size == 0:\n'
     b'                handle.write(b"\\0")\n'
     b'                handle.flush()\n'
     b'            yield\n'
     b'        finally:\n'
     b'            handle.seek(0)\n',
     b'        try:\n'
     b'            yield\n'
     b'        finally:\n'
     b'            handle.seek(0)\n'),),
}
