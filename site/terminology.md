---
title: Terminology
status: verified
---

# Terminology

Use the left column in prose and the right column in code. Several names on the left are words other
frameworks use for something different, which is exactly why they are listed.

| Term used here | Name in the code |
| -------------- | ---------------- |
| Provider registry | `ProviderRegistry` for registration, `Inject()` and `app.resolve` for resolution, `app.diagnostics()` for the view |
| Provider | what `app.provide` registers; keyed by a type or a `Protocol` |
| Dependency injection | `Annotated[T, Inject()]`, with `Scope.APP`, `Scope.REQUEST`, `Scope.TRANSIENT` |
| Module | an application package plus a composition root. There is no runtime "module" object to register |
| Plugin | a `Plugin` subclass: `name`, `api_version`, `requires`, `config_type`, `register`, and optional `start` and `stop` |
| Extension module | a plugin distributed as an installable package |
| Workflow | `Workflow`, `Step`, `StepContext`, `WorkflowExecutor` |
| Intent | a `structured` call validated against the closed JSON Schema subset |
| Agent | something you compose: a `ToolSet` plus the workflow engine |
| Model capability | `ModelCapabilities`, enforced through `AIUnsupportedCapabilityError` before any call |
| Capability | **ambiguous, and avoided here.** It means a declared model capability, or what a plugin provides — never a registry of runtime-discovered implementations |
| Startup and shutdown | `app.start()` and `app.stop()`, or `async with app.lifespan()` |

## Two terms that are not interchangeable

**A module is not a plugin.** A module is how you organise an application's own code: a package with a
composition root. A plugin is how someone else's code extends an application, through a declared
contract. The runtime loads plugins and knows nothing about "modules".

**A registry is not a container.** `app.provide` runs while the application is being composed, and
choosing an implementation is a decision the application makes then — not a lookup the runtime performs
per request. There is no way to resolve a provider by writing its name in a parameter, which is why a
misspelled contract is a type error rather than a surprise at runtime.
