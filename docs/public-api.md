# Public API and compatibility policy

This policy identifies supported imports for the `xyberos-minimal` distribution
(import package: `xyberos`). It applies to documented public APIs starting with
the next published release. A symbol being importable in Python does not, by
itself, make it part of the supported API.

## Supported surface

The following are supported public entry points:

- Root package metadata and namespaces:
  `xyberos.__version__`, `xyberos.kernel`, `xyberos.http`,
  `xyberos.providers`, and `xyberos.subsystems`.
- Supported import patterns that are covered by runtime regression tests:
  `from xyberos import kernel, http, providers, subsystems`,
  `from xyberos.kernel import AuthenticatedIdentity, ExecutionContext,
  PolicyEngine, XyberosKernel`, and direct imports from the module-level provider
  and subsystem packages such as `xyberos.providers.database`,
  `xyberos.providers.p2p`, `xyberos.subsystems.database`, and
  `xyberos.subsystems.p2p`.
- Names listed in `__all__` by `xyberos.kernel` and the subsystem packages that
  declare it: `xyberos.subsystems.ai`, `.blob`, `.database`, `.flows`,
  `.knowledge`, `.memory`, and `.p2p`.
- HTTP integration points documented in the README and tutorial:
  `IdentityResolver`, `XyberosContextMiddleware`,
  `KernelAdmissionMiddleware`, and `create_health_routes`.
- First-party provider implementations imported from their documented provider
  modules, when those modules are explicitly identified in the README, tutorial,
  or deployment documentation. Provider-specific configuration remains subject
  to the provider's documented contract.

The root namespaces are lazy module entry points, not promises that every
implementation detail beneath them is stable. In particular, private names
(leading underscore), undocumented modules, helper functions, and internal
classes are not supported API. Provider and optional subsystem implementations
may evolve independently where no compatibility is documented. Importing a
provider or subsystem from a root package path is not a compatibility promise
unless that module is explicitly documented and tested as part of the public
surface.

## Versioning and deprecation

- Xyberos follows Semantic Versioning for the supported public surface:
  compatible additions and fixes use a minor or patch release; incompatible
  public API changes require a major release. Raising the minimum supported
  Python version is a breaking change and requires a major release.
- Mark a public API as deprecated in documentation and emit a
  `DeprecationWarning` where practical before removing or changing it. The
  deprecation notice should identify the replacement and target removal release.
- Keep a deprecated public API available through at least one subsequent minor
  release before removal, unless a security issue or other exceptional risk
  requires a shorter window. Document the reason and migration guidance when
  shortening the window.
- Optional dependencies and provider-specific behavior are not guaranteed to be
  identical across implementations. Their supported Python versions and tested
  configurations are bounded by package metadata, CI, and the relevant provider
  documentation.

## Python support

The package declares Python 3.10 or newer (`requires-python = ">=3.10"`). CI
currently tests Python 3.10, 3.11, 3.12, and 3.13. The declared lower bound and
the tested CI matrix are different statements: behavior on Python versions
outside the current matrix is not certified by that matrix.

## Distribution validation

CI builds both the wheel and source distribution, installs the wheel in a clean
environment, and imports the documented package entry points outside the source
checkout. This verifies packaging and importability, not the behavior or
production suitability of every optional provider.

If a symbol needs to become a supported API, add it to the package's explicit
exports where appropriate, document its import path and compatibility status,
and add a regression test for that documented usage.
