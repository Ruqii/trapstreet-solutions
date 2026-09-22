// Paired comparison of every published arm against the top one, over the same
// 1500 cases. McNemar's exact-ish test on the discordant pairs: b = cases the
// top arm got right and the other wrong, c = the reverse. Normal approximation
// is fine at these counts (b + c is in the hundreds).
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
const WEB = "/Users/zhengruqi/Documents/Projects/trapstreet-web/apps/web";
const env = readFileSync(`${WEB}/.env.local`, "utf8");
const url = env.match(/^DATABASE_URL=(.*)$/m)?.[1].trim().replace(/^["']|["']$/g, "");
if (!(url?.match(/@([^/]*)/)?.[1] ?? "").includes("ep-super-queen")) throw new Error("not UAT");
const require = createRequire(`${WEB}/package.json`);
const { neon } = require("@neondatabase/serverless");
const sql = neon(url);

const runs = await sql`
  select s.id, s.platform_score as sc,
         coalesce(s.context->'identity'->>'name', s.context->'model'->'declared'->0->>'model') as nm
  from run_sessions s join task_versions tv on tv.id = s.task_version_id
  where tv.task_id = 'cve-weakness-class' and s.report_status = 'published'
  order by s.platform_score desc`;

const byRun = new Map();
for (const r of runs) {
  const rows = await sql`
    select case_key, platform_score from run_case_states
    where session_id = ${r.id} and platform_score is not null`;
  byRun.set(r.id, new Map(rows.map((x) => [x.case_key, Number(x.platform_score)])));
  console.log(`${String(r.nm).padEnd(46)} ${String(r.sc).padEnd(7)} cases=${rows.length}`);
}

const erf = (x) => { // Abramowitz-Stegun 7.1.26
  const s = Math.sign(x); x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return s * y;
};
const twoSidedP = (z) => 1 - erf(Math.abs(z) / Math.SQRT2);

const top = runs[0];
console.log(`\npaired against ${top.nm} (${top.sc}), n = 1500 shared cases\n`);
for (const r of runs.slice(1)) {
  const A = byRun.get(top.id), B = byRun.get(r.id);
  let b = 0, c = 0, n = 0;
  for (const [k, va] of A) {
    const vb = B.get(k);
    if (vb === undefined) continue;
    n++;
    if (va > 0 && vb === 0) b++;
    else if (va === 0 && vb > 0) c++;
  }
  const z = (b - c) / Math.sqrt(Math.max(b + c, 1));
  const p = twoSidedP(z);
  const diff = (b - c) / n;
  console.log(
    `${String(r.nm).padEnd(46)} Δ=${(diff * 100).toFixed(2).padStart(6)} pts  ` +
    `b=${String(b).padStart(4)} c=${String(c).padStart(4)}  z=${z.toFixed(2).padStart(6)}  ` +
    `p=${p < 1e-4 ? "<1e-4" : p.toFixed(4)}`);
}
