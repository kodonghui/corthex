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
- Node.js 22.5 or later, and a clone of this repository.
- `corthex-nexus` on each machine that sends snapshots.

## Set up

1. Install the tools: in this folder, run `npm install`.
2. Make your own settings file: copy `wrangler.jsonc` to `wrangler.local.jsonc`, which git ignores. In the copy, set the address in `routes`, such as `nexus.example.com` on a domain in your account, and set `NEXUS_LANGUAGE` to `ko` for a Korean page.
3. Deploy: run `npx wrangler login`, then `npm run deploy`. The first deploy creates the D1 database `corthex-nexus` and writes its ID into your settings file, and Cloudflare adds the address's DNS record and certificate. Until the next step, the address answers `403`.
4. Protect the Worker with Access. In the Cloudflare dashboard, go to **Workers & Pages**, select `corthex-nexus`, open the **Access** tab and select **Protect this Worker behind Access**. Choose **All traffic**, choose who can sign in (for yourself alone, **Cloudflare account**) and select **Apply Access**.
5. Check it: open the address in a private window. The Access sign-in comes first, then the hub page, which is empty until the first push.
6. Create a service token for `hub.py`. In **Zero Trust** › **Access controls** › **Service credentials** › **Service Tokens**, create one and copy its Client ID and Client Secret; the secret is shown only once. Then open the Access application that protects the Worker, under **Zero Trust** › **Access controls** › **Applications**, and add a policy with the action **Service Auth** that includes this token. Add it to that application rather than creating a second one for the same Worker, which can conflict with it.
7. On each machine that sends snapshots, set the address and the projects that may be sent in `~/.corthex/profile.json`:

   ```json
   { "nexus": { "url": "https://nexus.example.com", "push": ["acme-shop"] } }
   ```

   Put the token in the environment variables `CORTHEX_NEXUS_CLIENT_ID` and `CORTHEX_NEXUS_CLIENT_SECRET`, from your system's secret store, never in a file in a repository. Then run `hub.py push --dry-run`, and `hub.py push`.

Optional: to accept only that Access application, copy its **Application Audience (AUD) Tag** into `ACCESS_AUD` in your settings file and deploy again. Several tags can be given, separated by commas.

The dashboard names follow Cloudflare's documentation as of October 2026: [Cloudflare Access for Workers](https://developers.cloudflare.com/workers/configuration/cloudflare-access/), [service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/) and [Zero Trust setup](https://developers.cloudflare.com/cloudflare-one/setup/).

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
- To run it in the Workers runtime, add `"access": { "dev": { "aud": "local-test" } }` to `wrangler.local.jsonc`, run `npm run dev` and send with `hub.py push --url http://127.0.0.1:8787`. Without that block every request gets `403`, as on Cloudflare without Access. Remove the block before you deploy.

## Update and remove

- To update, pull the repository, compare `wrangler.jsonc` with your copy, then run `npm install` and `npm run deploy`.
- To remove it, `npx wrangler delete -c wrangler.local.jsonc` deletes the Worker and `npx wrangler d1 delete corthex-nexus` deletes the database with its snapshots. Then delete the Access application and the service token under **Zero Trust** › **Access controls**.
