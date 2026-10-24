// Cloudflare Worker entry point. The page template is bundled as text (see
// the `rules` in wrangler.jsonc) and is a copy of the plugin's assets/hub.html.

import template from "./hub.html";
import { handle } from "./app.js";

export default {
  fetch(request, env, ctx) {
    return handle(request, env, ctx, template);
  },
};
