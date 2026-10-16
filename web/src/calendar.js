// "Running-out day": a self-sufficiency share read as a date. If a country ate only what its own
// farms produce, starting on 1 January, a share of p% lasts p% of 365 days. A thought experiment
// (stores spread evenly over the year, seasons ignored); see docs/methodology.md.

const DAY = 86_400_000;
const YEAR_START = Date.UTC(2023, 0, 1); // any non-leap year
const MONTHS = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"];

// Map colour classes, from "runs out early" to "more than enough". Upper bounds in percent.
export const SEASONS = [
  { max: 50, color: "#b84a2a", label: "runs out before July" },
  { max: 75, color: "#e39a5f", label: "runs out July–September" },
  { max: 92, color: "#e6d49a", label: "runs out October–November" },
  { max: 99.5, color: "#b5cf8c", label: "runs out in December" },
  { max: 104.17, color: "#6fae80", label: "lasts the whole year" }, // < half a month spare
  { max: Infinity, color: "#2f6f4e", label: "more than enough" },
];

export function season(pct) {
  return SEASONS.find((s) => pct < s.max) ?? SEASONS[SEASONS.length - 1];
}

// Days of the year covered (0–365).
export function daysCovered(pct) {
  return Math.round((Math.max(0, Math.min(pct, 100)) / 100) * 365);
}

// Last day with food, e.g. "23 November"; null when it lasts the whole year.
export function lastDay(pct, { short = false } = {}) {
  const d = daysCovered(pct);
  if (d >= 365) return null;
  return new Date(YEAR_START + Math.max(d - 1, 0) * DAY).toLocaleDateString("en-GB", {
    day: "numeric", month: short ? "short" : "long", timeZone: "UTC",
  });
}

// Extra time beyond a year, in whole months (0 when there is none).
export function spareMonths(pct) {
  return pct > 100 ? Math.round(((pct - 100) / 100) * 12) : 0;
}

// "until 23 November" / "the whole year" / "the whole year, with 3 months to spare" / "2.4 years"
export function lasts(pct, { short = false } = {}) {
  if (pct >= 200) return `${(pct / 100).toFixed(1)} years`;
  const spare = spareMonths(pct);
  if (spare >= 1) {
    if (short) return `all year +${spare} mo`;
    return `the whole year, with ${spare === 1 ? "a month" : `${spare} months`} to spare`;
  }
  if (pct >= 99.5) return short ? "all year" : "the whole year";
  if (daysCovered(pct) < 3) return short ? "a few days" : "only a few days";
  return `until ${lastDay(pct, { short })}`;
}

// A year as a strip of 12 months, filled up to the running-out day (marked with a triangle);
// a surplus continues past December as a lighter bar. `small` is a bare bar for lists.
export function strip(pct, { small = false } = {}) {
  const W = small ? 120 : 300;
  const top = small ? 0 : 9; // room for the marker
  const barH = small ? 10 : 22;
  const H = small ? barH : top + barH + 16;
  const yearW = small ? W : W / 1.25; // full size leaves a quarter year after December
  const color = season(pct).color;
  const fill = (Math.min(pct, 100) / 100) * yearW;
  const over = Math.min(Math.max(pct - 100, 0) / 100, small ? 0 : 0.25) * yearW;
  const cells = small
    ? `<rect x="0" y="0" width="${W}" height="${barH}" rx="5" class="cell" />`
    : MONTHS.map((m, i) => {
      const w = yearW / 12;
      const x = i * w;
      return `<rect x="${x.toFixed(1)}" y="${top}" width="${(w - 1.5).toFixed(1)}" height="${barH}" rx="2" class="cell" />
        <text x="${(x + w / 2).toFixed(1)}" y="${top + barH + 13}" class="m">${m}</text>`;
    }).join("");
  const marker = !small && pct < 99.5
    ? `<path d="M${fill.toFixed(1)},${top - 1} l-5,-7 h10 z" class="mark" />`
    : "";
  const spill = over > 0
    ? `<rect x="${yearW.toFixed(1)}" y="${top + 4}" width="${over.toFixed(1)}" height="${barH - 8}" rx="2" fill="${color}" opacity=".5" />`
    : "";
  return `<svg class="strip${small ? " small" : ""}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
      role="img" aria-label="Lasts ${lasts(pct)}">
    ${cells}
    <rect x="0" y="${top}" width="${fill.toFixed(1)}" height="${barH}" rx="${small ? 5 : 2}" fill="${color}" />
    ${spill}${marker}
  </svg>`;
}
