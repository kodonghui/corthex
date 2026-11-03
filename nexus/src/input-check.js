// Small validator for the input subset of JSON Schema that stage 06 uses.
// No coercion, defaults, field stripping or network reference resolution.
import { INPUT_SCHEMAS } from "./input-schemas.js";

const own = (value, name) => Object.hasOwn(value, name);
const object = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const length = (value) => Array.from(value).length;
const types = {
  object, array: Array.isArray, string: (value) => typeof value === "string",
  boolean: (value) => typeof value === "boolean", number: Number.isFinite,
  integer: Number.isInteger, null: (value) => value === null,
};

const normalized = new WeakMap();
const compiled = new WeakSet();
const annotations = new Set(["$ref", "description", "title", "default", "example", "examples"]);
function prepare(schema) {
  if (typeof schema === "string") {
    if (!own(INPUT_SCHEMAS, schema)) throw new Error("unknown input schema");
    schema = INPUT_SCHEMAS[schema];
  }
  if (compiled.has(schema)) return schema;
  if (normalized.has(schema)) return normalized.get(schema);
  if (schema.$ref) {
    const match = schema.$ref.match(/^#\/components\/schemas\/([A-Za-z0-9]+)$/);
    if (!match) throw new Error("non-local input schema");
    const target = prepare(match[1]);
    const siblings = Object.fromEntries(Object.entries(schema).filter(([name]) => !annotations.has(name)));
    const result = Object.keys(siblings).length ? prepare({ allOf: [target, siblings] }) : target;
    normalized.set(schema, result);
    return result;
  }
  const result = { ...schema, hasConst: own(schema, "const") };
  normalized.set(schema, result); compiled.add(result);
  for (const name of ["allOf", "anyOf", "oneOf"]) if (schema[name]) result[name] = schema[name].map(prepare);
  if (schema.not) result.not = prepare(schema.not);
  if (schema.items) result.items = prepare(schema.items);
  if (schema.properties) result.properties = Object.fromEntries(Object.entries(schema.properties).map(([name, child]) => [name, prepare(child)]));
  if (object(schema.additionalProperties)) result.additionalProperties = prepare(schema.additionalProperties);
  if (schema.pattern) result.expression = new RegExp(schema.pattern, "u");
  return result;
}
// Resolve local references and compile patterns once at isolate startup. The
// request path performs no schema copying, function generation or evaluation.
for (const schema of Object.values(INPUT_SCHEMAS)) prepare(schema);

function format(value, name) {
  if (name === "date" || name === "date-time") {
    const match = /^(\d{4})-(\d{2})-(\d{2})(.*)$/.exec(value);
    if (!match) return false;
    const [, year, month, day, rest] = match;
    const leap = +year % 400 === 0 || (+year % 4 === 0 && +year % 100 !== 0);
    const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][+month - 1];
    if (+month < 1 || +month > 12 || +day < 1 || +day > days) return false;
    if (name === "date") return rest === "";
    return /^[Tt](?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](?:\.[0-9]+)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$/.test(rest) && Number.isFinite(Date.parse(value));
  }
  if (name === "uri") {
    try { return Boolean(new URL(value).protocol) && !/\s/u.test(value); }
    catch { return false; }
  }
  throw new Error("unimplemented input format");
}

export function inputFailure(value, schema, path = "body") {
  const failure = check(value, prepare(schema));
  return failure ? at(failure, path) : null;
}

function at(failure, prefix) {
  failure.path = prefix + (failure.path ? (failure.path.startsWith("[") ? "" : ".") + failure.path : "");
  return failure;
}

function check(value, schema) {
  // Paths are assembled only on refusal, not once per field of a valid 1 MiB
  // snapshot. This keeps successful validation free of those string copies.
  const path = "";
  if (schema.allOf) {
    for (const entry of schema.allOf) {
      const failed = check(value, entry);
      if (failed) return failed;
    }
  }
  if (schema.oneOf && schema.oneOf.filter((entry) => !check(value, entry)).length !== 1) return { path, reason: "shape" };
  if (schema.anyOf && !schema.anyOf.some((entry) => !check(value, entry))) return { path, reason: "shape" };
  if (schema.not && !check(value, schema.not)) return { path, reason: "shape" };
  if (schema.hasConst && value !== schema.const) return { path, reason: "value" };
  if (schema.enum && !schema.enum.includes(value)) return { path, reason: "value" };
  if (schema.type && (typeof schema.type === "string" ? !types[schema.type]?.(value) : !schema.type.some((name) => types[name]?.(value)))) return { path, reason: "type" };
  if (typeof value === "string") {
    if (schema.maxLength !== undefined && value.length > schema.maxLength && length(value) > schema.maxLength) return { path, reason: "maxLength", limit: schema.maxLength };
    if (schema.minLength !== undefined && (value.length < schema.minLength || (schema.minLength > 1 && length(value) < schema.minLength))) return { path, reason: "minLength" };
    if (schema.expression && !schema.expression.test(value)) return { path, reason: "pattern" };
    if (schema.format && !format(value, schema.format)) return { path, reason: "format" };
  }
  if (typeof value === "number") {
    if (schema.minimum !== undefined && value < schema.minimum) return { path, reason: "minimum" };
    if (schema.maximum !== undefined && value > schema.maximum) return { path, reason: "maximum" };
  }
  if (Array.isArray(value)) {
    if (schema.maxItems !== undefined && value.length > schema.maxItems) return { path, reason: "maxItems", limit: schema.maxItems };
    if (schema.minItems !== undefined && value.length < schema.minItems) return { path, reason: "minItems" };
    if (schema.uniqueItems && new Set(value.map((entry) => JSON.stringify(entry))).size !== value.length) return { path, reason: "uniqueItems" };
    if (schema.items) for (let i = 0; i < value.length; i++) {
      const failed = check(value[i], schema.items);
      if (failed) return at(failed, `[${i}]`);
    }
  }
  if (object(value)) {
    for (const name of schema.required || []) if (!own(value, name)) return { path: name, reason: "required" };
    if (schema.maxProperties !== undefined && Object.keys(value).length > schema.maxProperties) return { path, reason: "maxProperties" };
    if (!schema.properties && schema.additionalProperties === undefined) return null;
    for (const name of Object.keys(value)) {
      const entry = value[name];
      if (schema.properties && own(schema.properties, name)) {
        const failed = check(entry, schema.properties[name]);
        if (failed) return at(failed, name);
      } else if (schema.additionalProperties === false) return { path, reason: "unknown field" };
      else if (object(schema.additionalProperties)) {
        const failed = check(entry, schema.additionalProperties);
        if (failed) return at(failed, name);
      }
    }
  }
  return null;
}
