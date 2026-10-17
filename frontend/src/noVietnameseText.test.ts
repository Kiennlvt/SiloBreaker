/// <reference types="vite/client" />
import { describe, expect, it } from "vitest";

// Every UI string must be English. Matches Vietnamese letters (a-breve, a/e/o-circumflex, d-stroke,
// o/u-horn and vowels with tone marks, precomposed or as combining marks), but not typographic
// symbols such as … · → — × ↑ ↓ •. Written as escapes so this file passes the same search.
const VIETNAMESE = new RegExp(
  "[" +
    "\u00e0\u00e1\u1ea1\u1ea3\u00e3\u00e2\u1ea7\u1ea5\u1ead\u1ea9\u1eab\u0103\u1eb1\u1eaf\u1eb7\u1eb3\u1eb5" +
    "\u00e8\u00e9\u1eb9\u1ebb\u1ebd\u00ea\u1ec1\u1ebf\u1ec7\u1ec3\u1ec5" +
    "\u00ec\u00ed\u1ecb\u1ec9\u0129" +
    "\u00f2\u00f3\u1ecd\u1ecf\u00f5\u00f4\u1ed3\u1ed1\u1ed9\u1ed5\u1ed7\u01a1\u1edd\u1edb\u1ee3\u1edf\u1ee1" +
    "\u00f9\u00fa\u1ee5\u1ee7\u0169\u01b0\u1eeb\u1ee9\u1ef1\u1eed\u1eef" +
    "\u1ef3\u00fd\u1ef5\u1ef7\u1ef9\u0111" +
    "\u0300\u0301\u0303\u0309\u0323" +
    "]",
  "iu",
);

const sources = import.meta.glob<string>(["./**/*.{ts,tsx}", "!./**/*.test.*"], {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("UI text", () => {
  it("recognises Vietnamese letters and ignores typographic symbols", () => {
    for (const word of ["Th\u1eed l\u1ea1i", "T\u1ea3i l\u1ea1i", "\u0111", "\u01af", "\u0103", "\u01a1"]) {
      expect(word).toMatch(VIETNAMESE);
    }
    expect("… · → — × ↑ ↓ •").not.toMatch(VIETNAMESE);
  });

  it("contains no Vietnamese text in frontend/src", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(0);
    const violations: string[] = [];
    for (const [file, text] of Object.entries(sources)) {
      text.split(/\r?\n/).forEach((line, i) => {
        if (VIETNAMESE.test(line)) violations.push(`src/${file.slice(2)}:${i + 1}: ${line.trim()}`);
      });
    }
    expect(violations, `Vietnamese text found:\n${violations.join("\n")}`).toEqual([]);
  });
});
