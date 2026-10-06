# Codex review of PLAN.md

Reviewed: 2026-10-05

## Assessment

The plan establishes a coherent capstone: a simulated trading terminal, one container, one origin, SQLite persistence, SSE prices, and an assistant that uses the same trading rules as manual orders. The separation between frontend, backend, and market-data responsibilities is useful, and keeping cloud deployment optional protects the core scope.

The main weakness is that several behaviors crossing those boundaries are described without an executable contract. Resolve the high-priority findings before independent implementation begins; otherwise, agents can produce locally reasonable components that disagree about prices, balances, or completed actions.

This is a specification review of the current plan, not an implementation audit. External provider capabilities, pricing, and platform support have not been independently verified. References below point to sections and current line numbers in [PLAN.md](PLAN.md).

## High-priority findings

### 1. Price coverage must include holdings and requested trades

**References:** §6, lines 163–180; §8, line 269; §10, lines 370–373.

The poller covers watched tickers, and the SSE section equates all known tickers with the watchlist. But users can remove a ticker while still holding it, and the trade bar accepts a ticker without requiring watchlist membership. A removed holding could stop receiving prices, leaving valuation and sell execution stale; a trade for an unwatched ticker has no defined price source.

**Recommendation:** Define the pricing set as watchlist tickers plus held tickers, with an explicit quote acquisition path for new trade symbols. Removing a watchlist entry must not stop pricing an open position. Specify ticker normalization, supported symbols, new simulator seed prices, and rejection of unsupported symbols. Define quote timestamps, maximum acceptable age, and behavior when a fresh quote is unavailable. Test buying an unwatched ticker and selling a holding after removing it from the watchlist.

### 2. Trade execution needs atomicity, precision, and idempotency

**References:** §7, lines 199–238; §8, line 269; §9, lines 309–310 and 326.

Cash, positions, trades, and post-trade snapshots all change during execution, but transaction boundaries are unspecified. Two overlapping requests could both pass a cash check. A lost response followed by a retry could execute the same order twice. `REAL` amounts and fractional shares also need an explicit rounding policy to avoid residual balances or overselling at precision boundaries.

**Recommendation:** Use one shared trade service for manual and assistant orders. Capture an eligible execution quote, then perform balance/holding validation and all related database writes in one transaction. Require a client-generated idempotency key and persist its result atomically. Define allowed share precision, money representation and rounding, weighted average cost, partial-sale behavior, and deletion of zero-quantity positions. Reject non-finite or non-positive quantities; explicitly disallow shorting and negative cash. Specify database constraints and concurrency handling. Test simultaneous buys, retry after a committed order, fractional purchases, and full liquidation.

### 3. Assistant actions need an execution-result contract

**References:** §9, lines 304–348.

The example JSON describes proposed actions, while chat persistence and the frontend require executed actions. The plan does not define action ordering or partial failure: if an assistant sells one position and buys another, the order matters. It also says a validation error lets the LLM inform the user, but execution happens after the only model call in the documented flow.

**Recommendation:** Separate proposed actions from authoritative execution results. Define a strict schema with enums, numeric limits, bounded action counts, and unknown-field handling. Choose a batch policy, such as ordered execution with an individual success/error result for every action, and specify ordering across trades and watchlist changes. Return trade IDs, actual fill prices, quantities, and failures. Either add a second model call using those results or render backend-generated outcome text; the original assistant message must not claim a rejected trade succeeded. Preserve the no-confirmation experience, but define when recommendations should produce empty action arrays and how explicit execution intent is recognized. Define request idempotency and chat ordering so retries or concurrent chats cannot repeat a batch.

### 4. The API inventory is not yet a shared integration contract

**References:** §6, lines 175–181; §8, lines 256–290; §10, lines 366–373.

Endpoint names and short descriptions do not specify response bodies, error bodies, status codes, or numeric/timestamp conventions. Daily change percentage is required by the watchlist, but the cache only contains the previous price, which describes a tick change rather than a daily baseline. Snapshots and persisted chat messages have no defined frontend refresh/history flow.

**Recommendation:** Add example request, success, and error payloads for every endpoint, plus the exact SSE event envelope. Specify UTC timestamps, numeric units, nullable/unavailable quotes, duplicate watchlist behavior, and a stable error format. Supply a session reference price for daily change, including simulator session rules. Define chart refresh cadence, portfolio refresh after manual and assistant mutations, and either a chat-history endpoint or an explicit session-only chat UI. Specify history range/limit/order parameters and bounded frontend buffers. These contracts should precede parallel frontend/backend work.

### 5. Massive polling has an unresolved request-budget dependency

**References:** §6, lines 160–166.

Under the plan's stated five-calls-per-minute budget, a 15-second interval uses four calls per minute only if each polling cycle makes one request. Ten individual ticker requests every 15 seconds would require forty calls per minute. The endpoint, batching, and entitlement assumptions are not documented.

**Recommendation:** Select and document the provider endpoint and response fields before promising a cadence. Verify its batching, quote freshness, and account-tier access against provider documentation. Calculate the interval from the total requests needed per cycle, reserving capacity for symbol lookup or on-demand quotes. Define timeout, rate-limit backoff, invalid-key behavior, and market-closed behavior. Show whether quotes are simulated, delayed, fresh, or stale; avoid silently changing data sources after provider failures.

## Medium-priority findings

### 6. Startup and persistence behavior need one lifecycle

**References:** §4, line 114; §7, lines 187–197; §11, lines 397–413.

Initialization alternates between first request and startup, even though price and snapshot tasks need initialized state. The schema also has no evolution strategy for an existing persistent volume. Separately, the Docker command uses a named volume, while the following sentence describes the repository's `db/` directory as mounted; these are different storage arrangements.

**Recommendation:** Initialize and version the schema during backend startup, seed transactionally and idempotently, then start background tasks. Document safe upgrades of an existing volume and avoid re-adding watchlist entries a user intentionally removed. Choose named-volume storage as the default shown command, describe a bind mount separately, and configure an unambiguous database path. Specify one application worker for the in-memory cache/background tasks, graceful task shutdown, database locking behavior, and health/readiness semantics.

### 7. SSE reconnection does not establish state synchronization

**References:** §2, line 37; §6, lines 170–181; §12, line 472.

Automatic reconnection restores transport, but the plan does not say how a new or returning client gets current state. At a 500ms emission cadence, an unchanged provider quote might also be mistaken for a fresh price sample.

**Recommendation:** Send a complete current snapshot on connection, followed by versioned updates, and use heartbeats separately from quote events. Define event IDs or a documented snapshot-on-reconnect policy, quote timestamps distinct from delivery timestamps, unchanged-price handling, and bounded handling of slow clients. Specify how transport status differs from data freshness and whether missing chart intervals remain gaps. Test disconnecting through a trade or watchlist change and then reconciling state.

### 8. Portfolio visualization metrics need formulas

**References:** §2, lines 28–29; §7, lines 233–238; §10, lines 368–370.

The “P&L chart” is specified as total portfolio value, and “% change” and treemap weight do not have explicit denominators. Implementations could show daily movement, return since purchase, or total account return under the same labels.

**Recommendation:** Define total value as cash plus marked position values, unrealized P&L as quantity times price minus cost basis, and return percentages with their denominators. Choose whether the chart displays equity or profit relative to the initial $10,000. Define realized P&L if it is displayed, the treemap's treatment of cash, a fresh-account snapshot, and empty/all-cash UI behavior. Specify valuation behavior when any holding lacks a valid quote rather than treating that holding as worth zero.

### 9. First-launch and deployment expectations are incomplete

**References:** §2, lines 15–20; §5, lines 125–141; §11, lines 410–435.

The first-launch promise includes a ready assistant, but the default Docker command requires an `.env` file and chat requires a key unless mock mode is enabled. There is no specified experience when the file or key is absent. Cloud deployment also carries the single shared account and local-file persistence assumptions into a different environment.

**Recommendation:** Commit the promised `.env.example`, document a working keyless simulator launch, and define a disabled/unavailable assistant state when no key is configured. Bind the local launcher to loopback by default because all clients share mutable state. Treat cloud deployment as a separate acceptance gate requiring an explicit access boundary and durable SQLite storage strategy. Keep credentials server-side and out of static assets and logs. Choose lockfile-enforced dependency installation for both build stages and document route precedence so static serving cannot swallow `/api/*` errors.

### 10. Mock LLM responses alone do not make E2E tests deterministic

**References:** §6, lines 153–156; §7, line 233; §12, lines 439–472.

Tests still depend on random price movement, scheduled snapshots, persistent volumes, and asynchronous background activity. Exact cash/P&L assertions can vary even with deterministic chat responses.

**Recommendation:** Provide a seeded or fixed-price market fixture, controllable time where financial logic needs it, isolated test storage, and readiness checks. Make mock chat propose actions through the same validation and execution pipeline as real chat. Add coverage for the failures above: concurrent/repeated orders, partial assistant failures, stale quotes, held-but-unwatched symbols, restart persistence, and SSE state recovery. Keep provider parsing tests fixture-based and make any external-provider smoke test explicit and optional. Establish a small visual acceptance checklist for the desktop/tablet layout, keyboard operation, empty states, and reduced-motion price flashes.

## Documentation cleanup

- §7 says every table has `user_id`, but `users_profile` uses `id` instead. Describe that exception and add foreign keys, required fields, and relevant indexes.
- §9 references `cerebras-inference` without a path. The repository contains `.claude/skills/cerebras-inference/SKILL.md`; link the dependency and place the required integration contract in shared documentation for agents using other tooling.
- §9's statement that an API key exists is specific to one checkout. Replace it with setup requirements and missing-key behavior.
- §4 mentions migration logic while §7 says no separate migration step. Clarify that automatic versioned migrations can run at startup without a manual command.
- §2 promises a browser opens, while §11 makes opening it optional. Describe raw Docker usage and launcher behavior consistently.

## Suggested implementation gates

1. **Agree on contracts:** API/SSE payloads, quote coverage/freshness, financial formulas, transactional trading, and assistant action outcomes.
2. **Deliver the simulator vertical slice:** persisted fresh account, streamed prices, manual buy/sell, portfolio valuation, and restart behavior in one container.
3. **Add assistant execution:** mock and real adapters sharing parsing/validation/execution, visible per-action results, and retry protection.
4. **Complete UI and resilience:** charts, watchlist changes, reconnect behavior, deterministic E2E coverage, and documented launch scripts.
5. **Integrate optional real data:** verified endpoint/entitlement assumptions and explicit freshness/rate-limit behavior. Keep cloud deployment as a separate stretch deliverable.

The core architecture does not need a redesign. A compact contract appendix covering these decisions would make the plan substantially safer to implement and easier to review.
