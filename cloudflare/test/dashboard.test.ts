import { describe, expect, it } from "vitest";
import { dashboardPeriodStarts, decodeFeedCursor, encodeFeedCursor } from "../src/dashboard";

describe("dashboard helpers", () => {
  it("builds Istanbul day, week, month and year boundaries", () => {
    expect(dashboardPeriodStarts(new Date("2026-07-20T18:30:00Z"))).toEqual({
      today: "2026-07-19 21:00:00",
      week: "2026-07-19 21:00:00",
      month: "2026-06-30 21:00:00",
      year: "2025-12-31 21:00:00",
    });
  });

  it("round-trips feed cursors", () => {
    const cursor = {
      at: "2026-07-20T17:12:50.000Z",
      kind: "tweet",
      id: 42,
    };
    expect(decodeFeedCursor(encodeFeedCursor(cursor))).toEqual(cursor);
    expect(decodeFeedCursor("broken")).toBeNull();
  });
});
