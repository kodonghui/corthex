"""Explicit GitHub Actions setup; secrets travel only through gh's stdin."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote, urlsplit

SECRET_NAMES = ("CORTHEX_NEXUS_URL", "CORTHEX_NEXUS_CLIENT_ID", "CORTHEX_NEXUS_CLIENT_SECRET")
WORKFLOW = ".github/workflows/corthex-nexus-push.yml"
REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


class GhFailure(Exception):
    pass


def executable(env, root=None):
    name = "gh.exe" if os.name == "nt" else "gh"
    for folder in env.get("PATH", "").split(os.pathsep):
        path = Path(folder.strip('"'))
        if not path.is_absolute() or path.resolve() in {Path.cwd().resolve(), Path(root or Path.cwd()).resolve()}:
            continue
        candidate = path / name
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return None


def repository(remote):
    user, separator, host_path = remote.partition("@")
    if user == "git" and separator and host_path.startswith("github.com:"):
        name = host_path[len("github.com:"):]
    else:
        try:
            url = urlsplit(remote)
            if url.hostname != "github.com" or url.password or url.query or url.fragment:
                return None
            if url.scheme == "https" and not url.username or url.scheme == "ssh" and url.username == "git":
                name = url.path.lstrip("/")
            else:
                return None
        except ValueError:
            return None
    if name.endswith(".git"):
        name = name[:-4]
    return name if REPOSITORY.fullmatch(name) and all(x not in (".", "..") for x in name.split("/")) else None


def server_url(value):
    try:
        if any(ord(c) < 33 or ord(c) == 127 for c in value):
            return False
        url = urlsplit(value)
        if (url.scheme != "https" or not url.hostname or url.username or url.password or
                url.query or url.fragment or url.path.rstrip("/") or url.port not in (None, 443)):
            return False
        if url.hostname.lower() == "localhost":
            return False
        try:
            if ipaddress.ip_address(url.hostname).is_loopback:
                return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False


class GitHub:
    def __init__(self, program, root, env, run=subprocess.run):
        self.program, self.root, self.run = program, root, run
        # gh uses its own login. Do not also put the NEXUS credentials in its environment.
        self.env = {k: v for k, v in env.items() if k not in SECRET_NAMES}
        self.env.update(GH_HOST="github.com", GH_PROMPT_DISABLED="1", GH_PAGER="cat", GIT_TERMINAL_PROMPT="0")

    def call(self, arguments, body=None):
        try:
            return self.run([self.program] + arguments, input=body, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=str(self.root), env=self.env, timeout=45)
        except (OSError, subprocess.SubprocessError):
            # Never render an exception or a failed command's output: gh or a
            # wrapper could have echoed the stdin, including a secret.
            raise GhFailure("gh did not complete")

    def api(self, method, path, value=None, missing=False):
        args = ["api", "--method", method, path]
        body = None
        if value is not None:
            args += ["--input", "-"]
            body = json.dumps(value, separators=(",", ":")).encode("utf8")
        result = self.call(args, body)
        if result.returncode:
            if missing and (b"HTTP 404" in result.stderr or b'"status":"404"' in result.stdout or
                            b'"status": "404"' in result.stdout):
                return None
            raise GhFailure("GitHub request failed")
        try:
            return json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise GhFailure("GitHub returned an unreadable answer")

    def secret(self, repo, name, value):
        result = self.call(["secret", "set", name, "--repo", repo, "--app", "actions"], value.encode("utf8"))
        if result.returncode:
            raise GhFailure("could not configure " + name)


def repository_info(client, repo):
    info = client.api("GET", "repos/" + repo)
    branch = info.get("default_branch")
    if (not isinstance(branch, str) or not branch or len(branch) > 200 or
            any(ord(c) < 33 for c in branch) or info.get("full_name", "").casefold() != repo.casefold()):
        raise GhFailure("could not identify the default branch")
    return info


def workflow_pr(client, repo, dry_run=False, info=None):
    info = info or repository_info(client, repo)
    branch = info["default_branch"]
    base = "repos/" + repo
    content_path = base + "/contents/" + WORKFLOW
    current = client.api("GET", content_path + "?ref=" + quote(branch, safe=""), missing=True)
    if current is not None:
        return {"state": "present"}
    # Reuse an already reviewed/manual workflow PR too, not only a branch
    # created by this helper. Match the actual immutable workflow bytes.
    pending = client.api("GET", base + "/pulls?state=open&base=" + quote(branch, safe="") + "&per_page=100")
    for pull in pending:
        commit = pull.get("head", {}).get("sha", "")
        number = pull.get("number")
        if type(number) is not int or not re.fullmatch(r"[0-9a-f]{40}", commit):
            continue
        candidate = client.api("GET", content_path + "?ref=" + commit, missing=True)
        try:
            same = candidate is not None and base64.b64decode(candidate.get("content", "")) == workflow_text(branch).encode("utf8")
        except (ValueError, TypeError):
            same = False
        if same:
            return {"state": "pr-open", "url": "https://github.com/" + repo + "/pull/" + str(number)}
    if dry_run:
        return {"state": "would-open-pr"}
    held = client.api("GET", base + "/git/ref/heads/" + quote(branch, safe=""))
    sha = held.get("object", {}).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise GhFailure("could not identify the default commit")
    head = "corthex/nexus-ci-" + sha[:12]
    pulls = base + "/pulls?state=open&base=" + quote(branch, safe="") + "&head=" + quote(repo.split("/")[0] + ":" + head, safe="")
    opened = client.api("GET", pulls)
    if opened:
        number = opened[0].get("number")
        if type(number) is not int:
            raise GhFailure("could not identify the existing pull request")
        return {"state": "pr-open", "url": "https://github.com/" + repo + "/pull/" + str(number)}
    ref_path = base + "/git/ref/heads/" + quote(head, safe="")
    ref = client.api("GET", ref_path, missing=True)
    if ref is None:
        client.api("POST", base + "/git/refs", {"ref": "refs/heads/" + head, "sha": sha})
    elif ref.get("object", {}).get("sha") != sha:
        # An earlier interrupted run is reusable only when its sole change is
        # our exact workflow. Never overwrite or publish someone else's branch.
        compare = client.api("GET", base + "/compare/" + sha + "..." + quote(head, safe=""))
        candidate = client.api("GET", content_path + "?ref=" + quote(head, safe=""), missing=True)
        expected = workflow_text(branch).encode("utf8")
        try:
            same = candidate is not None and base64.b64decode(candidate.get("content", "")) == expected
        except (ValueError, TypeError):
            same = False
        if not same or [f.get("filename") for f in compare.get("files", [])] != [WORKFLOW]:
            raise GhFailure("the CI branch has other changes; it was left untouched")
    candidate = client.api("GET", content_path + "?ref=" + quote(head, safe=""), missing=True)
    if candidate is None:
        client.api("PUT", content_path, {"message": "ci: push NEXUS snapshots after default-branch merges",
                   "branch": head, "content": base64.b64encode(workflow_text(branch).encode("utf8")).decode("ascii")})
    pull = client.api("POST", base + "/pulls", {"title": "ci: push NEXUS snapshots after default-branch merges",
             "head": head, "base": branch, "body": "Run the immutable hub's push --job on default-branch pushes only. "
             "The checkout and hub are pinned; repository permission is read-only. First uploads and checkpoint passes "
             "remain the maintainer's actions. Repository Actions secrets were configured from the setup session's "
             "environment without printing or writing their values locally. This PR does not deploy the application."})
    number = pull.get("number")
    if type(number) is not int:
        raise GhFailure("could not identify the created pull request")
    return {"state": "pr-open", "url": "https://github.com/" + repo + "/pull/" + str(number)}


def workflow_text(default_branch="main"):
    text = (Path(__file__).resolve().parent.parent / "assets" / "corthex-nexus-push.yml").read_text(encoding="utf8")
    return text if default_branch == "main" else text.replace("branches: [main]", "branches: [" + json.dumps(default_branch) + "]")


def setup(project, home, h, env=None, dry_run=False, run=subprocess.run):
    env = os.environ if env is None else env
    result = {"state": "skipped", "why": "", "secrets": [], "workflow": None}
    missing = [name for name in SECRET_NAMES if not env.get(name)]
    if missing:
        return dict(result, why="missing settings: " + ", ".join(missing))
    try:
        for name in SECRET_NAMES:
            env[name].encode("utf8")
    except UnicodeError:
        return dict(result, state="failed", why="CI settings must be valid UTF-8")
    if not server_url(env[SECRET_NAMES[0]]):
        return dict(result, why="CI needs a non-loopback HTTPS NEXUS origin")
    repo = repository(h.git(project.root, "remote", "get-url", "origin") or "")
    if repo is None:
        return dict(result, why="the project has no supported GitHub origin")
    result["repository"] = repo
    program = executable(env, project.root)
    if program is None:
        return dict(result, why="gh is not installed; CI setup skipped")
    client = GitHub(program, project.root, env, run)
    try:
        if client.call(["auth", "status", "--hostname", "github.com"]).returncode:
            return dict(result, why="gh is not logged in to github.com; CI setup skipped")
        info = repository_info(client, repo)
        if not dry_run:
            for name in SECRET_NAMES:
                client.secret(repo, name, env[name])
                result["secrets"].append(name)
        result["workflow"] = workflow_pr(client, repo, dry_run, info)
        return dict(result, state="preview" if dry_run else "done", why="")
    except GhFailure as error:
        return dict(result, state="failed", why=str(error))


def selected(args, home, h):
    if not isinstance(args.project, str) or not h.NAME.fullmatch(args.project):
        raise ValueError("name one project with lowercase letters, digits and hyphens")
    entry = h.select_projects(home, [args.project])[0]
    if entry[1] is None:
        raise ValueError(entry[2])
    place = h.companion("commands").where(args, home, os.environ, h)
    if args.project not in place.allowed:
        raise ValueError("the project is not allowed to use this session's NEXUS server")
    return entry[1]


def line(project, result):
    label = project + ": CI setup " + result["state"]
    if result["why"]:
        return label + ": " + result["why"]
    workflow = result.get("workflow") or {}
    if result["state"] == "preview":
        return label + "; would configure three secrets; workflow " + workflow.get("state", "unknown")
    return label + "; " + str(len(result["secrets"])) + " secrets configured; workflow " + workflow.get("state", "unknown") + (" " + workflow["url"] if workflow.get("url") else "")


def main(args, home, h):
    project = selected(args, home, h)
    result = setup(project, home, h, dry_run=args.dry_run)
    if args.json:
        h.say(json.dumps({"command": "setup-ci", "project": project.name, "outcome": "failed" if result["state"] == "failed" else "done", "answer": result}, separators=(",", ":")))
    else:
        h.say(line(project.name, result))
    return 1 if result["state"] == "failed" else 0


def after_first(args, home, rows, h):
    if args.command != "push" or not getattr(args, "first", False) or args.dry_run:
        return
    for row in rows:
        if row["outcome"] != "done":
            continue
        name, project, _ = h.select_projects(home, [row["project"]])[0]
        if project is None:
            continue
        # An explicit --url may send this upload somewhere other than the CI
        # environment. Never silently redirect future jobs to a different server.
        configured = os.environ.get(SECRET_NAMES[0])
        uploaded = h.companion("commands").where(args, home, os.environ, h).url
        different = configured and (not isinstance(uploaded, str) or
                                    uploaded.rstrip("/") != configured.rstrip("/"))
        if different:
            result = {"state": "skipped", "why": "the upload destination differs from CORTHEX_NEXUS_URL",
                      "secrets": [], "workflow": None}
        else:
            result = setup(project, home, h)
        # Keep the established push JSON receipt intact. Optional CI setup is
        # a separate one-line diagnostic, never a reason to repeat an upload.
        h.say(line(name, result), sys.stderr)


def configure(commands):
    parser = commands.add_parser("setup-ci", help="configure GitHub Actions secrets from the environment and open a missing push-workflow PR")
    parser.add_argument("project")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
