import assert from "node:assert/strict";
import { dollarsToMinor, minorToDollars } from "../src/lib/money.ts";

assert.equal(dollarsToMinor("25.50"), 2550);
assert.equal(dollarsToMinor("25"), 2500);
assert.equal(dollarsToMinor("0.05"), 5);
assert.equal(dollarsToMinor("0.5"), 50);
assert.equal(minorToDollars(2550), "25.50");
assert.equal(minorToDollars(5), "0.05");
assert.throws(() => dollarsToMinor("25.555"));
assert.throws(() => dollarsToMinor("-1.00"));
assert.throws(() => dollarsToMinor("abc"));

console.log("money conversion tests passed");
