"""SQL picture reader. Tokenization is shared with the hub's inert SQL reader."""
import re

CONSTRAINT_WORDS = {"NOT", "NULL", "PRIMARY", "UNIQUE", "REFERENCES", "CHECK", "DEFAULT", "COLLATE", "GENERATED", "CONSTRAINT", "COMMENT", "AUTO_INCREMENT", "IDENTITY"}


def words(tokens):
    return [t[1].upper() if t[0] == "name" else t[1] for t in tokens]


def groups(tokens, level):
    """Comma-separated expressions at one parenthesis depth."""
    result, current = [], []
    for token in tokens:
        if token[1] == "," and token[3] == level:
            if current:
                result.append(current)
            current = []
        else:
            current.append(token)
    if current:
        result.append(current)
    return result


def inside_parens(tokens, start):
    opening = next((i for i in range(start, len(tokens)) if tokens[i][1] == "("), None)
    if opening is None:
        return [], len(tokens)
    level = tokens[opening][3]
    closing = next((i for i in range(opening + 1, len(tokens)) if tokens[i][1] == ")" and tokens[i][3] == level + 1), len(tokens))
    return tokens[opening + 1:closing], closing + 1


def names(tokens, h):
    return [h.one_line(h.sql_name(group[0][1]), 120) for group in groups(tokens, tokens[0][3] if tokens else 1) if group and group[0][0] == "name"][:50]


def index_columns(tokens, table, h):
    """Only name-based indexes fit the picture's column-list representation."""
    known = {column["name"].casefold() for column in table["columns"]}
    result = []
    for group in groups(tokens, tokens[0][3] if tokens else 1):
        if not group or group[0][0] != "name":
            return None
        name = h.one_line(h.sql_name(group[0][1]), 120)
        if name.casefold() not in known:
            return None
        tail = words(group[1:])
        if tail[:1] == ["COLLATE"] and len(group) > 2 and group[2][0] == "name":
            tail = tail[2:]
        if tail[:1] in (["ASC"], ["DESC"]):
            tail = tail[1:]
        if tail in (["NULLS", "FIRST"], ["NULLS", "LAST"]):
            tail = []
        if tail:
            return None
        result.append(name)
    return result[:50] if result else None


def removed_status(comment, h):
    # Delimiters inside quoted identifiers/titles are ordinary characters.
    # Preserve quoted field values so status: 'deleted' still has its meaning.
    fields, current, quoted, collecting, index = [], [], None, False, 0
    while index < len(comment):
        char = comment[index]
        if quoted:
            if collecting:
                current.append(char)
            if char == quoted:
                if index + 1 < len(comment) and comment[index + 1] == quoted:
                    if collecting:
                        current.append(comment[index + 1])
                    index += 2
                    continue
                quoted = None
        elif char in "\"'`[" and (index == 0 or comment[index - 1].isspace() or comment[index - 1] in "(|,;:."):
            quoted = "]" if char == "[" else char
            if collecting:
                current.append(char)
        elif char in "(|),;":
            if collecting:
                fields.append("".join(current))
                current = []
            if char in "(|":
                collecting = True
            elif char == ")":
                collecting = False
        elif collecting:
            current.append(char)
        index += 1
    if collecting:
        fields.append("".join(current))
    for field in fields:
        explicit = re.match(r"\s*(?:status|상태)\s*:\s*(.*)$", field, re.I)
        if explicit:
            return h.is_removed({"status": explicit.group(1)})
    return any(h.norm(field) in h.REMOVED for field in fields)


def type_text(tokens, h):
    value = " ".join("'" + t[1].replace("'", "''") + "'" if t[0] == "string" else t[1] for t in tokens)
    value = re.sub(r"\s*([(.])\s*", r"\1", value)
    value = re.sub(r"\s*\)", ")", value)
    value = re.sub(r"\s*,\s*", ", ", value)
    return h.one_line(value, 120)


def foreign_key(tokens, h, file, columns=None):
    w = words(tokens)
    if "REFERENCES" not in w:
        return None
    reference = w.index("REFERENCES")
    if columns is None:
        try:
            index = next(i for i in range(reference) if w[i:i + 2] == ["FOREIGN", "KEY"])
        except StopIteration:
            return None
        local, _ = inside_parens(tokens, index + 2)
        columns = names(local, h)
    target = reference + 1
    target_names = []
    while target < len(tokens) and tokens[target][0] == "name":
        target_names.append(h.sql_name(tokens[target][1]))
        target += 1
        if target < len(tokens) and tokens[target][1] == ".":
            target += 1
        else:
            break
    refs, _ = inside_parens(tokens, target) if target < len(tokens) and tokens[target][1] == "(" else ([], target)
    deletion = ""
    for i in range(reference, len(w) - 2):
        if w[i:i + 2] == ["ON", "DELETE"]:
            option = " ".join(w[i + 2:i + 4]).lower()
            deletion = next((x for x in ("set null", "set default", "no action", "cascade", "restrict") if option.startswith(x)), "")
            break
    if not columns or not target_names:
        return None
    return {"columns": columns[:50], "table": h.one_line(target_names[-1], 120), "references": names(refs, h),
            "on_delete": deletion, "where": file + ":" + str(tokens[reference][2])}


def parse(documents, checks, h, part):
    picture = {"format": 1, "tables": [], "without_table": []}
    made, statements, annotations = {}, [], {}

    def issue(file, line, detail):
        row = h.check("picture-partial", "warn", file + ":" + str(line) + ": " + detail, stage="05-erd")
        if part:
            row["part"] = part
        checks.append(row)

    for file, text in documents:
        for token_list in h.sql_statements(text):
            about, creates, own_comment = h.sql_about(token_list)
            comments = [(t[1][2:].strip(), t[2]) for t in token_list if t[0] == "comment" and t[1].startswith("--") and t[3] == 0]
            for comment, _ in comments:
                marker = re.match(r"without a table\s*:\s*(.*)", comment, re.I)
                if marker:
                    picture["without_table"].extend(x for x, kind, _ in h.picture_ids.find(marker.group(1)) if kind == "term")
            if not about:
                continue
            if own_comment:
                comments.append(own_comment)
            for comment, line in comments:
                lead = h.picture_ids.lead(comment)
                if lead and lead[1] == "table":
                    annotations[about[0]] = (lead[0], comment, line)
            code = [t for t in token_list if t[0] != "comment"]
            statements.append((file, code, about, creates))
            if creates:
                made[about[0]] = None

    def key_for(key):
        if key in made:
            return key
        aliases = [x for x in made if x[1] == key[1]]
        return aliases[0] if len(aliases) == 1 else key

    for file, code, about, creates in statements:
        if not creates:
            continue
        key = about[0]
        annotation = annotations.get(key) or annotations.get(key_for(key))
        ident, comment, line = annotation if annotation else ("", "", code[0][2])
        context = next((x for x, kind, _ in h.picture_ids.find(comment) if kind == "context"), "")
        table = {"id": ident, "name": h.one_line(about[1], 120), "context": context,
            "removed": removed_status(comment, h), "columns": [], "primary_key": [], "unique": [], "foreign_keys": [],
            "where": file + ":" + str(line)}
        terms = [x for x, kind, _ in h.picture_ids.find(comment) if kind == "term"]
        if terms or re.search(r"\bterms\s*:\s*none\b", comment, re.I):
            table["terms"] = list(dict.fromkeys(terms))[:20]
        body, _ = inside_parens(code, 0)
        if not body:
            issue(file, code[0][2], "CREATE TABLE has no readable column list")
        for expression in groups(body, 1):
            w = words(expression)
            if w[:1] == ["CONSTRAINT"]:
                expression, w = expression[2:], w[2:]
            if not expression:
                continue
            if w[:2] == ["PRIMARY", "KEY"]:
                cols, _ = inside_parens(expression, 2)
                table["primary_key"].extend(names(cols, h))
            elif w[:1] == ["UNIQUE"]:
                cols, _ = inside_parens(expression, 1)
                if cols:
                    table["unique"].append({"columns": names(cols, h), "partial": False})
            elif w[:2] == ["FOREIGN", "KEY"]:
                fk = foreign_key(expression, h, file)
                if fk:
                    table["foreign_keys"].append(fk)
            elif w[0] not in ("CHECK", "KEY", "INDEX", "EXCLUDE", "LIKE") and expression[0][0] == "name":
                name = h.one_line(h.sql_name(expression[0][1]), 120)
                end_type = next((i for i in range(1, len(expression)) if expression[i][3] == 1 and w[i] in CONSTRAINT_WORDS), len(expression))
                datatype = type_text(expression[1:end_type], h)
                column = {"name": name, "type": datatype, "null": not any(w[i:i + 2] == ["NOT", "NULL"] or w[i:i + 2] == ["PRIMARY", "KEY"] for i in range(len(w) - 1)),
                    "where": file + ":" + str(expression[0][2])}
                table["columns"].append(column)
                if any(w[i:i + 2] == ["PRIMARY", "KEY"] for i in range(len(w) - 1)):
                    table["primary_key"].append(name)
                if "UNIQUE" in w:
                    table["unique"].append({"columns": [name], "partial": False})
                fk = foreign_key(expression, h, file, [name])
                if fk:
                    table["foreign_keys"].append(fk)
        made[key] = table
        picture["tables"].append(table)

    for file, code, about, creates in statements:
        table = made.get(key_for(about[0]))
        if not table or creates:
            continue
        w = words(code)
        if w[:2] == ["ALTER", "TABLE"]:
            for action in groups(code, 0):
                fk = foreign_key(action, h, file)
                if fk:
                    table["foreign_keys"].append(fk)
        elif w[:1] == ["CREATE"] and "UNIQUE" in w[:4] and "INDEX" in w[:5] and "ON" in w:
            cols, _ = inside_parens(code, w.index("ON") + 1)
            if cols:
                columns = index_columns(cols, table, h)
                if columns:
                    table["unique"].append({"columns": columns, "partial": "WHERE" in w})
                else:
                    issue(file, code[0][2], "unique index has an unreadable column expression; rule omitted")
    for table in picture["tables"]:
        table["primary_key"] = list(dict.fromkeys(table["primary_key"]))[:50]
        for column in table["columns"]:
            if column["name"] in table["primary_key"]:
                column["null"] = False
        for key, limit in (("columns", 300), ("unique", 50), ("foreign_keys", 100)):
            if len(table[key]) > limit:
                issue(table["where"].rsplit(":", 1)[0], 1, key + " exceeds its picture limit")
                table[key] = table[key][:limit]
    if len(picture["tables"]) > 500:
        issue(documents[-1][0], 1, "more than 500 tables; later tables are omitted")
        picture["tables"] = picture["tables"][:500]
    picture["without_table"] = list(dict.fromkeys(picture["without_table"]))[:500]
    return picture
