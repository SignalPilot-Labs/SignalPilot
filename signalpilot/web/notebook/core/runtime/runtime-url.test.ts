import { describe, expect, it } from "vitest";
import { RuntimeManager } from "./runtime";

describe("RuntimeManager URL bases", () => {
  it("keeps a query string on the configured URL intact", () => {
    const rm = new RuntimeManager({
      url: "http://gateway.test/notebook/sid-1?kiosk=true",
      lazy: false,
    });
    expect(rm.httpURL.toString()).toBe(
      "http://gateway.test/notebook/sid-1/?kiosk=true",
    );
  });

  it("drops the query string from the REST base so paths join cleanly", () => {
    const rm = new RuntimeManager({
      url: "http://gateway.test/notebook/sid-1?kiosk=true",
      lazy: false,
    });
    expect(rm.httpBaseURL.toString()).toBe(
      "http://gateway.test/notebook/sid-1/",
    );
  });

  it("leaves a plain URL unchanged apart from the trailing slash", () => {
    const rm = new RuntimeManager({
      url: "http://gateway.test/notebook/sid-1",
      lazy: false,
    });
    expect(rm.httpBaseURL.toString()).toBe(
      "http://gateway.test/notebook/sid-1/",
    );
  });
});
