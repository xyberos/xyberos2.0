"""Lesson 10 — server-rendered pages over the same handlers.

Run it with:

    python -m learn_traditional.traditional10_pages
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from httpx import Response
from user_management.app import create_app
from user_management.identity import PrincipalVerifier
from user_management.migrate import migrate

from xyberos.database import SqliteSettings
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

SECRET = "a-secret-the-deployment-keeps"
ADMIN_HEADERS = PrincipalVerifier(SECRET).headers("admin@idp", "admin")

MARKUP = "<script>alert(1)</script>"


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        settings = SqliteSettings(path=Path(directory) / "users.db")
        migrate(settings)

        app = create_app(settings=settings, secret=SECRET)
        with create_test_client(HttpAdapter(app)) as client:
            client.headers.update(ADMIN_HEADERS)

            page: Response = client.get("/pages/users")
            print("GET /pages/users ->", page.status_code, page.headers["content-type"])
            print("an empty table and a form:", "<table" in page.text, "<form" in page.text)

            created = client.post(
                "/pages/users",
                data={"email": "grace@example.com", "display_name": "Grace Hopper"},
                follow_redirects=False,
            )
            print("POST /pages/users ->", created.status_code, created.headers["location"])
            print("the new row appears:", "Grace Hopper" in client.get("/pages/users").text)

            refused = client.post(
                "/pages/users",
                data={"email": "not-an-email", "display_name": "Nobody"},
                follow_redirects=False,
            )
            print("POST with a bad address ->", refused.status_code)
            print("the form keeps what was typed:", 'value="not-an-email"' in refused.text)
            print("and the refusal is text, not markup:", "&lt;" not in refused.text)

            posted = client.post(
                "/pages/users",
                data={"email": "markup@example.com", "display_name": MARKUP},
                follow_redirects=False,
            )
            rendered = client.get("/pages/users").text
            print("POST with markup ->", posted.status_code)
            print("the markup is escaped:", "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered)
            print("and none of it is raw:", MARKUP not in rendered)


if __name__ == "__main__":
    main()
