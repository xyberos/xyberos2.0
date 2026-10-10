# custom_plugin example

Shows how to author a plugin that contributes a capability, a route, and typed configuration.

## Run it

```powershell
python -m pip install -e ".[http]" uvicorn
uvicorn --app-dir examples/custom_plugin --factory app:app_factory
```

`GET /greet` returns `{"message": "hello, world"}`.

## What it demonstrates

| Piece | Purpose |
| --- | --- |
| `GreetingConfig` | a dataclass configuration schema, validated before registration |
| `Greeter` | the capability the plugin contributes to the application |
| `GreetingPlugin.register` | registers a provider and a route through the public `App` API |
| `GreetingPlugin.start` / `stop` | optional lifecycle hooks for plugin-owned resources |

Configuration can also come from settings instead of the explicit mapping:

```toml
[plugins.greeting]
greeting = "hey"
excited = true
```

```powershell
$env:XYBEROS_PLUGINS__GREETING__GREETING = "hi"
```

See the [plugin guide](../../docs/plugins.md).
