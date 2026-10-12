---
title: Writing a plugin
status: verified
---

# Writing a plugin

A plugin is a module with a name, a version, and a configuration schema — plus the one property a
module cannot have: it can be *installed* by somebody else, validated before it runs, and attributed
when it does.

## The trust boundary comes first

**Plugins are trusted, in-process Python code.** Adding one is equivalent to importing a library: it
runs with the full privileges of the process. There is no sandbox, no permission model, and no
protection from a plugin that misbehaves — only the decision to add it
([ADR 0007](../reference/adr/0007-trusted-plugins.md)). There is also no entry-point discovery, so
nothing can become a plugin by being installed: `app.add_plugin(...)` is the only way in, and startup
stays something a reader can follow from the application's own code.

That is the whole reason the metadata on this page exists. `name`, `api_version`, and `config_type` are
not documentation — they are the three things the runtime can check before a line of the plugin runs.

## The shape

<!-- snippet: examples/learn_extend/plugin_audit.py -->

Two plugins live in one module because that is how a distribution usually ships: `AuditPlugin`
contributes a capability and two routes, and `ReportsPlugin` declares `requires = ("audit",)` because it
reads the capability the first one registers. Everything a plugin contributes goes through the same
`app.provide` and `app.get` calls the application itself uses — there is no second API to learn.

## Registering them

<!-- snippet: examples/learn_extend/plugins01_registration.py -->

The application supplies `[plugins.audit]` in its settings, so the plugin's configuration arrives from
the deployment rather than from the plugin's own defaults:

<!-- output: plugins01_registration -->

```text
providers:
  AuditLog [app] from plugin:audit
plugins:
  audit 1 [registered] requires: -
  reports 1 [registered] requires: audit
GET /audit -> {'prefix': 'req', 'events': ['reply-drafted', 'reply-sent']}
GET /reports -> {'count': 2}
lifecycle hooks ran: started = True stopped = True
```

Four things are visible in six lines:

- **`from plugin:audit`.** The provider's source is attributed automatically, so an override you did not
  expect is traceable to the plugin that made it. Application registrations report `from application`.
- **`prefix: 'req'` and the two retained events.** Settings reached the plugin as a typed object, not as
  a dictionary — `limit = 2` came from the same section and is why the list is truncated.
- **`requires: audit` before `reports`.** Registration order is dependency order, and the reported order
  is the start order. A requirement that is not registered yet is refused immediately, which is why
  requirement cycles are impossible rather than merely forbidden.
- **Both hooks ran.** `start` runs after app-scoped providers are constructed; `stop` runs before the
  application closes its own resources.

## Lifecycle, in order

1. `app.add_plugin(plugin)` — validate metadata, build typed configuration, run `register`.
2. `app.start()` — validate the provider graph, construct eager app-scoped providers, start plugins in
   registration order.
3. `app.stop()` — stop plugins in reverse order, then close app-owned resources in reverse order.

A failure in `start` stops the plugins that already started and reports a `PluginLifecycleError` naming
the plugin and the phase, with the original exception kept as the cause. A failure in `stop` is
collected rather than raised: every remaining hook still runs, and the failures surface as
`plugin:<name>` in `ShutdownError.resources`. Shutdown is the one place where stopping late is worse
than reporting loudly.

## The refusals

<!-- snippet: examples/learn_extend/plugins02_refusals.py -->

<!-- output: plugins02_refusals -->

```text
requirement registered second: plugin 'reports' requires audit, which must be registered first
plugin from a later API: plugin 'future' targets plugin API '2', but this runtime supports '1'
name that is not an identifier: plugin name 'audit.log' must be an identifier so it can be used as a configuration key
name registered twice: a plugin named 'audit' is already registered
misspelled setting in [plugins.audit]: plugin 'audit' received unknown configuration key(s): prefx
required setting with no value: plugin 'webhook' is missing the required setting 'plugins.webhook.url'
configuration without a schema: plugin 'plain' received configuration but declares no config_type: url
register hook that raised: plugin 'exploding' failed to register: the plugin could not reach its database
the app that met the last refusal still has 0 plugins
```

Each of those is a mistake that would otherwise be discovered at request time, or never:

| Refusal | When it is raised | What it protects |
| ------- | ----------------- | ---------------- |
| `requires` not yet registered | `add_plugin` | deterministic startup order |
| `api_version` major mismatch | `add_plugin`, before `register` runs | a plugin written for a contract you do not have |
| `name` not an identifier | `add_plugin` | `[plugins.<name>]` as a configuration key |
| name already registered | `add_plugin` | two plugins competing for one name |
| unknown configuration key | `add_plugin` | a typo that would otherwise be ignored |
| required setting with no value | `add_plugin` | a plugin that cannot work without it |
| configuration without a schema | `add_plugin` | a settings section nobody reads |
| an exception inside `register` | `add_plugin` | a half-registered application |

The last line is the point of the whole exercise: after every one of those refusals the application has
no plugins at all. Validation happens before `register`, and a `register` that raises is reported as
`PluginValidationError` naming the plugin and the original error — the framework does not unwind a
partially registered plugin and pretend it succeeded.

## Configuration

Plugin settings follow the same precedence as core settings, and the plugin is the first thing that
narrows them:

1. the explicit mapping passed to `app.add_plugin(plugin, config={...})`
2. the environment — `XYBEROS_PLUGINS__AUDIT__PREFIX`
3. `[plugins.audit]` in the configuration file
4. the dataclass defaults

Fields may be `str`, `int`, `float`, `bool`, or their `| None` forms; numeric strings and the usual
boolean spellings are accepted, because that is what an environment variable provides. Anything else is
a `PluginValidationError` at registration, not a surprise at runtime. Error messages name the plugin and
the setting location — `plugins.audit.prefx` — and never the configured value, since a settings file is
allowed to contain secrets ([plugin configuration](../reference/plugins.md)).

## Publishing one

A plugin package is an ordinary distribution with one dependency and one export:

```text
mycompany-xyberos-webhooks/
├── pyproject.toml            # depends on the xyberos release you target
├── src/mycompany_webhooks/
│   ├── __init__.py           # exports the Plugin subclass
│   └── plugin.py             # name, api_version, config_type, register
└── tests/
    └── test_plugin.py        # imports xyberos, never an internal module
```

This repository ships the pattern rather than describing it. `tests/fixtures/metrics_plugin` is a real
distribution: CI installs it with `pip install --no-deps -e tests/fixtures/metrics_plugin`, and
`tests/integration/test_plugin_packages.py` imports it **as an installed package** and asserts that every
`xyberos` module it imports is part of the public surface. That last assertion is what turns an internal
refactor into your test failing instead of your users breaking, and it is worth copying verbatim:

- **Keep `api_version` honest.** `"1"` means "I use only what the version-1 plugin contract promises". A
  runtime with a different major refuses to load you, before `register` runs.
- **Import public names only.** `xyberos`, `xyberos.plugins`, and the documented `xyberos.*` modules.
- **Validate your own configuration.** Unknown keys are already refused; semantic checks — a URL that
  must be absolute, a limit that must be positive — belong in your own code, at registration.
- **Test it as an installed package**, not as a directory inside your application. The two differ, and
  the difference is exactly what a user will hit.

## Testing with plugins

`app.with_overrides({...})` clones the provider and route registrations but **not** the plugin
registrations, so plugin lifecycle hooks do not run a second time in a test clone. A test that needs a
plugin's *behaviour* should register the plugin on its own application; a test that needs a plugin's
*provider* replaced should override the contract instead, which is the same mechanism every other test
uses.

## Deliberate limitations

- No sandbox, permission model, or isolation of untrusted code.
- No entry-point discovery; plugins are added explicitly.
- A plugin cannot resolve application services from `start`, because the application is not `READY` yet.
  Register an eager provider whose factory does the work, or do it in `register`.
- Plugins cannot be added, removed, or replaced after `app.start()`.

## Where to read next

- [Plugin guide](../reference/plugins.md) — the exhaustive reference: compatibility, the catalogue, and
  the full metadata table.
- [Writing a module](./modules.md) — the unit to write first, if you are not publishing anything.
- [The provider registry](./registry.md) — what a plugin's `app.provide` calls actually do.
