# NEXUS snapshot CI

The `NEXUS push` workflow sends the repository's project snapshot after a push reaches `main`, using `hub.py push --job --json` from the immutable hub commit `c6095b40c71bc74d207b13b5b08aeeb078c7d0c5`. It never runs on pull requests and does not deploy the application.

The repository owner must set these Actions secrets in Settings → Secrets and variables → Actions:

- `CORTHEX_NEXUS_URL`: the existing NEXUS server URL.
- `CORTHEX_NEXUS_CLIENT_ID`: the Cloudflare Access service client ID.
- `CORTHEX_NEXUS_CLIENT_SECRET`: the matching service secret.

Do not paste secret values into a PR, log or file. No secrets are configured by this change. If secrets are missing, the job reports `not-set` and sends nothing. The project name comes from `.corthex/project.json` (`marong` in the marong2 repository). A first upload still needs the owner's confirmation and a manual `--first` push; CI reports `first-push-waits`. It sends only a newer descendant of the held default-branch commit, never replaces divergent history, never approves checkpoints and never deletes a project.

The job uses read-only repository permission, full project history, immutable checkout action and hub pins, no persisted Git credentials, and serial execution without cancellation. Only the final hub step receives the secrets.

To stop automation, disable `NEXUS push` in Actions. To roll it back, revert the PR adding `.github/workflows/corthex-nexus-push.yml`. Existing server data remains. Updating the hub pin requires checking compatibility with the deployed server and the product repository's `hub-ref.json`.

Validation: the workflow is identical to the already tested push-job example in the NEXUS server guide. Live delivery remains unverified until the owner configures the secrets and the job receives a default-branch push.
