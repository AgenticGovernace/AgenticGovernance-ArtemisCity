import express, { NextFunction, Request, Response } from "express";
import request from "supertest";

import { rateLimit } from "../middleware/auth";

describe("API rate limiting", () => {
  it("counts a long-running request once and returns retry guidance at the boundary", async () => {
    const app = express();
    const key = `rate-limit-test-${Date.now()}-${Math.random()}`;

    app.use(
      (
        req: Request & { apiKey?: string },
        _res: Response,
        next: NextFunction,
      ) => {
        req.apiKey = key;
        next();
      },
    );
    app.use(rateLimit({ windowMs: 60_000, maxRequests: 1 }));
    app.get("/work", (_req, res) => res.json({ ok: true }));

    const accepted = await request(app).get("/work");
    expect(accepted.status).toBe(200);
    expect(accepted.headers["x-ratelimit-limit"]).toBe("1");
    expect(accepted.headers["x-ratelimit-remaining"]).toBe("0");
    expect(Number(accepted.headers["x-ratelimit-reset"])).toBeGreaterThan(
      Math.floor(Date.now() / 1000),
    );

    const rejected = await request(app).get("/work");
    expect(rejected.status).toBe(429);
    expect(rejected.body).toMatchObject({
      success: false,
      code: "RATE_LIMITED",
    });
    expect(Number(rejected.headers["retry-after"])).toBeGreaterThan(0);
  });
});
