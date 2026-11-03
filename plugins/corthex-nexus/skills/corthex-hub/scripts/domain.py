"""Read the English/Korean stage-01 table forms without executing markup."""
import re
import unicodedata

HEADERS = {
    "context": ("context", "컨텍스트"), "type": ("type", "종류"),
    "aggregates": ("aggregates", "애그리거트"),
    "given_by": ("given by", "주는 쪽"), "read_model": ("read model", "읽기 모델"),
    "command": ("command", "명령"), "aggregate": ("aggregate", "애그리거트"),
    "events": ("events", "사건"), "shows": ("shows", "보여 주는 것"),
    "from": ("from", "어디서"), "to": ("to", "어디로"), "kind": ("kind", "종류"),
    "why": ("why", "까닭"), "data": ("data", "오가는 것"),
    "hotspot": ("hotspot", "핫스팟"), "state": ("state", "상태"),
    "answer": ("answer or next step", "답이나 다음 할 일"),
    "id": ("id",), "term": ("term", "용어"), "status": ("status", "상태"),
    "lane": ("lane", "흐름"),
}


def word(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text)).casefold()


def trace_ids(text, h, kind=None):
    return [ident for ident, found, _ in h.picture_ids.find(text) if kind is None or kind == found]


def tables(lines, h):
    index = 0
    fenced = False
    while index < len(lines):
        if re.match(r"^\s*(`{3,}|~{3,})", lines[index]):
            fenced = not fenced
        if fenced or index + 1 >= len(lines) or not h.is_table(lines[index]):
            index += 1
            continue
        divider = h.cells(lines[index + 1])
        if not divider or not all(re.fullmatch(r":?-{3,}:?", x.strip()) for x in divider):
            index += 1
            continue
        header = [h.norm(h.plain(x)) for x in h.cells(lines[index])]
        columns = {key: next((i for i, name in enumerate(header) if name in aliases), None)
                   for key, aliases in HEADERS.items()}
        index += 2
        while index < len(lines) and h.is_table(lines[index]):
            values = h.cells(lines[index])
            yield index + 1, {key: values[col] if col < len(values) else "" for key, col in columns.items() if col is not None}
            index += 1


def partial(checks, h, file, line, why, part):
    row = h.check("picture-partial", "warn", file + ":" + str(line) + ": " + why, stage="01-domain")
    if part:
        row["part"] = part
    checks.append(row)


def parse(documents, checks, h, part):
    picture = {"format": 1, "contexts": [], "aggregates": [], "read_models": [], "dependencies": [], "hotspots": []}
    for file, text in documents:
        text = h.STRUCK.sub(" ", text)
        lines = text.splitlines()
        rows = list(tables(lines, h))
        glossary, removed = {}, set()
        for line, row in rows:
            ids = trace_ids(row.get("id", ""), h)
            if ids and "status" in row and h.is_removed({"status": row["status"]}):
                removed.update(ids)
            if "term" in row:
                for ident in (x for x in ids if h.picture_ids.kind(x) == "term"):
                    glossary.setdefault(word(h.plain(row["term"], 120)), []).append(ident)
        contexts, positions = {}, []
        current, nearest, context_level = None, None, 0
        fenced = False
        for index, line in enumerate(lines, 1):
            if re.match(r"^\s*(`{3,}|~{3,})", line):
                fenced = not fenced
            if fenced:
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)", line)
            if heading:
                lead = h.picture_ids.lead(h.plain(heading.group(2), 300))
                if lead and lead[1] == "context":
                    ident, _, _, name = lead
                    current = contexts.setdefault(ident, {"id": ident, "name": h.plain(name, 120), "type": "", "purpose": "",
                        "removed": ident in removed, "external": "", "rows": [], "where": file + ":" + str(index)})
                    nearest, context_level = current, len(heading.group(1))
                    positions.append((index, current, nearest))
                elif current and len(heading.group(1)) <= context_level:
                    current = None
                    positions.append((index, None, nearest))
            if current:
                purpose = re.match(r"^\s*(?:Purpose|목적)\s*:\s*(.*)", line, re.I)
                external = re.match(r"^\s*[-*]\s*(?:External systems|바깥 시스템)\s*:\s*(.*)", line, re.I)
                if purpose:
                    current["purpose"] = h.plain(purpose.group(1), 300)
                if external:
                    current["external"] = h.plain(external.group(1), 300)
        if not contexts:
            if text.strip():
                partial(checks, h, file, 1, "document has no context heading", part)
            continue
        aggregate_defs = []
        model_defs = []

        def located(line):
            candidates = [(context, previous) for start, context, previous in positions if start <= line]
            return candidates[-1] if candidates else (None, None)

        def add_terms(target, value, context, where):
            # A TERM ID in parentheses belongs to the name before it, not to
            # the next comma-separated aggregate.
            for name in re.split(r"\s*,\s*|\s*<br\s*/?>\s*", value):
                clean = h.plain(name, 300)
                if not clean or h.norm(clean) in h.EMPTY or h.norm(clean) == "not drawn":
                    continue
                explicit = trace_ids(clean, h, "term")
                for ident in explicit:
                    clean = clean.replace(ident, "")
                clean = h.one_line(re.sub(r"\(\s*\)", "", clean), 120)
                target.append((clean, context, explicit[0] if explicit else None, where))

        for line, row in rows:
            where = file + ":" + str(line)
            if {"context", "type", "aggregates"} <= row.keys():
                for ident in trace_ids(row["context"], h, "context"):
                    context = contexts.get(ident)
                    if context:
                        context["type"] = h.plain(row["type"], 120)
                    add_terms(aggregate_defs, row["aggregates"], ident, where)
            if {"given_by", "read_model", "command", "aggregate", "events"} <= row.keys():
                context, previous = located(line)
                if context is None:
                    partial(checks, h, file, line, "command table is under no context heading", part)
                    context = previous
                    if context is None:
                        context = contexts.setdefault("", {"id": "", "name": "", "type": "", "purpose": "",
                            "removed": False, "external": "", "rows": [], "where": where})
                given = h.plain(row["given_by"], 300)
                events = [h.plain(re.sub(r"^(?:or|또는)\s+", "", x.strip(), flags=re.I), 120)
                          for x in row["events"].split(",") if x.strip()]
                context["rows"].append({"given_by": given, "policy": bool(re.search(r"(?:\bPolicy\s*:|정책\s*:)", given, re.I)),
                    "read_model": h.plain(row["read_model"], 120), "command": h.plain(row["command"], 120),
                    "aggregate": h.plain(row["aggregate"], 120), "events": events[:20], "where": where})
                add_terms(aggregate_defs, row["aggregate"], context["id"], where)
                add_terms(model_defs, row["read_model"], context["id"], where)
            if {"read_model", "shows"} <= row.keys():
                name = word(h.plain(row["read_model"], 120))
                used = [c for c in contexts.values() if any(word(r["read_model"]) == name for r in c["rows"])]
                for context in used:
                    add_terms(model_defs, row["read_model"], context["id"], where)
            if {"from", "to", "kind", "why", "data"} <= row.keys():
                kind = h.plain(row["kind"], 120).casefold()
                picture["dependencies"].append({"from": h.plain(row["from"], 120), "to": h.plain(row["to"], 120),
                    "kind": "call" if kind.startswith(("call", "바로 묻기")) else "event" if kind.startswith(("event", "사건 알림")) else "",
                    "why": h.plain(row["why"], 300), "data": h.plain(row["data"], 300), "where": where})
            if {"hotspot", "context", "state", "answer"} <= row.keys():
                words = h.plain(row["hotspot"], 300)
                hotspot = {"text": words, "contexts": trace_ids(row["context"], h, "context")[:20],
                    "state": h.plain(row["state"], 120), "answer": h.plain(row["answer"], 300), "where": where}
                number = re.match(r"^(\d+)\s*[.)]?\s+", words)
                if number and int(number.group(1)) > 0:
                    hotspot["number"] = int(number.group(1))
                picture["hotspots"].append(hotspot)
            if {"lane", "events"} <= row.keys():
                places = []
                for place in re.split(r"\s*→\s*", row["events"])[:200]:
                    names = re.split(r",?\s+(?:or|또는)\s+", place)
                    cleaned = [h.plain(x, 120) for x in names if h.plain(x, 120)][:10]
                    if cleaned:
                        places.append(cleaned)
                picture.setdefault("timeline", []).append({"lane": h.plain(row["lane"], 120), "places": places, "where": where})
        picture["contexts"].extend(contexts.values())
        for target, definitions in (("aggregates", aggregate_defs), ("read_models", model_defs)):
            seen = set()
            for name, context, explicit, where in definitions:
                key = context, word(name)
                if key in seen:
                    continue
                seen.add(key)
                candidates = [explicit] if explicit else glossary.get(word(name), [])
                row = {"name": name, "context": context, "removed": bool(candidates and candidates[0] in removed), "where": where}
                if candidates:
                    row["term"] = candidates[0]
                if len(candidates) != 1:
                    warning = h.check("board-term-missing", "warn", name + " has " + ("multiple" if candidates else "no") + " glossary terms", [context] if context else [], "01-domain", {"name": name, "context": context})
                    if part:
                        warning["part"] = part
                    checks.append(warning)
                picture[target].append(row)
    for key, limit in (("contexts", 200), ("aggregates", 500), ("read_models", 500), ("dependencies", 500), ("hotspots", 500), ("timeline", 50)):
        if key in picture and len(picture[key]) > limit:
            picture[key] = picture[key][:limit]
            partial(checks, h, documents[-1][0], 1, key + " exceeds its picture limit", part)
    for context in picture["contexts"]:
        if len(context["rows"]) > 200:
            partial(checks, h, context["where"].rsplit(":", 1)[0], 1, "context rows exceed their picture limit", part)
        context["rows"] = context["rows"][:200]
    return picture if picture["contexts"] else None
