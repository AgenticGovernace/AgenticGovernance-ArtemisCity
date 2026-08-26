import { bridgeCodeToHttpStatus } from "../lib/pythonBridge";

describe("bridgeCodeToHttpStatus", () => {
  test.each([
    ["MEMORY_IDEMPOTENCY_CONFLICT", 409],
    ["MEMORY_STORAGE_UNAVAILABLE", 503],
    ["MEMORY_DATABASE_CONFIGURATION_ERROR", 503],
    ["MEMORY_DELETE_UNSUPPORTED", 409],
  ])("maps %s to %i", (code, expectedStatus) => {
    expect(bridgeCodeToHttpStatus(code)).toBe(expectedStatus);
  });

  test("keeps unknown bridge failures internal", () => {
    expect(bridgeCodeToHttpStatus("UNRECOGNIZED_CODE")).toBe(500);
  });
});
