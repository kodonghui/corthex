import { Problem } from "./problem.js";
import { inputFailure } from "./input-check.js";

export async function jsonBody(request, schema, snapshot = false) {
  if (!/^application\/json\s*(?:;|$)/i.test(request.headers.get("Content-Type") || "")) throw new Problem("json_required", "send application/json");
  const limit = snapshot ? 1024 * 1024 : 256 * 1024;
  const large = () => new Problem(snapshot ? "snapshot_too_large" : "body_too_large", "the request body is too large", { limit });
  if (Number(request.headers.get("Content-Length")) > limit) throw large();
  const chunks = [];
  let size = 0;
  const reader = request.body?.getReader();
  if (reader) for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) { try { await reader.cancel(); } catch { /* Refusal survives stream cancellation failure. */ } throw large(); }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let at = 0;
  for (const chunk of chunks) { bytes.set(chunk, at); at += chunk.byteLength; }
  let text, data;
  const invalid = (detail, field = "body") => new Problem(snapshot ? "invalid_snapshot" : "invalid_request", detail, { field });
  try { text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); }
  catch { throw invalid("the body is not UTF-8 text"); }
  try { data = JSON.parse(text); }
  catch { throw invalid("the body is not JSON"); }
  if (schema) {
    const failure = inputFailure(data, schema);
    const field = failure?.path.replace(/^body\./, "");
    if (failure?.reason === "maxLength" && !snapshot && ["text", "quote", "reason", "change", "source_text", "words", "link", "pull_request"].includes(field)) throw new Problem("text_too_long", "a text is too long", { field, limit: failure.limit });
    if (failure) throw invalid("the body is not in its required form", field);
  }
  return { data, text, size };
}
