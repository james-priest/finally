# E2E Issues

Logged by `integration-tester` from runs of the Playwright suite in `test/`. Owners per TEAM_CONTRACT.md §1.

| ID | Scenario | Evidence | Owner | Status |
| -- | -------- | -------- | ----- | ------ |

No app issues found. Every failure so far was in the test suite itself and was fixed there (see the run log).

## Run Log

| Date | Target | Spec | Result | Notes |
| ---- | ------ | ---- | ------ | ----- |
| 2026-10-11 | local uvicorn :8010, fresh temp DB, simulator, LLM_MOCK=true | 07-api | 8 passed, 1 failed | The one failure ("SSE stream sends price events") is environmental: headless Chromium aborts at launch in the agent's macOS sandbox (`bootstrap_check_in ... MachPortRendezvousServer: Permission denied (1100)`). The SSE endpoint checked with curl: `retry: 1000` and then about 2 events/s, each with all 10 tickers. Browser specs need the Docker compose run (Linux container) or a run outside the sandbox. |
| 2026-10-11 | docker compose (app built from root Dockerfile, frontend still a scaffold) | 07-api | 8 passed, 1 failed | The failure was a test-infra bug in my compose file: the service was named `app`, and Chromium forced HTTPS for `http://app:8000` (`net::ERR_SSL_PROTOCOL_ERROR`) because `.app` is an HSTS-preloaded TLD. A probe from the Playwright container got 200 from `http://test-app-1:8000` and the SSL error from `http://app:8000`, against the same server. Renamed the service to `finally-app`. |
| 2026-10-11 | docker compose, after the rename | 07-api | 9 passed | |
| 2026-10-11 | docker compose, full suite (frontend complete) | all | 30 passed, 1 failed | "SSE resilience" was a test bug. `context.setOffline(true)` fails new requests but does not cut an SSE response that is already streaming. A probe showed `fetch` failing while offline, yet the open EventSource kept receiving messages (5 to 13 in 4s, 0 errors), so the frontend was right to stay `connected`. I rewrote the test to own the stream: the first connection gets a finite body, reconnects are refused, then the real stream is let through. Passed 3/3 alone. |
| 2026-10-11 | docker compose up, full suite | all | 31 passed | exit 0 |
| 2026-10-11 | docker compose up, full suite (repeat) | all | 31 passed | exit 0; no flakes |
| 2026-10-11 | docker compose up, full suite (after team-lead go; frontend final) | all | 31 passed | exit 0 |
