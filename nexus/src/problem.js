// Stage 06 is the source of error names, statuses and titles. The tests compare
// these names with the contract itself. Details are written by the caller and
// must never contain stored text; neither details nor request values are logged.
export const ERRORS = Object.freeze({
  invalid_request: [400, "The request is not valid"],
  invalid_snapshot: [400, "The snapshot is not valid"],
  clock_ahead: [400, "The snapshot is dated in the future"],
  unknown_item: [400, "An item is not in the picture"],
  access_missing: [403, "Not checked by Cloudflare Access"],
  access_other_app: [403, "Checked for another application"],
  cross_site: [403, "A change from another site"],
  user_only: [403, "Only the user does this"],
  agent_only: [403, "Only the agent does this"],
  no_kind: [403, "This sign-in cannot write here"],
  not_found: [404, "Not found"],
  project_not_found: [404, "No such project"],
  space_not_found: [404, "No space for this project"],
  part_not_found: [404, "No such part"],
  picture_not_found: [404, "No picture yet"],
  comment_not_found: [404, "No such comment"],
  discrepancy_not_found: [404, "No such discrepancy"],
  proposal_not_found: [404, "No such proposal"],
  edit_not_found: [404, "No such reflection"],
  checkpoint_not_found: [404, "No such checkpoint"],
  entry_not_found: [404, "No such entry"],
  method_not_allowed: [405, "Method not allowed"],
  older_snapshot: [409, "The server holds a newer snapshot"],
  commit_not_replaced: [409, "The server holds another commit"],
  too_many_projects: [409, "No room for another project"],
  repository_mismatch: [409, "The space is bound to another repository"],
  comment_limit: [409, "No room for another comment"],
  reply_limit: [409, "No room for another reply"],
  proposal_limit: [409, "No room for another proposal"],
  reflection_limit: [409, "No room for another reflection"],
  space_full: [409, "The space is full"],
  comment_closed: [409, "The comment is closed"],
  proposal_not_open: [409, "The proposal is not open"],
  edit_state: [409, "The reflection is in another state"],
  pull_request_reported: [409, "A pull request holds this already"],
  pull_request_mismatch: [409, "Not the reported pull request"],
  claimed: [409, "Another session holds this"],
  entry_closed: [409, "The entry is closed"],
  checkpoint_recorded: [409, "The checkpoint is recorded"],
  checkpoint_withdrawn: [409, "The checkpoint is withdrawn"],
  write_id_reused: [409, "The write ID is taken"],
  snapshot_too_large: [413, "The snapshot is too large"],
  body_too_large: [413, "The request is too large"],
  text_too_long: [413, "The text is too long"],
  json_required: [415, "Send JSON"],
  internal: [500, "Something went wrong"],
});

export const COMMON_HEADERS = Object.freeze({
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "X-Robots-Tag": "noindex, nofollow",
  "Cross-Origin-Resource-Policy": "same-origin",
});

const EXTRA_FIELDS = new Set([
  "field", "limit", "items", "held_commit", "stored_at", "bound", "state",
  "pull_request", "ends_at", "why", "needs",
]);
const shorten = (text, length) => Array.from(String(text)).slice(0, length).join("");

export class Problem extends Error {
  constructor(code, detail, fields = {}, headers = {}) {
    if (!Object.hasOwn(ERRORS, code)) throw new TypeError("unknown problem code");
    const safeDetail = shorten(String(detail).replace(/\s+/gu, " ").trim(), 300);
    super(safeDetail);
    this.name = "Problem";
    this.code = code;
    this.status = ERRORS[code][0];
    this.title = ERRORS[code][1];
    this.fields = {};
    for (const [key, value] of Object.entries(fields)) {
      if (!EXTRA_FIELDS.has(key)) throw new TypeError("unknown problem member");
      this.fields[key] = value;
    }
    // The only per-error HTTP header stage 06 defines is Allow.
    this.headers = headers.Allow ? { Allow: headers.Allow } : {};
  }
}

export function traceId(request) {
  const ray = request?.headers?.get("Cf-Ray");
  if (ray && /^[0-9a-f]{16}(?:-[A-Z]{3})?$/.test(ray)) return ray;
  return Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => b.toString(16).padStart(2, "0")).join("");
}

export function problemDocument(request, failure) {
  const problem = failure instanceof Problem ? failure : new Problem("internal", "the server could not finish the request");
  return {
    title: problem.title, status: problem.status, detail: problem.message,
    code: problem.code, traceId: traceId(request), error: problem.message,
    ...problem.fields,
  };
}

export function problemResponse(request, failure) {
  const document = problemDocument(request, failure);
  // Unknown exception text, request headers, identities and stored text never
  // reach the log. The trace ID is the same one returned to the client.
  console.error("nexus", { kind: document.code, traceId: document.traceId });
  return new Response(request.method === "HEAD" ? null : JSON.stringify(document), {
    status: document.status,
    headers: {
      ...COMMON_HEADERS,
      "Content-Type": "application/problem+json",
      "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
      ...(failure instanceof Problem ? failure.headers : {}),
    },
  });
}
