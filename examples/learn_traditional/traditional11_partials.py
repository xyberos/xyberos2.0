"""Lesson 11 — one route, two clients: a full page or a swapped row.

Run it with:

    python -m learn_traditional.traditional11_partials
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from user_management.app import HX_REQUEST, create_app
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate

from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)
            for email in ("ada@example.com", "grace@example.com"):
                client.post(
                    "/pages/users",
                    data={"email": email, "display_name": email.split("@")[0].title()},
                )

            without = client.post("/pages/users/1/toggle", follow_redirects=False)
            print("toggle without HTMX ->", without.status_code, without.headers["location"])

            with_htmx = client.post(
                "/pages/users/2/toggle", headers={HX_REQUEST: "true"}, follow_redirects=False
            )
            print("toggle with HTMX ->", with_htmx.status_code, with_htmx.headers["content-type"])
            print("the answer is one row:", with_htmx.text.count("<tr") == 1)
            print("no page around it:", "<html" not in with_htmx.text)
            print("the row carries the swap target:", 'id="user-2"' in with_htmx.text)
            print("and the button now offers the other state:", "Enable" in with_htmx.text)

            page = client.get("/pages/users").text
            print("the list renders the same row:", 'id="user-2"' in page, "Enable" in page)
            print("with the styling in place:", 'class="w-full' in page)


if __name__ == "__main__":
    main()
