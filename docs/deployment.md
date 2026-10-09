# Deployment and operations baseline

This runbook describes the platform's current deployment baseline; it is not a
claim that every included provider is production-supported. Use a maintained ASGI
server behind a trusted TLS terminator, supply real application authentication,
and keep the local CRUD demo's fixed identity mapping off public networks.

## Network and secrets

- Terminate TLS at a maintained reverse proxy or load balancer. Forward traffic to
  the ASGI server over a private interface/network, and trust forwarded headers only
  from known proxy addresses.
- Expose only the required HTTPS listener. Do not expose databases, Ollama, relay
  administration, or internal metrics directly to the public internet.
- Load credentials, signing keys, and database connection strings from a secret
  manager or protected runtime environment. Never place production secrets in
  source, container arguments, checked-in config, or logs.
- Replace the bundled demo identity resolver with application-owned authentication.
  Protect application routes independently of the public health endpoints.
- Log lifecycle and request metadata needed for operations, but not credentials,
  authorization headers, prompts, message bodies, or database connection strings.

## Startup, readiness, and shutdown

The `/health/live` route reports kernel lifecycle only. `/health/ready` also runs
configured async dependency probes, each bounded by `probe_timeout_seconds` (one
second by default). It returns only `ready` or `unavailable` for each dependency;
probe exception text is not returned. Configure probes only for dependencies that
must be available before serving requests. Keep readiness probes bounded and
side-effect-free.

```python
from xyberos.http.health import create_health_routes


async def database_probe() -> None:
    database = kernel.container.resolve(Database)
    await database.fetch_one("SELECT 1")


routes = create_health_routes(
    kernel,
    probes={"database": database_probe},
    probe_timeout_seconds=1.0,
)
```

Set the orchestrator termination grace period above the configured
`shutdown_drain_timeout_seconds` (30 seconds by default), plus enough time for the
process to close providers. The kernel stops admissions before draining tracked
work, but does not forcibly cancel arbitrary tasks or thread/process work.

## Schema upgrades

Use `SchemaMigration(version, statements)` and `SchemaMigrator(database)` to keep
an ordered migration history in `xyberos_schema_migrations`. Migrations are
forward-only and each migration's statements plus ledger record are committed in
one database transaction. Pass the complete ordered migration history on each
`apply` call. Keep applied migration versions immutable, add a higher version for
changes, and do not reuse or renumber a released version. The migrator rejects a
database containing a version unknown to the running application.

Run a migration as a single deployment job before starting or scaling application
workers. Do not run competing migration processes concurrently. Rollback means
restore a verified backup or deploy a separately authored compensating migration;
there is no automatic reverse migration. The example app retains
`auto_migrate=True` for local convenience. Production deployments should first run
the migration command once and construct the app with `auto_migrate=False`.

The SQLite example migration command uses the same database path as the example
app:

```powershell
$env:XYBEROS_DATABASE_PATH = ".\data\example.db"
python -m apps.example_crud_app.migrate
```

For applications using PostgreSQL or another provider, run the same
`SchemaMigrator` against that provider from a single pre-deploy migration job.
Review provider compatibility for application-specific SQL before applying it.

## Backups and restore

Backups are not configured by Xyberos. Establish a recovery-point objective and
recovery-time objective, encrypt backups, restrict access, and regularly test
restores in an isolated environment.

For SQLite, use SQLite's online backup API rather than copying a live database
file, especially when WAL mode is enabled:

```python
import sqlite3

with sqlite3.connect(r".\data\example.db") as source:
    with sqlite3.connect(r".\backups\example-backup.db") as destination:
        source.backup(destination)
```

Verify the backup opens and run `PRAGMA integrity_check` on a restored copy before
promoting it. Restore by stopping writers, preserving the failed database for
investigation, placing the verified backup at the configured path, and restarting
the application.

For PostgreSQL, use the database operator's tested snapshot mechanism or
`pg_dump`/`pg_restore` with credentials supplied securely. Test restoration to a
separate database and verify application-level schema/data invariants before
cutover. These are operator procedures; this repository does not ship backup
automation.

## Provider maturity and support

- SQLite and PostgreSQL implement the same async database contract. SQLite is the
  default/local provider; PostgreSQL support is optional and CI exercises the
  contract against PostgreSQL 16.
- Local filesystem blob storage is single-host storage, not a replicated object
  store. In-memory memory and keyword-knowledge providers are bounded
  demonstration/test implementations and are not durable.
- The HTTPS P2P relay is an early protocol foundation, not a managed messaging
  service. Review [the implementation plan](implementation.md) and [README](../README.md)
  for its retention, rate-limit, encryption-at-rest, and key lifecycle gaps.
- CI is configured for Python 3.10–3.13. This is the intended tested matrix; the
  current local validation only establishes behavior for the interpreter used in
  this checkout. Consult successful CI runs before asserting a version is verified.

CI runs linting, focused static type checking, the unit/integration suite, a
PostgreSQL service, and `pip-audit`. The exact local commands are listed in the
repository workflow.
