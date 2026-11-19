import { describe, expect, it } from "vitest";
import { isNavActive, latencyLabel } from "./navigation";

describe("isNavActive", () => {
  it("matches home exactly", () => {
    expect(isNavActive("/", "/")).toBe(true);
    expect(isNavActive("/scanner", "/")).toBe(false);
  });

  it("matches nested routes", () => {
    expect(isNavActive("/backtests/run", "/backtests")).toBe(true);
    expect(isNavActive("/paper-trading/abc", "/paper-trading")).toBe(true);
    expect(isNavActive("/strategy-lab", "/strategy-lab")).toBe(true);
  });
});

describe("latencyLabel", () => {
  it("never claims live for replay", () => {
    expect(latencyLabel("historical_replay")).toContain("Replay");
    expect(latencyLabel("delayed")).toBe("Delayed");
  });
});