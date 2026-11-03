import { inputFailure } from "./input-check.js";
import { Problem } from "./problem.js";

const SOURCE = { "01-domain": "DomainSource", "05-erd": "ErdSource", "07-sitemap": "SitemapSource" };
const invalid = (field) => { field = field.replace(/^snapshot\./, ""); return new Problem("invalid_snapshot", `the snapshot has a bad ${field}`, { field }); };
const timestamp = (value) => Date.parse(value);

// Called after JSON decoding. Snapshot fields that the server does not yet
// understand survive; only pictures move to the separate pictures table.
export function readSnapshot02(data, nowMs) {
  const failure = inputFailure(data, "Snapshot02", "snapshot");
  if (failure) throw invalid(failure.path);
  const generatedMs = timestamp(data.generated_at);
  if (generatedMs > nowMs + 600000) throw new Problem("clock_ahead", "the snapshot is dated in the future; check the device's clock");
  const repo = data.repos?.["."];
  const defaultCommit = repo?.default?.commit || null;
  const parts = new Set(["", ...(data.project.parts || [])]);
  const seen = new Set();
  for (let i = 0; i < data.pictures.length; i++) {
    const picture = data.pictures[i];
    const field = `pictures[${i}]`;
    if (!parts.has(picture.part)) throw invalid(field + ".part");
    if (!defaultCommit || picture.commit !== defaultCommit) throw invalid(field + ".commit");
    if (inputFailure(picture.source, SOURCE[picture.stage], field + ".source")) throw invalid(field + ".source");
    const key = JSON.stringify([picture.part, picture.stage]);
    if (seen.has(key)) throw invalid(field);
    seen.add(key);
    // A parent points into this picture's flat list, never another object or
    // a cycle. Keeping this bounded also prevents recursive renderer failure.
    if (picture.stage === "07-sitemap") {
      const screens = picture.source.screens;
      for (let at = 0; at < screens.length; at++) {
        const visited = new Set([at]);
        let parent = screens[at].parent;
        while (parent !== undefined) {
          if (parent >= screens.length || visited.has(parent)) throw invalid(field + ".source.screens.parent");
          visited.add(parent);
          parent = screens[parent].parent;
        }
      }
    }
  }
  for (let i = 0; i < (data.left_out || []).length; i++) {
    const entry = data.left_out[i];
    if (!parts.has(entry.part) || seen.has(JSON.stringify([entry.part, entry.stage]))) throw invalid(`left_out[${i}]`);
    seen.add(JSON.stringify([entry.part, entry.stage]));
  }
  if (data.records.from === "repository" && (!defaultCommit || data.records.commit !== defaultCommit || !data.records.time)) throw invalid("records");
  const { pictures, ...stored } = data;
  return {
    name: data.project.name, generatedMs, generatedAt: data.generated_at,
    body: JSON.stringify(stored), data: stored, pictures, defaultCommit,
    repository: repo?.url || null,
  };
}
