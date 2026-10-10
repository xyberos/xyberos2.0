# ADR 0003: Begin at version 0.0.0 and isolate experimental scope

**Status:** accepted

## Decision

The package begins at `0.0.0` and uses SemVer concepts with PEP 440 package-version
spelling. Releases before `1.0.0` are preview releases. Breaking changes may occur in a
`0.x` minor release only with upgrade notes. `1.0.0` is reserved for the first stable
runtime and Workflow contract.

AI and durable execution are optional packages. Durable execution remains explicitly
experimental and is never represented as exactly-once, multi-host, or high-availability
execution.

## Consequences

- Public contracts require explicit compatibility/versioning decisions before `1.0.0`. *Owned by
  Phase 7, which audits and freezes the stable surface.*
- Experimental APIs must be clearly named and documented, and should emit warnings where
  practical. *Owned by Phase 6: the durable package is the experimental boundary and defines
  `ExperimentalWarning`.*
- Plugin, configuration, Workflow-definition, and journal-schema compatibility are versioned
  independently from the package. *Plugin API and configuration schema versioning shipped with
  the plugin and configuration work; Workflow-definition versioning shipped in Phase 4, which made
  `version` a required definition attribute surfaced in events and inspection and required
  definition metadata to be JSON-serializable ([ADR 0009](./0009-workflow-engine-contract.md));
  the stored journal schema and its migration path remain owned by Phase 6.*
