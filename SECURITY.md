# Security policy

Xyberos is an application framework: it runs trusted code in your process and keeps untrusted input
at the boundaries. The [security guide](docs/security.md) states the trust model, the secrets
handling rules, the resource limits, and — explicitly — what the framework does not protect you
from. Read that first if you are deciding whether to deploy it.

## Reporting a vulnerability

Report privately, **not** in a public issue. Use GitHub's private vulnerability reporting on the
repository ("Security" → "Report a vulnerability"); if that is unavailable, contact the project
owner directly by the address listed on the repository profile.

Please include:

- the version (`xyberos.__version__`, and the versions of any extras you installed),
- the configuration that matters — which extras, which provider, which backend,
- the smallest reproduction you can manage, and
- what you believe the impact is.

Do not include live credentials, personal data, or anything else you would not want disclosed.

## What is in scope

A defect in Xyberos itself with security consequences:

- an input path where untrusted data reaches something it should not (a client-safe message leaking
  an internal one, a configured value appearing in a log or an error, a payload written where it was
  refused);
- a durable-execution defect where an execution resumes against work it should not, or a refused
  write is applied anyway;
- a dependency *requirement* that is wrong in a way we introduced (for example an unfloored range
  that lets a vulnerable release be selected);
- anything that breaks a guarantee stated in [ADR 0013](docs/adr/0013-stable-surface-and-versioning.md)
  or a limits section of a guide.

## What is out of scope

- **A vulnerability in a dependency.** Report it upstream; tell us as well if the fix needs a range
  change here.
- **Anything that requires the attacker to already run code in your process.** Plugins, step
  functions, and tool handlers are trusted by design — see the plugin guide's trust boundary. A
  "malicious plugin" is not a vulnerability.
- **A deployment's own misconfiguration**: no TLS terminator, no rate limits, secrets in
  `xyberos.toml`, `debug = true` in production, a database file readable by everyone.
- **The absence of a feature**: no sandbox, no authorization model, no secret manager, no encryption
  at rest. These are documented omissions, not defects.
- **Denial of service by resource exhaustion at the transport layer**. Request size and rate limits
  belong to the ASGI server and the reverse proxy.

## Supported versions

There is no release yet. Once there is, the supported line is the newest `0.x` release, and a fix is
shipped as a patch release on that line. Before `1.0.0` there is no long-term support line and no
back-porting to older minors: a `0.x` minor may be a breaking change, so the upgrade path is the fix.

## What to expect

- **Acknowledgement** within a few working days.
- **An assessment** — affected versions, impact, and whether it is a defect — within about ten
  working days, sooner for something trivially exploitable.
- **A fix** in a patch release when the fix is contained. If it needs a breaking change before
  `1.0.0`, it lands in the next minor release and the release notes say so.
- **Disclosure with the release that carries the fix**, including the impact, the affected versions,
  and the workaround if there was one. A reporter who asks to be credited is credited.

If a report turns out not to be a vulnerability, you get the reasoning rather than silence.

## For maintainers

- Reproduce before assessing, and write the regression test before the fix: this repository's rule is
  that evidence precedes a conclusion.
- A security fix never goes in unannounced. Record it in `CHANGELOG.md` under "Security", with the
  impact and the affected versions, and reference it from the release notes.
- If the fix requires a dependency range change, say which range and why; the ranges in
  `pyproject.toml` are floored rather than capped, so a newer vulnerable release is reachable by
  resolution and the floor is the thing to move.
- If a release has to be withdrawn, follow the rollback steps in
  [the release guide](docs/release.md).
