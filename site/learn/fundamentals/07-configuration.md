---
title: Add configuration
path: fundamentals
lesson: 7
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals07_configuration.py
prerequisites: ["/learn/fundamentals/04-your-first-application"]
---

# Lesson 7 — add configuration

## What you will build

One setting, read from three places, to show which one wins. Nothing is hard-coded and nothing is
global: configuration is read once, by the application, and reached through it.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## Where settings come from

Four sources, and the highest one in this list wins:

1. **explicit arguments** passed in code,
2. **environment variables** starting with `XYBEROS_`,
3. **the file** `xyberos.toml`,
4. **defaults**.

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals07_configuration.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals07_configuration
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals07_configuration
    ```

## What it prints

<!-- output: fundamentals07_configuration -->
```text
from the file: tutorial staging True
the environment wins: from-the-environment
arguments win: from-the-arguments
```

The same file is loaded three times with different inputs, which is why the module writes its
`xyberos.toml` into a temporary directory instead of the working directory — a lesson that leaves a
config file behind is a lesson that changes the next one's result.

## The lines that matter

| You write | You get |
| --- | --- |
| `[app] name = "tutorial"` | `settings.app.name` |
| `XYBEROS_APP__NAME=tutorial` | the same setting, from the environment |
| `XYBEROS_CONFIG=/etc/xyberos.toml` | a different file to read |
| `Settings.load(overrides={"app": {"debug": True}})` | an explicit argument, the highest precedence |

The double underscore in `XYBEROS_APP__NAME` is not a typo: a single `_` separates words inside a
name, and `__` walks into a section. So `XYBEROS_APP__SHUTDOWN_TIMEOUT` sets `[app] shutdown_timeout`.

## Common mistakes

- **Looking for a global.** There is no module-level settings object and no `app.name` shortcut.
  Read it through the application: `app.settings.app.name`.
- **Misspelling a key and expecting a default.** An unknown key is an error, not silence. The message
  names the field and the source it came from, and never the value, because a value can be a secret.

- **Editing the file to change a deployment.** That is what the precedence order is for: a deployment
  sets an environment variable and leaves everything under version control alone.

## Exercise

Set the application name from the environment, without changing the file.

<details>
<summary>Show the answer</summary>

=== "PowerShell"

    ```powershell
    $env:XYBEROS_APP__NAME = "from-the-environment"
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals07_configuration
    ```

=== "POSIX"

    ```bash
    XYBEROS_APP__NAME=from-the-environment PYTHONPATH=src:examples \
      python -m learn_fundamentals.fundamentals07_configuration
    ```

The file still says `tutorial`, and the first line of output still shows it — but the setting the
lesson cares about now comes from the environment, which is how a deployment changes configuration
without editing anything under version control.
</details>

## Next

Lesson 8 is where the wiring becomes interesting: a service that needs another service, and what the
runtime does when one is missing. Until it is published, [the roadmap](../../roadmap.md) shows where
each lesson stands.
