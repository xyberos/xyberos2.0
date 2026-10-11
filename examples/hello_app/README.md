# hello_app example

The smallest complete Xyberos application: a service, two routes, one settings file, and a test
client. It is the code the [getting started guide](../../docs/getting-started.md) walks through.

## Run it

```powershell
python -m pip install -e ".[http]" uvicorn
uvicorn --app-dir examples/hello_app app:asgi_app
```

```powershell
curl http://127.0.0.1:8000/health
curl "http://127.0.0.1:8000/?name=reader"
```

`uvicorn` is not a Xyberos dependency; it is the ASGI server this example uses.

## What each piece is for

| Piece | Why it is here |
| --- | --- |
| `Greeter` | An app-scoped service, provided as an instance and closed by `App.stop()` |
| `GreetingLog` | A request-scoped service: one instance per request, and it may depend on `Greeter` |
| `create_app` | Composition: settings, providers, routes — the whole application in one function |
| `build_asgi_app` | The single place where the optional `http` extra is imported |
| `xyberos.toml` | The configured application name, which the greeting then proves was read |
| `asgi_app` | What an ASGI server imports, so `uvicorn` needs no `--factory` |

## Try a change

- Point the app at a different name: edit `xyberos.toml`, or set
  `$env:XYBEROS_APP__NAME = "another"` and start it again. Environment variables win over the file.
- Break the wiring on purpose: delete `app.provide(GreetingLog, scope=Scope.REQUEST)` and run the
  tests. `App.validate()` reports a missing provider and the resolution path that needed it, which
  is the error you will meet most often while composing an application.
- Read the application without running it: `create_app().diagnostics().render()` lists every
  provider, its scope, and whether it came from the application, a test override, or a plugin.

```powershell
python -m pytest tests/integration/test_hello_app.py
```

See the [runtime guide](../../docs/runtime.md) for scopes, lifecycle, and configuration, the
[HTTP guide](../../docs/http.md) for handlers and error responses, and the
[testing guide](../../docs/testing.md) for the test client used by the integration test.
