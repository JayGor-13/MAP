# Local service recovery — 2026-10-20

The newly installed Docker Desktop was used for live verification after the user reauthorized access. **All eleven backend readiness probes and the complete local synthetic journey passed.** Billing recreation against existing schemas, frontend authentication/proxy flows and the engine's private recompute/cache path also passed. See [the current verification record](VERIFICATION.md) for evidence and limits. Interactive browser automation could not attach; native browser video playback was not verified.

## Repairs in this checkout

- **Subscription, Payment and Invoice:** `Store.Init()` now trims SQL fragments and removes empty entries before executing commands. This prevents the final newline after the migration's last semicolon from being sent as an empty MySQL command. The reported `CommandText must be specified` is an initialization bug; it does not establish a bad MySQL connection/password. No migration or database data was changed.
- **Catalog Write and Read:** Store database/JSON fields are private. Health, browse, outbox relay and projection call Store methods, allowing Spring's proxy to delegate to the initialized target. Projection retains a transaction through `Store.project()`. Two proxy regressions passed, followed by real PostgreSQL/Kafka publish, projection and browse checks.
- **Recommendation Engine and API:** `requirements.txt` already includes `httpx==0.28.1`. Both Python images were rebuilt; `pip check` and imports of all direct runtime modules passed. Real graph-backed trending, watched-title exclusion, private recompute persistence and Redis snapshot publication passed.
- **Kafka/Mongo startup:** command-based probes repeatedly exceeded their original 10-second/5-second limits. A successful Kafka API probe took 42 seconds during startup load. Local Compose now allows 60 seconds for Kafka and 30 seconds for MongoDB, with startup grace periods. Kafka's probe and topic initializer use smaller CLI heaps. Both databases/brokers became healthy and their one-shot initializers exited successfully.
- **Watchlist/Playback/History communication:** local Watchlist's nested authority call failed at its 800 ms deadline; playback initially failed at its one-second dependency boundary. Outbound HTTP deadlines are now configurable, with five-second values in local Compose. Service defaults remain unchanged outside this configuration. Sanitized dependency diagnostics were added. Real watchlist, admission/idempotency, heartbeat, media and history checks passed.
- **Gateway after container recreation:** Kong attempted Playback's old IP after its container moved, causing intermittent connection-refused 502 responses while direct readiness passed. Local DNS valid/stale/negative TTLs are now 5/0/1 seconds, using [Kong 3.9's documented settings](https://raw.githubusercontent.com/Kong/kong/3.9.0/kong.conf.default). Billing containers later changed IPs and gateway/frontend requests recovered without a gateway restart. Two gateway workers also reduce the local memory footprint.
- **Smoke test:** request JSON headers are only sent when a body exists, fixing Fastify's rejection of an empty JSON DELETE during cleanup. `--check-media` verifies signed HLS files and unsigned URL rejection. Recommendation checks respect the intended watched-title exclusion rather than expecting a watched title on Home.

## Rebuild on the Docker host

From this project folder, with the host's existing `.local/dev.env` and healthy Docker engine:

```powershell
docker compose --env-file .local/dev.env -f member-1-platform/compose.yaml build --no-cache reco-engine reco-api
docker compose --env-file .local/dev.env -f member-1-platform/compose.yaml up --build -d
docker compose --env-file .local/dev.env -f member-1-platform/compose.yaml ps -a
```

Use the Compose frontend at http://localhost:8090 and select **Check connections**. Host-mode frontend probes cannot reach the private application ports in the standard Compose stack. Eleven ready probes confirm dependency availability only; they do not prove the business journey.

Check that the recommendation image imports the formerly missing module:

```powershell
docker compose --env-file .local/dev.env -f member-1-platform/compose.yaml exec reco-api python -c "import httpx; print(httpx.__version__)"
```

Verify billing can restart against its existing schemas, then check connections again:

```powershell
docker compose --env-file .local/dev.env -f member-1-platform/compose.yaml restart subscription payment invoice
docker compose --env-file .local/dev.env -f member-1-platform/compose.yaml logs --tail 100 subscription payment invoice catalog-write catalog-read reco-engine reco-api playback-session watch-history
```

Run the synthetic journey on the local demo stack only. It creates test data, cancels alice's existing ACTIVE/PENDING subscriptions, and retains sandbox financial history:

```powershell
python member-1-platform/tests/smoke.py --check-media
```

The optional media check requires `.local/media/demo/master.m3u8` and its segments. Generate them with `member-1-platform/tools/make-demo-media.ps1` when FFmpeg is installed, or omit `--check-media` for a journey without media-byte checks.

Do not remove volumes or regenerate credentials to apply these source repairs. If a service is still unavailable, its current startup log and `ps -a` output are needed to distinguish crashes, dependencies and HTTP errors.

## Historical evidence — 2026-10-11

The frontend and Markdown API reference are delivered. Docker images built and all Compose service containers started. A full live user journey has not passed. Browser interaction checks used isolated fixtures; these do not establish service integration.

## Member 4: billing startup

Subscription, Payment and Invoice repeatedly fail with `System.InvalidOperationException: CommandText must be specified` in `Billing.Store.Init()` (`member-4-billing/Store.cs:8`).

The migration ends with a semicolon followed by whitespace. Splitting with `RemoveEmptyEntries` retains a whitespace-only fragment; inspecting the actual migration found one such fragment. MySqlConnector rejects this as an empty command. The databases themselves became healthy.

Requested owner fix: trim each statement and exclude empty/whitespace fragments before execution. Verify startup against a real MySQL database, existing-schema restart, plans/subscriptions, payment convergence and invoice generation. Unit/build tests alone did not expose this initialization failure.

## Member 3: catalog store access

Catalog Write's scheduled relay repeatedly throws `NullPointerException` because `this.store.db` is null in `Relay.flush()` (`member-3-catalog/src/main/java/local/streaming/catalog/Catalog.java:102`). Both catalog dependency probes returned HTTP 401 after startup; the configured security chain permits `/health/**`, so this is not evidence that probe callers should supply a token. An error dispatch can mask the original exception behind authentication.

`Store` has transactional methods and is proxied by Spring. Other components directly access its `db`/`json` fields; direct field access bypasses proxy delegation. This is the inferred cause of the null field, based on the runtime exception and source. The same direct access appears in browse, readiness and projection code.

Requested owner fix: encapsulate database/JSON operations behind methods on the target bean (or inject needed dependencies directly into the caller), preserve transaction boundaries, and verify health, admin publish, relay/projection and eligible browse against real PostgreSQL/Kafka.

Member 1 has not changed either member's source or migrations. Coordinate fixes through owner-reviewed pull requests according to AGENTS.md. No claim of a completed end-to-end or production-qualified system follows from frontend tests.

## Recheck after owner fixes

```powershell
docker compose --env-file .local/dev.env -f member-1-platform/compose.yaml up --build -d
python member-1-platform/tests/smoke.py
```

Smoke changes synthetic local records and cancels alice's existing ACTIVE/PENDING subscriptions. Use only the local demo account. In the UI, Account → Connection details exposes dependency probes and the latest redacted response.
