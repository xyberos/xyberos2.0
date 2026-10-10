# xyberos-plugin-metrics

A separately distributed example plugin used by the Xyberos test suite. It exists to prove that a
plugin package can contribute a service and a route using only the public `xyberos` API, without
importing runtime internals.

It is imported in tests through `pythonpath` and can be installed with:

```powershell
python -m pip install --no-deps -e tests/fixtures/metrics_plugin
```
