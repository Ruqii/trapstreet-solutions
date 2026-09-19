/**
 * Pi's half of the same-tools board: the three shared tools, as a pi extension.
 *
 * Pi has no MCP ("intentionally does not include built-in MCP", its docs say),
 * so the tools are registered through its extension API instead. That is a
 * difference in plumbing, not in what the model is shown: the names,
 * descriptions and JSON schemas are read from tools.py's own `schema` output,
 * and every call shells back to the same file, so the text a tool returns here
 * is the text it returns under Claude Code and DSH.
 *
 * The names keep the mcp__bench__ prefix the other two harnesses' MCP clients
 * impose, so the tool list diffs byte for byte across all three.
 *
 * $BENCH_TOOLS is the path to tools.py, set by pi_run.py (the jail cannot read
 * this repo, so the copy in the case root is what runs).
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFileSync } from "node:child_process";

const TOOLS_PY = process.env.BENCH_TOOLS;
const PREFIX = "mcp__bench__";

type Definition = { name: string; description: string; inputSchema: Record<string, unknown> };

function definitions(): Definition[] {
  if (!TOOLS_PY) throw new Error("BENCH_TOOLS is not set: nothing to register");
  return JSON.parse(execFileSync("python3", [TOOLS_PY, "schema"], { encoding: "utf8" }));
}

export default function (pi: ExtensionAPI) {
  for (const tool of definitions()) {
    pi.registerTool({
      name: `${PREFIX}${tool.name}`,
      label: tool.name,
      description: tool.description,
      // The schema tools.py publishes, unchanged: a JSON Schema object is what
      // typebox produces anyway, and rewriting it here is how the two harnesses
      // would drift apart.
      parameters: tool.inputSchema as never,
      async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
        const argv = [TOOLS_PY as string, "call", tool.name, JSON.stringify(params ?? {})];
        const options = { encoding: "utf8" as const, cwd: ctx?.cwd ?? process.cwd(), maxBuffer: 64 * 1024 * 1024 };
        let text: string;
        try {
          text = execFileSync("python3", argv, options);
        } catch (error) {
          // tools.py exits non-zero for a tool error and prints the message it
          // would print anywhere else; execFileSync throws on that status, and
          // the model must still be given that text rather than a node stack.
          const output = (error as { stdout?: string }).stdout;
          if (typeof output !== "string") throw error;
          text = output;
        }
        return { content: [{ type: "text", text: text.replace(/\n$/, "") }], details: {} };
      },
    });
  }
}
