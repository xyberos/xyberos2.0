# ADR 0019: The storage contract, and keys as the security boundary

**Status:** accepted

## Context

An application that handles uploads or generated artefacts needs somewhere to put bytes, and every
option in that space — a directory, an object store, a database column — has the same two failure modes:
a key that escapes the namespace it was given, and an unbounded object. Both are ordinary mistakes in an
adapter and both are unrecoverable in production, which is what makes them worth a contract rather than a
convention.

Two things about this framework decide the shape:

1. **It ships one implementation rather than a catalogue.** [ADR 0016](0016-database-providers-are-an-extension-point.md)
   made the database seam reusable and proved it with a conformance suite that fails for two deliberately
   broken providers. A storage backend is the same kind of seam — a local directory today, an
   S3-compatible store later — and deserves the same treatment rather than a second, differently-shaped
   one.
2. **A dependency-free capability is a module here, not an extra.**
   [ADR 0018](0018-capability-placement-rule.md) places it. The filesystem implementation uses only the
   standard library, so `xyberos.storage` is importable without an extra, exactly as `xyberos.ai` is.

## Decision

**Ship a five-member contract, one working implementation, a double, and a suite — and make the key rules
part of the contract, not part of each provider.**

1. **The contract is `max_object_bytes`, `put`, `get`, `delete`, `list_keys`, and `health`.** It
   deliberately says nothing about content types, versions, multipart uploads, signed URLs, or metadata,
   so a provider cannot smuggle a backend-specific API into application code. `put` replaces what was
   there and reports what it stored; `get` raises `StorageNotFoundError` rather than returning `None`;
   `delete` reports whether an object was there; `list_keys` yields keys in ascending order; `health`
   proves the space can be read *and written*, because a filesystem that has gone read-only still
   reports a directory that exists.
2. **A key is a relative path, and `validate_key` is the only rule.** No leading or trailing separator, no
   empty, `.` or `..` segment, no backslash, no control character, and no segment beginning with the
   reserved prefix `.xyberos-` that providers use for their own scratch space. The rule lives in the
   contract module rather than in each provider because it is the one mistake every backend can make, and
   it is called by every provider that ships here and by the double.
3. **The local provider checks containment on the *resolved* path.** Validating the key is not enough:
   `(root / key).resolve()` follows symlinks, so a link inside the root pointing outside it is refused by
   a containment test where a prefix test on the joined string would have written through it. It also
   refuses Windows device names (`con`, `nul`, `com1`, …) unconditionally, because a key that resolves to
   a device on one platform and a file on another means two things depending on where it runs.
4. **The ceiling is enforced before the disk is touched, and publish is atomic.** `put` refuses an object
   over `max_object_bytes` with `StorageSizeLimitError` and stores nothing. A write lands in a temporary
   file that `os.replace` publishes within the filesystem, so a reader sees either the previous object or
   the new one and never a half-written one.
5. **`assert_storage_contract` ships with the contract.** A provider author outside this project runs it
   against their own implementation — the same claims checked here as against the shipped provider, so
   "we support an S3-compatible backend" means evidence. It is exercised against `InMemoryStorage`, the
   filesystem provider, and two deliberately broken providers in `tests/storage/`.

**What is deliberately not promised.** Durability against power loss: the bytes reach the disk on the
operating system's schedule, and a deployment that needs the stronger guarantee uses a database. Nor
performance, isolation, or operational maturity — a provider that passes the suite can still be wrong for
a workload, and the suite says so in its own docstring.

## Consequences

- **Swapping the backend is a supported path, not a promised feature.** A team that needs S3 writes a
  provider package, runs `assert_storage_contract`, and keeps the service code that depends on `Storage`.
  This repository never imports such a package, and the compatibility job proves the published pair.
- **`xyberos.storage` is public surface in the preview tier.** `Storage`, `StoredObject`, `validate_key`,
  the limits, the settings object, the provider, and the factory are declared in `__all__` and pinned by
  `tests/test_public_surface.py`; the errors (`StorageError`, `StorageKeyError`, `StorageNotFoundError`,
  `StorageSizeLimitError`, `StorageConfigurationError`) join the taxonomy in `xyberos.errors` beside the
  AI and durable families.
- **Configuration is the application's.** `FilesystemStorageSettings` plus `filesystem_storage(settings)`
  is the whole integration: the application composes the settings, the module hands `app.provide` a
  zero-argument async factory, and nothing reads the environment or a configuration file. It is the
  explicit-argument route of [ADR 0018](0018-capability-placement-rule.md), proven in `tests/storage/`
  through the registry rather than in prose.
- **`list` was renamed `list_keys`.** The first implementation named the member `list`, which shadows the
  builtin inside the class body: two `mypy` errors in `_keys` were the visible symptom, and the invisible
  one is that any later method in those classes annotating `list[str]` would have silently resolved to the
  method. The contract pays one word to remove a whole class of mistake.
- **A key is data, not text.** Refusing control characters and reserving one segment prefix is what makes
  a key safe to put in a log line, a URL path, and a filesystem path at the same time — which is the only
  reason the validation belongs in the contract rather than in the provider that happens to be first.
