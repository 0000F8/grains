// Self-contained local dev runner for Node agents (used by `grains dev`).
// Reads a task JSON from stdin, runs the user's handler with a minimal Task,
// prints exactly one result JSON line. No grains-sdk dependency required.
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { existsSync } from "node:fs";
import { join } from "node:path";

function makeTask(id, text, payload) {
  const charges = [];
  return {
    id, text, payload,
    reply(t, data = {}) { return { text: String(t), data }; },
    charge(value, currency = "USDC") {
      if (typeof value !== "string") throw new TypeError("charge value must be a decimal string");
      const c = { value, currency };
      charges.push(c);
      return c;
    },
    _charges: charges,
  };
}

async function main() {
  const [appDir, entrypoint] = process.argv.slice(2);
  const [mod, func] = entrypoint.split(":");
  let file = null;
  for (const ext of [".mjs", ".js"]) {
    const p = join(appDir, mod + ext);
    if (existsSync(p)) { file = p; break; }
  }
  if (!file) { process.stdout.write(JSON.stringify({ status: "failed", error: `entrypoint file for ${mod} not found` }) + "\n"); return; }

  const input = JSON.parse(readFileSync(0, "utf8") || "{}");
  const task = makeTask(input.task_id || "dev", input.text || "", input.payload || {});
  try {
    const m = await import(pathToFileURL(file).href);
    const handler = m[func];
    if (typeof handler !== "function") throw new Error(`export '${func}' is not a function`);
    let result = await handler(task);
    if (result == null) result = task._lastReply ?? { text: "", data: {} };
    if (typeof result === "string") result = { text: result, data: {} };
    process.stdout.write(JSON.stringify({
      status: "done",
      reply: { text: String(result.text ?? ""), data: result.data ?? {} },
      charges: task._charges,
    }) + "\n");
  } catch (e) {
    process.stdout.write(JSON.stringify({ status: "failed", error: String(e && e.message || e) }) + "\n");
  }
}
main();
