"""Walkthrough — registering plugins: what they contribute, what they read, and when they run.

Run it with:

    python -m learn_extend.plugins01_registration
"""

from __future__ import annotations

from learn_extend.plugin_audit import AuditPlugin, ReportsPlugin
from xyberos import App, Settings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

#: ``[plugins.audit]`` in this walkthrough, in the same shape a configuration file would have it.
SETTINGS = {"plugins": {"audit": {"prefix": "req", "limit": 2}}}


def main() -> None:
    """Configure two plugins, watch the order, and read what each one contributed."""
    app = App(settings=Settings.load(environ={}, overrides=SETTINGS))
    audit = AuditPlugin()
    reports = ReportsPlugin()
    app.add_plugin(audit)
    app.add_plugin(reports)

    print(app.diagnostics().render().strip())

    with create_test_client(HttpAdapter(app)) as client:
        for event in ("ticket-opened", "reply-drafted", "reply-sent"):
            client.post("/audit", json={"event": event})
        print("GET /audit ->", client.get("/audit").json())
        print("GET /reports ->", client.get("/reports").json())

    print("lifecycle hooks ran: started =", audit.started, "stopped =", audit.stopped)


if __name__ == "__main__":
    main()
