# Contributing

[한국어](CONTRIBUTING.ko.md)

One maintainer works with AI agents, including Claude Code and Codex, through pull requests. [AGENTS.md](AGENTS.md) is the source of repository rules, and [the architecture notes](docs/architecture.md) explain the design. Run the commands in [AGENTS.md's Checks section](AGENTS.md#checks) before every commit; that section is the source of check commands.

## Branches and history

Use GitHub flow: keep `main` passing its checks, start a short branch from the latest `origin/main` for one purpose, and delete the work branch after merging.

- AI agents use the host's branch name under `claude/…` or `codex/…`.
- People should use `<type>/<summary>`, such as `fix/hook-timeout`.
- Branch names do not grant permissions.

Never force push, delete or rewrite `main` or release tags. Only your own work branch may be force pushed, using both `--force-with-lease --force-if-includes`. Review fixes must still be new commits; do not rewrite commits already submitted for review.

## Commits

Follow Conventional Commits 1.0.0: `type(scope): summary`. Use `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore` or `revert`. An optional scope names the affected plugin or skill.

- Write an English imperative subject of at most 72 characters; aim for 50.
- Explain why in the body. Mark breaking changes with `!` or a `BREAKING CHANGE:` footer.
- Keep one change per commit, and make every commit pass the checks.
- Address reviews with additional commits; do not rewrite commits already submitted for review.

## Pull requests and merges

All changes go through a pull request. Use the PR template to explain what changes and why, the checks and results, risk and rollback, and any AI involvement. Include affected stage IDs when applicable.

Merge only with a merge commit, after:

- The checks pass, with `all-checks` on the head. A draft pull request's CI runs only the Linux jobs and reports `linux-checks`, so mark the pull request ready for review, which runs every system, before merging. If Actions fails before starting a runner, record the agreed replacement checks and their results in the PR, including each OS, tool versions, pass/fail counts and skips.
- Automated code and security reviews have completed at the latest head with no unresolved findings, and review conversations are resolved.
- If `main` has moved, the combined tree has been checked again on the required systems, and the merge commit's tree ID matches the checked tree.

Protection rules may be bypassed only for an Actions outage that fails before a runner starts, after the replacement results and the reason are recorded in a PR comment.

Use the merge title `Merge pull request #N: <PR title>`. The body records the change, review results and checks by OS. Keep `<` and `>` literal throughout the merge message, including attribution trailers; do not HTML-escape them.

## Versions and releases

Use SemVer 2.0.0. Versions stay in `0.x` during initial development, including after the repository becomes public; the maintainer declares the stable `1.0.0` release. During `0.x`, use MINOR for breaking changes and features, and PATCH for fixes. The breaking-change rule is this project's convention, not a requirement of SemVer. Prereleases use `-rc.N`.

Update both plugin manifests and every skill's `metadata.version` together, as specified in [AGENTS.md](AGENTS.md).

Release tags are annotated tags named `<plugin>--v<version>`, created only with `claude plugin tag plugins/<plugin>` from a passing `main` commit whose `check` workflow passed with macOS included. Do not create lightweight release tags, move published tags or delete them.

Release notes have a human-readable summary of 3–5 lines and an automatically generated PR list. There is no `CHANGELOG.md` for now.

## CI and security

- Never check out PR code in `pull_request_target` or `workflow_run` workflows.
- Pin actions to full commit SHAs, with their versions in comments on the same lines.
- Use minimum workflow permissions: `permissions: contents: read`.

Report security vulnerabilities through [the private reporting process](SECURITY.md). Use the public issue forms for ordinary bugs and feature requests.

## AI contributions and privacy

Agent-created commits keep that agent's co-author trailer. When the host supplies a session trailer, keep it too. Describe the agent's role in the PR's AI involvement section.

Never use a personal email address as the commit author: use your GitHub noreply address, or the no-reply identity your agent host sets. Do not put personal names, email addresses, home paths or private workspace links in commits, documents or examples. Follow [AGENTS.md](AGENTS.md) and the checks in [tests/test_public_safety.py](tests/test_public_safety.py).
