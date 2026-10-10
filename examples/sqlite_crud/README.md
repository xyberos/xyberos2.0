# sqlite_crud example

A complete CRUD slice: typed configuration, an injected SQLite provider, SQLAlchemy Core tables, a
service layer, domain errors, routing, and Alembic migrations.

## Run it

```powershell
python -m pip install -e ".[http,database]" uvicorn
python examples/sqlite_crud/migrate.py var/app.db
uvicorn --app-dir examples --factory sqlite_crud.app:app_factory
```

## Layout

| Path | Purpose |
| --- | --- |
| `tables.py` | SQLAlchemy Core metadata and the `items` table |
| `service.py` | `ItemService`: business rules and transaction boundaries, no HTTP types |
| `errors.py` | `ItemNotFoundError` (404) and `ItemValidationError` (422) |
| `app.py` | `create_app` and `build_asgi_app`: composition and routes |
| `migrations/` | Alembic environment with two revisions, including a batch-mode migration |
| `migrate.py` | Applies the migrations to a database path |

## Endpoints

| Method | Path | Behavior |
| --- | --- | --- |
| `GET` | `/health` | database readiness check |
| `GET` | `/items` | list items |
| `GET` | `/items/{item_id}` | one item, or 404 |
| `POST` | `/items` | create from `{"name": "..."}`, or 422 |
| `PATCH` | `/items/{item_id}` | rename (`name`) or complete (`completed`), or 404/422 |
| `DELETE` | `/items/{item_id}` | delete, or 404 |

## Why it is shaped this way

- The service depends on the `DatabaseProvider` protocol, so swapping SQLite does not change
  business code, and no HTTP type reaches the service or the tables.
- Every write is one short transaction; a failed write leaves no partial row.
- Domain errors carry their HTTP status, so the adapter maps them without per-route error
  handling.
- Migrations are explicit and Alembic-owned; the second revision uses batch mode because SQLite
  cannot add a `NOT NULL` column in place.

See the [HTTP guide](../../docs/http.md) and the [database operations guide](../../docs/database.md).
