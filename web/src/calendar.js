// "How long would it last?": a self-sufficiency share read as months of the year. A share of p%
// means a year's own production covers p% of a year's use: p/100 × 12 months. A thought
// experiment (a year's production treated as one store, seasons ignored); see
// docs/methodology.md. The same share as a date ("runs out on 5 November") is kept for the
// sources page.

const DAY = 86_400_000;
const YEAR_START = Date.UTC(2023, 0, 1); // any non-leap year

// Map colour classes, from "runs out early" to "more than enough". Upper bounds in percent.
export const SEASONS = [
  { max: 50, color: "#b84a2a", label: "less than 6 months" },
  { max: 75, color: "#e39a5f", label: "6 to 9 months" },
  { max: 91.67, color: "#e6d49a", label: "9 to 11 months" },
  { max: 99.5, color: "#b5cf8c", label: "11 to 12 months" },
  { max: 104.17, color: "#6fae80", label: "the whole year" }, // < half a month spare
  { max: Infinity, color: "#2f6f4e", label: "more than enough" },
];

export function season(pct) {
  return SEASONS.find((s) => pct < s.max) ?? SEASONS[SEASONS.length - 1];
}

// Months of the year covered (0–12).
export function months(pct) {
  return (Math.max(0, Math.min(pct, 100)) / 100) * 12;
}

// Days of the year covered (0–365).
export function daysCovered(pct) {
  return Math.round((Math.max(0, Math.min(pct, 100)) / 100) * 365);
}

// As a date, counting from 1 January: "5 November"; null when it lasts the whole year.
export function lastDay(pct) {
  const d = daysCovered(pct);
  if (d >= 365) return null;
  return new Date(YEAR_START + Math.max(d - 1, 0) * DAY).toLocaleDateString("en-GB", {
    day: "numeric", month: "long", timeZone: "UTC",
  });
}

// Extra time beyond a year, in whole months (0 when there is none).
export function spareMonths(pct) {
  return pct > 100 ? Math.round(((pct - 100) / 100) * 12) : 0;
}

const half = (m) => {
  const r = Math.round(m * 2) / 2;
  return `${Math.floor(r)}${r % 1 ? "½" : ""}`;
};

// How long it lasts, as a noun phrase: "about 10 months", "about 6 weeks", "almost the whole
// year", "the whole year, with 3 months to spare", "2.5 years". `short` is for lists and labels.
export function lasts(pct, { short = false } = {}) {
  if (pct >= 200) return `${(pct / 100).toFixed(1)} years`;
  const spare = spareMonths(pct);
  if (spare >= 1) {
    if (short) return `year + ${spare} mo`;
    return `the whole year, with ${spare === 1 ? "a month" : `${spare} months`} to spare`;
  }
  if (pct >= 99.5) return short ? "whole year" : "the whole year";
  const m = months(pct);
  if (m >= 11.75) return short ? "almost a year" : "almost the whole year";
  if (m >= 1.75) {
    const n = half(m);
    return short ? `${n} months` : `about ${n} months`;
  }
  if (pct < 0.5) return short ? "none" : "none at all";
  const weeks = Math.round((pct / 100) * 52);
  if (weeks < 1) return short ? "a few days" : "only a few days";
  const w = `${weeks} week${weeks === 1 ? "" : "s"}`;
  return short ? w : `about ${w}`;
}

// "for about 10 months of the year" / "for the whole year, with 3 months to spare" / "for 2.5 years"
export function forHowLong(pct) {
  const s = lasts(pct);
  if (s === "none at all") return s;
  return /days|weeks|months$/.test(s) ? `for ${s} of the year` : `for ${s}`;
}

// A year as 12 month boxes, filled as far as the food lasts (marked with a triangle); a surplus
// continues as a lighter bar. `small` is a bare bar for lists.
export function strip(pct, { small = false } = {}) {
  const W = small ? 120 : 300;
  const top = small ? 0 : 9; // room for the marker
  const barH = small ? 10 : 22;
  const H = small ? barH : top + barH + 16;
  const yearW = small ? W : W / 1.25; // full size leaves a quarter year for the surplus
  const color = season(pct).color;
  const fill = (Math.min(pct, 100) / 100) * yearW;
  const over = Math.min(Math.max(pct - 100, 0) / 100, small ? 0 : 0.25) * yearW;
  const w = yearW / 12;
  const cells = small
    ? `<rect x="0" y="0" width="${W}" height="${barH}" rx="5" class="cell" />`
    : Array.from({ length: 12 }, (_, i) =>
      `<rect x="${(i * w).toFixed(1)}" y="${top}" width="${(w - 1.5).toFixed(1)}" height="${barH}" rx="2" class="cell" />`,
    ).join("") + [[0, "0"], [6, "6 months"], [12, "12"]]
      .map(([i, t]) => `<text x="${(i * w - (i === 12 ? 1.5 : 0)).toFixed(1)}" y="${top + barH + 13}" class="m"
        text-anchor="${i === 0 ? "start" : i === 12 ? "end" : "middle"}">${t}</text>`).join("");
  const marker = !small && pct < 99.5
    ? `<path d="M${fill.toFixed(1)},${top - 1} l-5,-7 h10 z" class="mark" />`
    : "";
  const spill = over > 0
    ? `<rect x="${yearW.toFixed(1)}" y="${top + 4}" width="${over.toFixed(1)}" height="${barH - 8}" rx="2" fill="${color}" opacity=".5" />`
    : "";
  return `<svg class="strip${small ? " small" : ""}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
      role="img" aria-label="Enough ${forHowLong(pct)}">
    ${cells}
    <rect x="0" y="${top}" width="${fill.toFixed(1)}" height="${barH}" rx="${small ? 5 : 2}" fill="${color}" />
    ${spill}${marker}
  </svg>`;
}
