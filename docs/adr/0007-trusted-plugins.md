# ADR 0007: Trusted plugins as an explicit, ordered capability model

**Status:** accepted

## Context

Phase 3 adds independently authored capability integrations. The registry must not become a global
service locator, startup must stay visible and reproducible, and failures must be attributable to a
plugin, a phase, and a dependency.

## Decision

**Plugins are an abstract base class, not duck-typed objects.** `Plugin` declares `name`,
`api_version`, `requires`, `config_type`, and the `register` hook, so a malformed plugin fails at
import time and the contract is type-checkable. Optional `start` and `stop` hooks manage
plugin-owned resources.

**Requirements must already be registered.** `add_plugin` rejects a plugin whose `requires` are not
yet registered. Registration order is therefore dependency order, startup order is deterministic,
and requirement cycles are structurally impossible. This replaces a deferred topological sort with
an immediate, actionable error.

**`register` is the only mutation window.** A plugin adds providers and routes during `register`,
while the application is still mutable. Provider duplicates fail, so a plugin cannot silently
replace an existing provider; replacement stays explicit through configuration or
`with_overrides` for tests. Route registration is already rejected after `start()`, so a plugin
cannot change routing once the application is ready.

**Plugin lifecycle wraps the provider lifecycle.** Eager app-scoped providers are constructed
first, then plugins start in order; on shutdown plugins stop in reverse order before app-owned
resources close. Providers are the lower layer, so dependencies keep pointing downward. A plugin
cannot resolve application services from `start`, because the application is not ready yet;
registering an eager provider is the supported pattern for startup work.

**Failures name the plugin and the phase.** Plugin errors carry `plugin` and `phase`, always chain
the original exception, and never echo configuration values. Partial startup stops the plugins that
already started and reports any cleanup failure in the same message.

**Configuration is typed, validated, and never echoed.** A plugin may declare a dataclass schema.
Settings come from the same precedence chain as core settings (explicit mapping, environment,
`[plugins.<name>]` in the configuration file, dataclass defaults) and support scalar fields only,
which keeps the runtime free of a configuration framework. Unknown keys, missing required values,
and invalid values fail before `register`.

**Plugin API versioning is a major-version match.** `PLUGIN_API_VERSION` is the runtime contract
version; a plugin targeting a different major version is rejected during `add_plugin`, before any
registration or startup work.

**Attribution and diagnostics are automatic.** Providers registered from a plugin's `register` hook
record `plugin:<name>` as their source, and `app.diagnostics()` reports every active provider's
source plus plugin order and state.

**No discovery and no sandbox.** Application code adds plugins explicitly, so startup stays
readable and reproducible. Plugins are trusted in-process Python: Xyberos does not sandbox them,
does not claim a permission model, and does not attempt to make untrusted package code safe.

## Consequences

- Phase 4 (Workflow) and later phases can ship capabilities as plugins without widening the
  runtime. *Phase 4 instead kept the workflow engine in core, because it is an execution layer
  rather than a capability, so it needs no extra and no plugin lifecycle; the plugin path stays open
  for capabilities built on top of it ([ADR 0008](./0008-workflow-terminology.md)).*
- Test clones copy providers and routes but not plugin registrations, so plugin lifecycle hooks
  cannot run twice; this is documented in the plugin guide.
- Provider `source` attribution from Phase 2 is now populated automatically for plugin
  registrations, closing that follow-up.
- A sandbox, plugin removal, or hot reload would each require a new ADR.
