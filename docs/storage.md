# Object storage

> Status: preview API. `xyberos.storage` ships with the core package: the contract, the shipped
> local-filesystem provider, and the double need nothing beyond the standard library, so there is no
> extra to install. A remote backend is a package of its own that runs the conformance suite below.

Storage is for bytes an application generates or receives and keeps: an upload, an export, a rendered
report. It is deliberately not a filesystem abstraction, a content-type registry, or a signing service —
it is `put`, `get`, `delete`, `list_keys`, and a health check over an opaque payload.

## The contract

```python
from xyberos.storage import Storage  # a Protocol: max_object_bytes, put, get, delete, list_keys, health
```

| Member | Promise |
| --- | --- |
| `max_object_bytes` | the largest object this provider accepts; `put` refuses anything larger |
| `put(key, data)` | store bytes, replacing what was there, and report `StoredObject(key, size)` |
| `get(key)` | return the bytes, or raise `StorageNotFoundError` |
| `delete(key)` | remove the key and report whether an object was there |
| `list_keys(prefix="")` | yield keys in ascending order; `prefix` is matched as a literal string |
| `health()` | prove the space can be read *and written*, or raise `StorageError` |

`get` raises rather than returning `None` because a read that silently yields nothing turns an absent
object into an `AttributeError` somewhere further away. `delete` is the opposite decision on purpose:
removing something that was not there is not an error, so it answers `False`.

## Using the shipped provider

```python
from xyberos import App
from xyberos.storage import Storage, FilesystemStorageSettings, filesystem_storage

app = App()
app.provide(
    Storage,
    factory=filesystem_storage(FilesystemStorageSettings(root="var/objects")),
    eager=True,
)
```

`filesystem_storage(...)` returns a zero-argument async factory, the same shape
`sqlite_provider(...)` uses: the application composes the settings, the module provides the value.
Marking it `eager=True` proves the root is writable during `app.start()`, so a mounted volume that is
not there is a startup failure rather than a 500 on the first upload. The provider owns no connection or
handle and exposes no close hook.

Set `create_root=False` when the root must already exist — a deployment that expects a mounted volume
wants to hear about a missing directory, not to have one quietly created for it.

Reading and writing it looks like this:

```python
report = await storage.put("reports/2026-q1.csv", csv_bytes)
report.key, report.size

async for key in storage.list_keys("reports/"):
    print(key)
```

## Keys are the security boundary

A key is a **relative, forward-slash-separated path**. `validate_key` — which every provider calls, and
which a provider package should call too — refuses:

| Refused | Why |
| --- | --- |
| a leading or trailing `/` | the key is relative by definition; an absolute key is a caller bug |
| an empty, `.`, or `..` segment | this is the escape: `../` reaches a parent directory and is wrong-but-harmless in an object-store namespace |
| a backslash | a separator that only means something on one platform |
| a control character | a key reaches a filesystem, a URL, and a log line; a newline makes the third one a lie |
| a segment beginning with `.xyberos-` | providers use that prefix for scratch space, and a stored key must never be confusable with it |

The local provider checks twice: once through `validate_key`, and again on the **resolved** path. The
second check is what makes a symlink inside the root that points outside it a refusal rather than a
write. It also refuses Windows device names (`con`, `nul`, `com1`, …) on every platform, because one key
should not mean two things depending on where the application runs.

## The ceiling, and what is not promised

`put` refuses an object over `max_object_bytes` (64 MiB by default) with `StorageSizeLimitError` and
stores nothing. Writes are published atomically: the bytes land in a temporary file that `os.replace`
renames into place, so a concurrent reader sees either the previous object or the new one and never a
half-written one.

What that does **not** give you is durability against power loss. The bytes reach the disk on the
operating system's schedule. A deployment that needs a committed write to survive a crash uses a
database, and [`docs/database.md`](database.md) is the guide for that.

## Writing a provider package

A backend with a client library — S3-compatible and friends — is a package outside this repository
([ADR 0018](adr/0018-capability-placement-rule.md)), and it proves itself the same way a database
provider does:

```python
from xyberos.storage.testing import assert_storage_contract


def test_the_backend_satisfies_the_contract() -> None:
    checked = asyncio.run(assert_storage_contract(make_backend()))
    assert len(checked) == 10
```

`assert_storage_contract` checks round trips byte for byte, replacement, absence, deletion, ordering,
prefix filtering, the ceiling boundary at exactly one byte over, and the key refusals — and it cleans up
after itself, including after a failure. It is run in this repository against the filesystem provider,
against `InMemoryStorage`, and against two deliberately broken providers, because a suite that passes for
everything would be evidence that means nothing. The same shape applies to a database backend
([`database-providers.md`](database-providers.md)) and to an AI provider (`xyberos.ai.testing`).

Two things a provider author should keep in mind:

- **A backend that can fail transiently raises an error that is also a `TransientError`**, so a retry
  decision stays a classification rather than a guess. The shipped filesystem provider never raises one.
- **Bounded is part of the contract.** `list_keys` yields keys in ascending order whatever the backend's
  native ordering is, and the ceiling is a property of the provider rather than of the call.

## Errors

| Error | Raised when |
| --- | --- |
| `StorageError` | base class; `health()` also uses it directly for an unusable space |
| `StorageConfigurationError` | settings are unusable, or a root that must exist does not |
| `StorageKeyError` | a key is not a usable storage key, or resolves outside the root |
| `StorageNotFoundError` | `get` was asked for a key that is not stored |
| `StorageSizeLimitError` | the payload exceeds the provider's ceiling |

They live in [`xyberos.errors`](runtime.md) with the rest of the taxonomy.
