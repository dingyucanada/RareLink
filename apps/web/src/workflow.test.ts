import { describe, expect, it } from "vitest";
import { stages, statusIndex } from "./workflow";

describe("research workflow", () => {
  it("keeps the report stage after all controlled execution stages", () => {
    expect(statusIndex("DRAFT")).toBe(0);
    expect(statusIndex("REPORT_READY")).toBe(stages.length - 1);
    expect(statusIndex("TRAINING_RUNNING")).toBeGreaterThan(statusIndex("CONTRACT_LOCKED"));
  });
});

