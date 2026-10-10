# ADR 0003: Begin at version 0.0.0 and isolate experimental scope

**Status:** accepted

## Decision

The package begins at `0.0.0` and uses SemVer concepts with PEP 440 package-version
spelling. Releases before `1.0.0` are preview releases. Breaking changes may occur in a
`0.x` minor release only with upgrade notes. `1.0.0` is reserved for the first stable
runtime and Flow contract.

AI and durable execution are optional packages. Durable execution remains explicitly
experimental and is never represented as exactly-once, multi-host, or high-availability
execution.

## Consequences

- Public contracts require explicit compatibility/versioning decisions before `1.0.0`.
- Experimental APIs must be clearly named and documented, and should emit warnings where
  practical.
- Plugin, configuration, Flow-definition, and journal-schema compatibility are versioned
  independently from the package.
