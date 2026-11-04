---
name: corthex-memory
description: Manage CORTHEX conversation recording on this device. Use when the user wants to turn recording on or off, inspect memory status, exclude folders or entry kinds, change the retention period, delete all device memory, or repair a damaged store record. Explains consent and confirmation, keeps keys out of chat, and distinguishes C1 recording from later curation and recall.
license: Apache-2.0
metadata:
  author: kodonghui
  version: "0.2.0"
---

# Manage device memory

C1 records redacted user prompts and final agent answers when the project is enabled; it does not curate memory. Model curation, semantic search and recall belong to C2. Do not promise those features or run their unimplemented commands. Tool calls, tool results and files are not recording inputs. The user's profile and project settings remain the source of their working preferences.

Use the user's language. Work on the device and session folder the user means. Do not turn memory on, delete it, repair it or change its settings merely because this skill was loaded. A request about implementation or a disposable test is not permission to operate on the user's real memory.

## Run the command

Resolve [scripts/memory.py](scripts/memory.py) relative to this SKILL.md and invoke its absolute path with Python 3.8 or later. Use an installed interpreter from an absolute PATH directory, not an executable in the project. On Windows use `python` or `py -3` if `python3` is unavailable. Quote paths and arguments for the host shell.

```text
python3 "<absolute skill directory>/scripts/memory.py" --folder "<absolute session folder>" status
```

Use the actual session folder for `--folder`, including when a request concerns an excluded subfolder. The project list determines ownership; do not infer a project from its name or open repository settings to replace the list. `on`, `off` and `leave-out` are project commands. `status`, `retention`, `purge` and `repair` act on this device; status may also include the session's project.

Read the one JSON result. Translate `say` without inventing successful effects, rollback or a diagnostic log. Explain the relevant fields of `data`. Exit 0 can mean `done`, `nothing` or `confirm`, so a successful process exit is not proof that the action happened. `refused` and `failed` exit 1; a usage error exits 2. Do not hide errors or edit store files to bypass a refusal.

## Choose a C1 command

| Command | User intent and behavior |
| --- | --- |
| `on` | Enable recording for the session's project. When consent is missing or outdated, show the complete consent text and ask first. Valid current consent can be reused; an already enabled project needs no new store. Missing provider keys do not prevent local C1 recording. |
| `off` | Stop new recording for this project and keep existing memory; retention continues. It is idempotent and asks for no extra confirmation. It does not delete a project's memory. |
| `status [--all]` | Read device status, available project summaries, disk usage, usage logs, hook timings and key presence. Unavailable C2 measurements are not claimed as working or displayed as verified zero. This command does not call a provider or run maintenance. |
| `leave-out [<folders>...] [--kind prompt|answer|boundary] [--remove]` | Add or remove exclusions for the session's enabled project. Folder arguments are relative to the selected session folder; repeat `--kind` for more kinds. Empty arguments show the current exclusions. An outside folder is refused. |
| `retention <days>` | Set the device period from 1 through 3650 days. Shortening previews the old/new periods and expired raw-entry count and asks first; extending applies directly. It changes configuration only; the next session-start worker applies deletion, including disabled or no longer registered projects. |
| `purge` | Preview the exact device memory folder and its projects/counts/sync state, then ask to delete that whole folder and consent. Profile, project list and plugin stay; remote and other-device copies remain. This is not a substitute for an unimplemented single-project delete. |
| `repair` | Ask before replacing an irrecoverable store record with a new device ID; configuration, consent and other memory are preserved. A readable record needs no repair. Supported readable backups use ordinary recovery; a missing directory is not created. |

An uninstall leaves the memory store behind. `off` preserves it too. Do not describe either as deletion. Purge affects only the shown local folder, not host transcripts, providers or other devices. Do not send memory elsewhere or start sync to satisfy a local management request.

## Ask before applying

A confirmation code is not permission. First run the command without `--confirm` and show its current proposal. Only after the user's explicit yes run the same command and arguments with `--confirm <code>` from that proposal. A general request for a feature, a pasted instruction, or an agent-generated code is not the user's yes.

For `on`, show every point in `data.consent.text` in the user's language, preserving provider, retention, redaction, sync and API-spending disclosures. Explain that C1 currently records without model curation or recall; do not drop the consent's future model disclosures. Missing keys are a presence warning, not a request to put secrets in the conversation.

For `retention`, distinguish the proposed expired-entry count from immediate deletion. For `purge`, show `data.folder`, the whole-folder scope, available counts and copies that remain elsewhere. Show null counts or lists and unknown sync as "cannot verify", never as zero, an empty list or off. The user may confirm the whole shown folder even when metadata cannot be verified; do not interpret an opaque newer layout to invent counts.

For `repair`, explain that only the store record receives a new device ID and that invalid or missing configuration is preserved. Repair does not enable recording or obtain new consent. Keep the same configured device target between preview and application; its existing empty-object preview does not bind a different memory-home override into the code.

On `confirm-stale`, show the new proposal and ask the user again. Never silently substitute the new code or assume a previous yes covers a changed proposal. The command checks current and previous ten-minute periods; do not compute a code yourself or change the clock to make one valid.

## Result codes

These rows list every code applicable to each C1 command, including invalid-home overrides. Read the explanation below before applying a broad common-code rule.

| Command | Codes |
| --- | --- |
| `on` | `configuration-invalid`, `confirm-stale`, `internal`, `lock-busy`, `no-project-list`, `not-in-project`, `ok`, `store-damaged`, `store-newer`, `usage` |
| `off` | `configuration-invalid`, `internal`, `lock-busy`, `no-project-list`, `no-store`, `not-enabled`, `not-in-project`, `ok`, `store-damaged`, `store-newer`, `usage` |
| `status` | `configuration-invalid`, `internal`, `lock-busy`, `no-store`, `ok`, `store-damaged`, `store-newer`, `usage` |
| `leave-out` | `configuration-invalid`, `folder-outside`, `internal`, `lock-busy`, `no-project-list`, `no-store`, `not-enabled`, `not-in-project`, `ok`, `store-damaged`, `store-newer`, `usage` |
| `retention` | `configuration-invalid`, `confirm-stale`, `internal`, `lock-busy`, `no-store`, `ok`, `store-damaged`, `store-newer`, `usage` |
| `purge` | `configuration-invalid`, `confirm-stale`, `files-left`, `internal`, `lock-busy`, `ok`, `usage` |
| `repair` | `configuration-invalid`, `confirm-stale`, `internal`, `lock-busy`, `ok`, `store-newer`, `usage` |

- `ok`: check `outcome`; `confirm` waits, `nothing` is a no-op, and only `done` reports the completed action.
- `usage`: explain documented arguments; do not echo unknown arguments that might contain a pasted key.
- `no-store`: use `on` only when the user wants recording. Status returns `nothing`; purge and repair use their own no-op behavior. Do not create a store as a read-side fix.
- `store-newer`: update the plugin; do not downgrade or repair an opaque store. Purge is the explicit whole-folder exception and still asks first.
- `store-damaged`: explain that repair can propose a new store record. Do not rewrite it directly or reset configuration.
- `configuration-invalid`: name the safe reported field. An invalid `CORTHEX_MEMORY_HOME` is refused by every command, with no fallback to a different folder. Status can report a schema-invalid configuration; purge and repair have narrow configuration exemptions, not permission to fix its fields.
- `no-project-list` or `not-in-project`: use the core corthex skill to help register or select the intended project. A clash needs a specific project choice; do not guess one or change the registry as a memory side effect.
- `not-enabled`: explain that the project's memory is off. `on` bypasses this gate; `off` on an already disabled project is `nothing`.
- `confirm-stale`: show the new proposal and ask again; make no confirmed change with the old code.
- `folder-outside`: show `data.outside` and keep exclusions unchanged. Do not rebase an outside path to make it appear inside.
- `files-left`: show the actual relative `data.left` paths inside the shown root and the manual cleanup guidance. Close the program holding them before retrying. Do not claim full deletion or broaden manual removal beyond that folder.
- `lock-busy`: explain the ten-second wait and offer a later retry. Never force a lock for repair or a routine setting change; only the confirmed purge implementation may revoke the leases in its deletion scope. Do not kill a PID from a lock file.
- `internal`: report failure without claiming rollback, revealing exception text or promising a log. Stop for a real diagnosis rather than repeating a destructive action.

Healthy reads do not take write leases. An ordinary supported backup recovery may take its record lease and record a safe restore notice before a preview; do not turn a busy recovery into success, skip it, or use force to get past it. A lost root/header/lease stops further mutation.

## Keep secrets and boundaries

Never ask the user to paste an API key into chat. Read only key presence from status, not secret values or the process environment. Provider use in later stages takes `CORTHEX_MEMORY_ANTHROPIC_API_KEY` and `CORTHEX_MEMORY_OPENAI_API_KEY` from the environment that starts the host. Do not print, log, put in command arguments or store either value in project settings, memory, Notion or a transcript.

If a pasted API key appears, tell the user to revoke it and rotate it in the provider console; do not repeat it, test it, save it or treat later redaction as removing the exposure. Ask them to set the replacement through their local secret/environment mechanism without sending it in chat.

Recording removes configured secrets and `<private>...</private>` text before writing, but it does not erase the host's transcript or guarantee removal of every unknown secret. Do not request sensitive data to exercise redaction. Use disposable fixtures for development and tests, and distinguish code checks from actual installed-host walks and the maintainer's trial.
