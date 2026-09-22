// How much headroom is left? If the three arms that tie at 0.74 fail the SAME
// cases, the remaining quarter is not "harder for weak models" -- it is where
// this material stops separating anyone, and that is the ceiling the board
// will hit as models improve.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const WEB = "/Users/zhengruqi/Documents/Projects/trapstreet-web/apps/web";
const env = readFileSync(`${WEB}/.env.local`, "utf8");
const url = env.match(/^DATABASE_URL=(.*)$/m)?.[1].trim().replace(/^["']|["']$/g, "");
if (!(url?.match(/@([^/]*)/)?.[1] ?? "").includes("ep-super-queen")) throw new Error("not UAT");
const require = createRequire(`${WEB}/package.json`);
const { neon } = require("@neondatabase/serverless");
const sql = neon(url);

const NAMES = {
  rs_aobcib9q29y6qpwz: "jev",
  rs_9zhhjk1bvhkn6rsy: "qwen-27b",
  rs_e2eo4hklcvbjex23: "qwen-35b-moe",
  rs_e198xgv040ravazi: "von",
  rs_dhy3homzh5iomkku: "word-overlap",
};
const got = {};
for (const id of Object.keys(NAMES)) {
  const rows = await sql`select case_key, platform_score from run_case_states
                         where session_id = ${id} and platform_score is not null`;
  got[NAMES[id]] = new Map(rows.map((x) => [x.case_key, Number(x.platform_score) > 0]));
}
const keys = [...got.jev.keys()];
const top3 = ["jev", "qwen-27b", "qwen-35b-moe"];

let allRight = 0, allWrong = 0, split = 0;
const unionRight = new Set();
for (const k of keys) {
  const v = top3.map((n) => got[n].get(k));
  if (v.every(Boolean)) allRight++;
  else if (v.every((x) => !x)) allWrong++;
  else split++;
  if (v.some(Boolean)) unionRight.add(k);
}
console.log(`n = ${keys.length}\n`);
console.log(`all three right : ${allRight}  (${(allRight / keys.length * 100).toFixed(1)}%)`);
console.log(`they disagree   : ${split}  (${(split / keys.length * 100).toFixed(1)}%)`);
console.log(`all three wrong : ${allWrong}  (${(allWrong / keys.length * 100).toFixed(1)}%)`);
console.log(`\noracle over the three (best possible pick per case): ${(unionRight.size / keys.length).toFixed(4)}`);

// of the cases all three miss, how many does anything else get?
let rescuedByVon = 0, rescuedByLexical = 0;
for (const k of keys) {
  if (top3.every((n) => !got[n].get(k))) {
    if (got.von.get(k)) rescuedByVon++;
    if (got["word-overlap"].get(k)) rescuedByLexical++;
  }
}
console.log(`\nof the ${allWrong} nobody-in-the-top-three gets:`);
console.log(`   von gets          ${rescuedByVon}`);
console.log(`   word-overlap gets ${rescuedByLexical}`);
