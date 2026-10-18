// Release gate, run before every `vite build` (package.json "prebuild"): the data files about to
// be published must be exactly the ones `atlas validate` checked (sha256 in validation.json), with
// no blocking finding, and the independent recomputation (verify/recompute.py) must agree with
// them. Any host that builds the site goes through this; ATLAS_SKIP_DATA_CHECK=1 skips it for
// local experiments and says so loudly.
import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const data = join(web, "public", "data");
const report = join(web, "..", "verify", "recompute_report.json");
const fail = (msg) => {
  console.error(`\n✗ data check failed: ${msg}\n  Run \`make verify\` (or \`make release\`) first.\n`);
  process.exit(1);
};

if (process.env.ATLAS_SKIP_DATA_CHECK === "1") {
  console.warn("\n!!! ATLAS_SKIP_DATA_CHECK=1: building WITHOUT the data check. Do not publish this build.\n");
  process.exit(0);
}

const vpath = join(data, "validation.json");
if (!existsSync(vpath)) fail("web/public/data/validation.json is missing (`atlas validate`).");
const v = JSON.parse(readFileSync(vpath, "utf8"));
if (!v.ok) {
  const blocks = (v.findings ?? []).filter((f) => f.severity === "block");
  fail(`${blocks.length} blocking finding(s), e.g. ${blocks.slice(0, 3).map((f) => `${f.check} ${f.iso3 ?? ""}/${f.group ?? ""}: ${f.detail}`).join("; ")}`);
}
const sha = (p) => createHash("sha256").update(readFileSync(p)).digest("hex");
for (const [name, hash] of Object.entries(v.files ?? {})) {
  const p = join(data, name);
  if (!existsSync(p)) fail(`${name} was validated but is missing.`);
  if (sha(p) !== hash) fail(`${name} changed after validation (re-run \`atlas validate\`).`);
}
for (const name of ["ssr.json", "items.json", "trade.json", "seasons.json", "regions.json", "countries.geojson"]) {
  if (!(name in (v.files ?? {}))) fail(`${name} is not covered by validation.json.`);
}

if (!existsSync(report)) fail("verify/recompute_report.json is missing (`make verify`).");
const r = JSON.parse(readFileSync(report, "utf8"));
const checked = r.published_sha256 ?? {};
for (const name of ["ssr.json", "items.json", "trade.json", "seasons.json", "regions.json"]) {
  if (checked[name] && checked[name] !== v.files[name]) {
    fail(`the independent recomputation checked a different ${name} (re-run verify/recompute.py).`);
  }
}
if (!r.ok) fail(`the independent recomputation found ${r.n_mismatches ?? "some"} mismatch(es); see verify/recompute_report.json.`);

console.log(`✓ data check: ${Object.keys(v.files).length} files validated, ${v.counts?.warn ?? 0} warnings for review, recomputation agrees.`);
