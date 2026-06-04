#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Benefits Viewer Dash app.

Posit Connect should use the entrypoint app:app.
"""

import os
from html import escape as html_escape

import dash
import dash_bootstrap_components as dbc
from dash import Dash, Input, Output, dcc, html, no_update
from flask import Response, request
from requests.exceptions import HTTPError
from werkzeug.exceptions import HTTPException

from auth_setup import server
from layout import Footer, Navbar
from settings import APP_URL, AUTH_URL, CLIENT_ID, CLIENT_SECRET, TOKEN_URL


def env(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return default.strip() if isinstance(default, str) else default


def has_env(*names):
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value
    return None


def missing_config(required_options):
    missing = []
    for options in required_options:
        if not has_env(*options):
            missing.append(" or ".join(options))
    return missing


REQUIRED_CONFIG = (
    ("BENEFITS_VIEWER_CLIENT_ID", "CLIENT_ID"),
    ("BENEFITS_VIEWER_CLIENT_SECRET", "CLIENT_SECRET"),
    ("BENEFITS_VIEWER_APP_URL", "APP_URL"),
)
MISSING_CONFIG = missing_config(REQUIRED_CONFIG)


app = Dash(
    __name__,
    server=server,
    use_pages=True,
    suppress_callback_exceptions=True,
    title="Benefits Viewer",
    external_stylesheets=[
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
    ],
)


navbar = Navbar(
    title="Benefits Viewer",
    buttons=[
        {"label": "Registration Data", "url": "/home"},
    ],
)
navbar.register_callbacks(app)


def safe_str(value):
    if value is None:
        return ""
    return str(value)


def oauth_error_response(status_code, heading, message, detail):
    body = f"""<!doctype html>
<html>
  <head>
    <title>Benefits Viewer Error</title>
    <style>
      body {{ font-family: Arial, sans-serif; margin: 2rem; line-height: 1.4; }}
      pre {{ background: #f6f6f6; padding: 1rem; overflow-x: auto; }}
    </style>
  </head>
  <body>
    <h1>{html_escape(heading)}</h1>
    <p>{html_escape(message)}</p>
    <p><strong>Status:</strong> {status_code}</p>
    <p><strong>Authorization URL:</strong> {html_escape(AUTH_URL)}</p>
    <p><strong>Token URL:</strong> {html_escape(TOKEN_URL)}</p>
    <p><strong>App URL:</strong> {html_escape(APP_URL)}</p>
    <p><strong>Redirect URL:</strong> {html_escape(APP_URL)}/redirect</p>
    <p><strong>Client ID length:</strong> {len(CLIENT_ID or "")}</p>
    <p><strong>Client Secret configured:</strong> {"yes" if CLIENT_SECRET else "no"}</p>
    <h2>Detail</h2>
    <pre>{html_escape(safe_str(detail))}</pre>
  </body>
</html>"""
    return Response(body, status=status_code, mimetype="text/html")


@server.before_request
def show_oauth_callback_error():
    if request.path.rstrip("/") != "/redirect":
        return None

    if request.args.get("code"):
        return None

    return oauth_error_response(
        status_code=400,
        heading="OAuth Callback Error",
        message=(
            "The OAuth provider redirected back to the app without an "
            "authorization code."
        ),
        detail=dict(request.args),
    )


@server.errorhandler(HTTPError)
def oauth_http_error(error):
    response = error.response
    status_code = response.status_code if response is not None else 500
    detail = response.text if response is not None else str(error)
    return oauth_error_response(
        status_code=status_code,
        heading="OAuth Error",
        message="The OAuth server rejected the request while this app was logging in.",
        detail=detail,
    )


@server.errorhandler(Exception)
def app_error(error):
    if isinstance(error, HTTPException):
        return error

    return oauth_error_response(
        status_code=500,
        heading="Application Error",
        message="The app hit an error while handling this request.",
        detail=f"{type(error).__name__}: {error}",
    )


def config_warning():
    if not MISSING_CONFIG:
        return None

    return dbc.Alert(
        [
            html.Strong("Missing Posit environment variables: "),
            ", ".join(MISSING_CONFIG),
        ],
        color="danger",
        className="mx-3 mt-3 mb-0",
    )


app.layout = html.Div(
    [
        dcc.Location(id="app-location"),
        navbar.render(),
        config_warning(),
        html.Main(dash.page_container, className="app-main"),
        Footer().render(),
    ],
    className="app-shell",
)


@app.callback(
    Output("app-location", "pathname"),
    Input("app-location", "pathname"),
    prevent_initial_call=False,
)
def redirect_home(pathname):
    if pathname in (None, "", "/"):
        return "/home"
    return no_update


if __name__ == "__main__":
    app.run(
        debug=env("BENEFITS_VIEWER_DEBUG", default="true").lower() == "true",
        host=env("HOST", default="127.0.0.1"),
        port=int(env("PORT", default="8050")),
    )
