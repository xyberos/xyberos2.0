"""Walkthrough — composing modules into one application, and replacing one of them in a test.

Run it with:

    python -m learn_extend.modules01_composition
"""

from __future__ import annotations

from learn_extend import module_pricing, module_rates
from learn_extend.module_rates import Rates
from xyberos import App, Settings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


def create_app() -> App:
    """The application's own module: it decides which pieces exist, and in which order.

    This function is also the target a deployment points at —
    ``xyberos check --app pricing.app:create_app --app-dir src`` — which is why it takes no
    required arguments. A factory with required arguments is a factory the CLI and an ASGI server
    cannot call.
    """
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "pricing"}}))
    module_rates.register(app)
    module_pricing.register(app)
    return app


def main() -> None:
    """Compose two modules, serve them, and then swap one module's answer without editing either."""
    app = create_app()
    print("routes:", [f"{route.method} {route.path}" for route in app.routes])
    print(app.diagnostics().render().strip())

    with create_test_client(HttpAdapter(app)) as client:
        print("GET /rates/SAVE10 ->", client.get("/rates/SAVE10").json())
        print("GET /quote ->", client.get("/quote?code=SAVE10&price=100").json())

        under_test = app.with_overrides({Rates: Rates({"SAVE10": 0.5})})
        with create_test_client(HttpAdapter(under_test)) as tested:
            print(
                "the same routes, a test's rates ->",
                tested.get("/quote?code=SAVE10&price=100").json(),
            )
            print("the clone is a different application:", under_test is not app)


if __name__ == "__main__":
    main()
