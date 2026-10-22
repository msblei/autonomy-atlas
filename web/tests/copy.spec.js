// No factual number typed into the page text: figures come from the data (meta.claims, the
// indicators). The allow-list holds arithmetic examples and formatter output, not facts.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";

const ALLOWED = [
  "85% of 12 months is about 10 months", // worked example of the arithmetic
  "Of every 10 kg used here", // "of every 10 kg", a proportion
  "Of every 10 kg of ${foodName()}", // the same, in the tour
  '"<1 kg"', // formatter output
  "* 100, tonnes: v", // code: a share in per cent next to a field named tonnes
];
const FIGURE = /\b\d[\d.,]*\s?(?:%|kg|g a day|million|thousand|tonnes|Mt|MB|foods)\b/;

for (const file of ["main.js", "tour.js"]) test(`no hard-coded factual figures in ${file} text`, () => {
  const src = readFileSync(new URL(`../src/${file}`, import.meta.url), "utf8");
  const facts = src.split("\n")
    .map((line, i) => [i + 1, line.trim()])
    .filter(([, l]) => !l.startsWith("//") && FIGURE.test(l.replace(/\/\/.*$/, "")))
    .filter(([, l]) => !ALLOWED.some((a) => l.includes(a)))
    .map(([n, l]) => `${n}: ${l}`);
  expect(facts).toEqual([]);
});
