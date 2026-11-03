# NEXUS server

[한국어](README.ko.md)

The NEXUS server puts the CORTHEX project hub on an address of your own, so you can open it from any device. It is a Cloudflare Worker: it keeps the snapshots that `hub.py push` sends in a Cloudflare D1 database and serves the same page that `corthex-nexus` builds on your machine. It runs on your Cloudflare account, and Cloudflare Access decides who can open it.

This folder is not a plugin. Deploy it from a clone of this repository.

## What it keeps and who can see it

- **Snapshots only.** One row per project holds the snapshot that `hub.py push` sent: IDs, titles, states, checks, file locations and commit IDs, never other file contents or local paths ([format](../plugins/corthex-nexus/skills/corthex-hub/references/snapshot.md)). A new push of a project replaces its row. The Worker keeps nothing else and logs no stored text.
- **Access first.** The Worker answers only requests that Cloudflare Access checked. Any other request gets `403` and no data, so a Worker deployed before Access is set up shows nothing.
- **One address.** Only the address you set serves it: no `workers.dev` or preview addresses, and no static assets, which would take the Access check away from the Worker.
- **A page that loads nothing.** The page carries its data and loads nothing from the network. It runs only its own script, allowed by its hash, and other sites can neither frame it nor change what the server holds.

## Requirements

- A Cloudflare account with a domain on it, and Cloudflare Zero Trust set up. The Zero Trust Free plan is enough; its setup asks for payment details even so.
- Node.js 22.13 or later, and a clone of this repository.
- `corthex-nexus` on each machine that sends snapshots.

## Set up

1. Install the tools: in this folder, run `npm install`.
2. Make your own settings file: copy `wrangler.jsonc` to `wrangler.local.jsonc`, which git ignores. In the copy, set the address in `routes`, such as `nexus.example.com` on a domain in your account, and set `NEXUS_LANGUAGE` to `ko` for a Korean page.
3. Deploy: run `npx wrangler login`, then `npm run deploy`. The first deploy creates the D1 database `corthex-nexus` and links it to the Worker; run in a terminal, it also writes the database's ID into your settings file, and later deploys keep using the database either way. Cloudflare then adds the address's DNS record and certificate. If the address already has a DNS record, for example from an earlier service, Cloudflare does not put the Worker's record over it: note its value if you may need it, delete it in the dashboard under your domain's **DNS** › **Records**, and deploy again. Until the next step, the address answers `403`.
4. Protect the Worker with Access. In the Cloudflare dashboard, go to **Workers & Pages**, select `corthex-nexus`, open the **Access** tab and select **Protect this Worker behind Access**. Choose **All traffic**, choose who can sign in (for yourself alone, **Cloudflare account**) and select **Apply Access**. If an Access application for this address already exists under **Zero Trust** › **Access controls** › **Applications**, it applies before Worker-level Access and already protects the hub: check that its policies let in only the people you want, and skip this step.
5. Pin the application before checking it. Remove the empty `ACCESS_AUD` placeholder from your local `vars`, then run `npx wrangler secret put ACCESS_AUD -c wrangler.local.jsonc` and enter that application's **Application Audience (AUD) Tag** at the prompt. Set `ACCESS_TEAM_DOMAIN` in your local file's `vars` to your team host, such as `your-team.cloudflareaccess.com`, and deploy again. Open the address in a private window: the Access sign-in comes first, then the empty hub page.
6. Create a service token for `hub.py`. In **Zero Trust** › **Access controls** › **Service credentials** › **Service Tokens**, create one and copy its Client ID and Client Secret; the secret is shown only once. Then open the Access application that protects the hub, the one from step 4 or the one the address already had, under **Zero Trust** › **Access controls** › **Applications**, and add a policy with the action **Service Auth** that includes this token. Add it to that application rather than creating a second one for the same Worker, which can conflict with it.
7. On each machine that sends snapshots, set the address and the projects that may be sent in `~/.corthex/profile.json`:

   ```json
   { "nexus": { "url": "https://nexus.example.com", "push": ["acme-shop"] } }
   ```

   Put the token in the environment variables `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`, from your system's secret store, never in a file in a repository. Then run `hub.py push --dry-run`, and `hub.py push`.

`ACCESS_AUD` and `ACCESS_TEAM_DOMAIN` are required in 0.2. Several audience tags can be given, separated by commas. After checking `ctx.access`, the Worker verifies the assertion header's RS256 signature against the configured team's public keys, issuer, audience and expiry; a missing configuration grants no access. It retains only the author's kind, never a person or service identity.

The dashboard names follow Cloudflare's documentation as of October 2026: [Cloudflare Access for Workers](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/), [service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/) and [Zero Trust setup](https://developers.cloudflare.com/cloudflare-one/setup/).

## Use

- `hub.py push` sends the projects in `nexus.push`; name projects to send only those. The server keeps the newer snapshot of a project: one generated earlier than the stored one is refused, so build again and push.
- `hub.py remove <project>` deletes a project from the server. Taking a project out of `nexus.push` stops further pushes but leaves what the server holds.
- When signed in, `/api/snapshots` lists what the server holds.

## Limits

- A snapshot of up to 1 MiB (`hub.py` keeps them under 1 MB), and up to 30 projects. A snapshot dated more than 10 minutes in the future is refused; check the clock of the machine that made it.
- On the Workers Free plan, a request gets 10 ms of CPU time. Checking a snapshot of about 40 KB, the size of a real project with 92 items, took under 1 ms in a local measurement with Node; one near 1 MB took about 15 ms and may exceed the limit.
- D1's free plan has daily limits on rows read and written, which a personal hub stays far below. See Cloudflare's current [Workers limits](https://developers.cloudflare.com/workers/platform/limits/) and [D1 limits](https://developers.cloudflare.com/d1/platform/limits/).

## Try it on this machine

- `npm test` runs the server's checks with Node's own test runner over an in-memory database.
- For a local HTTP stand-in, run `node test/serve.js`. It signs synthetic assertions and uses in-memory SQLite; its printed `127.0.0.1` address works with the hub. `npm run dev` does not manufacture a signed Access assertion: a fake `ctx.access` audience alone cannot authenticate in 0.2. Check the Workers runtime on a separately protected development Worker with its own D1 and service token.

## Update and remove

- To update, pull the repository, compare `wrangler.jsonc` with your copy, then run `npm install` and `npm run deploy`.
- To remove it, `npx wrangler delete -c wrangler.local.jsonc` deletes the Worker and `npx wrangler d1 delete corthex-nexus` deletes the database with its snapshots. Then delete the Access application and the service token under **Zero Trust** › **Access controls**.
