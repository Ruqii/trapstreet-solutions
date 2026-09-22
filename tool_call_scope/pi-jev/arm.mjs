/**
 * pi-jev's own gate, on one case.
 *
 * The three sources in vendor/ are @y0usaf/pi-jev's, byte for byte -- their
 * sha256s are in vendor/SOURCES.sha256 against the published package. They are
 * copied rather than imported because Node refuses to strip types inside
 * node_modules, and copied rather than rewritten because the copy is the whole
 * fidelity claim.
 *
 * What runs is the product's own buildGateState -> askJev -> evaluateGate, at
 * its own shipped defaults (beyondScope 0.85, destructive 0.9, exfiltration
 * 0.7, impact 2.5). What is skipped is Pi's event plumbing: the tool-name
 * filter, which `bash` passes, and shadow/enforce, which is enforcement rather
 * than judgement. A flagged call prints ASK because that is what a user in
 * enforce mode is shown; shadow being the default is stated here, not scored.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { buildGateState, GATE_QUESTIONS, evaluateGate } from "./vendor/gate.ts";
import { askJev } from "./vendor/client.ts";
import { defaultJevConfig } from "./vendor/config.ts";

const manifest = JSON.parse(process.env.TRAP_MANIFEST);
const dir = manifest.inputs_dir;
const session = readFileSync(join(dir, "session.txt"), "utf8");
const command = readFileSync(join(dir, "pending_call.txt"), "utf8").trim();
const userRequest = session.split("[user]")[1]?.split("[assistant]")[0]?.trim() ?? "";

const apiKey = process.env.TYPESAFE_API_KEY;
if (!apiKey) { console.error("TYPESAFE_API_KEY unset"); process.exit(1); }

const config = defaultJevConfig();
config.apiKey = apiKey;
const state = buildGateState({
  cwd: "/work", toolName: "bash", input: { command },
  userRequest, maxStateChars: config.maxStateChars,
  argumentChars: config.gate.argumentChars,
});
const response = await askJev({
  state, questions: GATE_QUESTIONS, apiKey, model: config.model,
  endpoint: config.endpoint, timeoutMs: config.timeoutMs, retries: config.retries,
});
const v = evaluateGate(response, config);
console.log(`PI_JEV destructive=${v.destructive.toFixed(3)} exfiltration=${v.exfiltration.toFixed(3)}`
  + ` beyond_scope=${v.beyondScope.toFixed(3)} impact=${v.impact ?? "n/a"} mode=${config.gate.mode}`);
const tokens = response.usage?.input_tokens ?? 0;
if (tokens) console.log(`UNMETERED_COST_USD: ${(tokens * 0.042 / 1e6).toFixed(8)}`);
console.log(v.flagged ? "ASK" : "ALLOW");
