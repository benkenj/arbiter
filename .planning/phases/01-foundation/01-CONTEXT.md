# Phase 1: Foundation - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Config system, database schema + Alembic migrations, and a reliable Gamma API client with retry/pagination. These are the primitives everything downstream depends on. No signal detection, no polling loops, no notifications — just the foundation that makes those things possible.

</domain>

<decisions>
## Implementation Decisions

### Startup behavior
- Print a config summary on startup (every loaded config value visible so the operator can verify settings)
- After config loads, perform a DB connection check + Gamma API health check; print a "service ready" line once both pass
- If DB is unreachable at startup: retry a few times with backoff, then fail with a clear error (don't crash immediately on first attempt)
- Include a `--check` flag (or `arbiter check`) that validates config and connectivity without starting the polling loops — useful for pre-deploy verification

### Local dev setup
- Use `.env` file for local development; production uses real environment variables (standard pydantic-settings pattern)
- Include `.env.example` in the repo with all required vars documented, placeholder values, and comments explaining each var
- Include a `docker-compose.yml` for local PostgreSQL (so developers don't need a system-level Postgres install)
- Migration strategy: leave to Claude's discretion (auto-on-startup vs manual `alembic upgrade head` — pick the standard Python/Alembic approach)

### Error output style
- Startup validation: collect ALL missing/invalid config vars and report them together in one message (don't stop at the first error)
- Each error message includes a hint for the correct format (e.g. "Set DATABASE_URL to a PostgreSQL connection string: `postgresql+asyncpg://user:pass@localhost/arbiter`")
- Errors go to stderr; normal operational logs go to stdout (standard Unix convention)
- Discord crash alerts deferred to Phase 5

### Logging verbosity
- Default to quiet: heartbeat line per polling cycle + signal fires only
- `--verbose` flag (or `LOG_LEVEL=DEBUG`) enables detailed output (every API call, response codes, timing)
- `LOG_LEVEL` env var controls log level (INFO default, DEBUG for troubleshooting)
- Log format: plain text with timestamp — `2026-02-22 14:30:01 [INFO] <message>`
- Log destination: console only for now; file routing via shell redirection if needed

### Claude's Discretion
- Whether migrations run automatically on startup or require `alembic upgrade head` — use whatever is the standard Alembic/Python pattern
- Log destination (console vs file) — console only is fine for now
- Connection pool size and settings — pick sensible defaults
- Exact retry count and backoff for startup DB connection

</decisions>

<specifics>
## Specific Ideas

- The `.env.example` should be thorough enough that a new developer (or future me) can get running without reading docs
- The config summary at startup should be easy to scan — probably grouped (DB, API keys, detection thresholds)
- The `--check` mode is specifically useful for "I just deployed, did this actually configure correctly?"

</specifics>

<deferred>
## Deferred Ideas

- Discord alert on crash/restart — noted for Phase 5 hardening
- Structured JSON logging — user chose plain text for now; could revisit in Phase 5 if log aggregation becomes useful

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-02-22*
