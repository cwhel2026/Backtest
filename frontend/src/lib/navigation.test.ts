import { describe, expect, it } from "vitest";
import { isNavActive } from "./navigation";

describe("isNavActive", () => {
  it("matches home exactly", () => {
    expect(isNavActive("/", "/")).toBe(true);
    expect(isNavActive("/strategies", "/")).toBe(false);
  });

  it("matches nested routes", () => {
    expect(isNavActive("/backtests/run", "/backtests")).toBe(true);
    expect(isNavActive("/market-data/health", "/market-data")).toBe(true);
  });
});