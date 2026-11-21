"""Normalize only the reviewed v2 opt-in wiring for the legacy CLI audit."""

REVIEWED_V2 = {
    "hub.py": (
        (b'"outbox", "commands", "ci", "publication_v2"}:', b'"outbox", "commands", "ci"}:'),
        (b'    companion("publication_v2").configure(commands)\n', b''),
        (b'        if args.command in ("preview-v2", "publish-v2"):\n'
         b'            return companion("publication_v2").main(args, home, SimpleNamespace(**globals()))\n', b''),
    ),
    "commands.py": (
        (b'for key in (*TOKEN, "CORTHEX_NEXUS_PUBLISHER_TOKEN"):', b'for key in ("CORTHEX_NEXUS_CLIENT_ID", "CORTHEX_NEXUS_CLIENT_SECRET"):'),
    ),
    "transport.py": (
        (b'version="0.5.0", timeout=30, publisher=None):', b'version="0.5.0", timeout=30):'),
        (b'        if publisher is not None and (parsed.scheme != "https" or parsed.path not in ("", "/")):\n'
         b'            raise ValueError("v2 publication requires the configured HTTPS origin")\n'
         b'        self._publisher = publisher\n', b''),
        (b'        if self._publisher and not path.startswith("/api/v2/projects/"):\n'
         b'            raise ValueError("publisher credentials require a project-scoped v2 route")\n'
         b'        if not self._publisher and not self.local and not all(self._token):\n',
         b'        if not self.local and not all(self._token):\n'),
        (b'        if self._publisher:\n'
         b'            request.add_header("Authorization", "Bearer " + self._publisher)\n'
         b'        elif all(self._token):\n', b'        if all(self._token):\n'),
    ),
}
