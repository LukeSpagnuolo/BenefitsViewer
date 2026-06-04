#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Benefits Viewer Dash app.

Configured for local development and Posit Connect deployment via environment
variables. Posit should use the entrypoint app:app.
"""

import json
import os
import random
import time
from html import escape as html_escape

import pandas as pd
import requests
from dash import Dash, Input, Output, dash_table, html
from dash.exceptions import PreventUpdate
from flask import Response
from dash_auth_external import DashAuthExternal
from requests.exceptions import ConnectTimeout, ConnectionError, HTTPError, ReadTimeout
from werkzeug.exceptions import HTTPException


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


# -------------------------------------------------------------------------
# Runtime Config
# -------------------------------------------------------------------------

REQUIRED_CONFIG = (
    ("BENEFITS_VIEWER_CLIENT_ID", "CLIENT_ID"),
    ("BENEFITS_VIEWER_CLIENT_SECRET", "CLIENT_SECRET"),
    ("BENEFITS_VIEWER_APP_URL", "APP_URL"),
)
MISSING_CONFIG = missing_config(REQUIRED_CONFIG)

CLIENT_ID = env("BENEFITS_VIEWER_CLIENT_ID", "CLIENT_ID", default="")
CLIENT_SECRET = env("BENEFITS_VIEWER_CLIENT_SECRET", "CLIENT_SECRET", default="")

# Django site that hosts OAuth + API.
SITE = env("BENEFITS_VIEWER_SITE", "SITE_URL", default="https://apps.csipacific.ca").rstrip("/")

# Public URL where this Dash app is reachable. In Posit Connect, set this to
# the content URL shown after publishing, without a trailing slash.
APP_URL = env("BENEFITS_VIEWER_APP_URL", "APP_URL", default="http://127.0.0.1:8050").rstrip("/")

AUTH_URL = env("BENEFITS_VIEWER_AUTH_URL", default=f"{SITE}/o/authorize")
TOKEN_URL = env("BENEFITS_VIEWER_TOKEN_URL", default=f"{SITE}/o/token/")
BENEFITS_URL = env("BENEFITS_VIEWER_BENEFITS_URL", default=f"{SITE}/api/benefits/partners/")

PAGE_LIMIT = int(env("BENEFITS_VIEWER_PAGE_LIMIT", default="50"))
MAX_RETRIES = int(env("BENEFITS_VIEWER_MAX_RETRIES", default="5"))
BACKOFF_SEC = float(env("BENEFITS_VIEWER_BACKOFF_SEC", default="1.5"))
REQUEST_TIMEOUT = (
    float(env("BENEFITS_VIEWER_CONNECT_TIMEOUT", default="10")),
    float(env("BENEFITS_VIEWER_READ_TIMEOUT", default="90")),
)
RETRYABLE_STATUSES = (502, 503, 504, 524)


# -------------------------------------------------------------------------
# Helper functions
# -------------------------------------------------------------------------

def safe_str(v):
    if v is None:
        return ""
    if isinstance(v, (str, int, float, bool)):
        return str(v)
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return str(v)


def flatten_json(data, prefix=""):
    """
    Flatten nested dicts/lists into a single-level dict
    using dot notation for keys and '; ' for list values.
    """
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            new_key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            out.update(flatten_json(v, new_key))
    elif isinstance(data, list):
        out[prefix] = "; ".join([safe_str(i) for i in data])
    else:
        out[prefix] = safe_str(data)
    return out


def fetch_paginated(url, headers, log=None):
    """
    Fetch all pages from a DRF-style paginated endpoint.
    """
    if log is None:
        log = []
    if not url:
        return []

    rows = []
    page = 0
    session = requests.Session()

    while url:
        if "limit=" not in url:
            url += ("&" if "?" in url else "?") + f"limit={PAGE_LIMIT}"

        page += 1
        retries = 0
        wait = BACKOFF_SEC

        while True:
            try:
                resp = session.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
                status = resp.status_code

                if status in RETRYABLE_STATUSES and retries < MAX_RETRIES:
                    log.append(
                        f"[page {page}] {url} - {status} -> "
                        f"retry {retries + 1}/{MAX_RETRIES} in {wait:.1f}s"
                    )
                    time.sleep(wait + random.uniform(0, 0.5))
                    retries += 1
                    wait *= 2
                    continue

                if status != 200:
                    log.append(f"[page {page}] {url} - status={status}, stopping.")
                    return rows

                data = resp.json()
                page_results = data.get("results", [])
                rows.extend(page_results)
                url = data.get("next")
                log.append(
                    f"[page {page}] ok, got {len(page_results)} rows, "
                    f"total={len(rows)}, next={url}"
                )
                break

            except (ReadTimeout, ConnectTimeout, ConnectionError) as e:
                if retries < MAX_RETRIES:
                    log.append(
                        f"[page {page}] timeout/conn error {e.__class__.__name__} "
                        f"-> retry {retries + 1}/{MAX_RETRIES} in {wait:.1f}s"
                    )
                    time.sleep(wait + random.uniform(0, 0.5))
                    retries += 1
                    wait *= 2
                    continue

                log.append(
                    f"[page {page}] giving up after {MAX_RETRIES} retries: "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )
                return rows

            except Exception as e:
                log.append(
                    f"[page {page}] unexpected error: "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )
                return rows

    return rows


# -------------------------------------------------------------------------
# App Setup
# -------------------------------------------------------------------------

auth = DashAuthExternal(
    external_auth_url=AUTH_URL,
    external_token_url=TOKEN_URL,
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    app_url=APP_URL,
    with_pkce=False,
)
server = auth.server
app = Dash(__name__, server=server)

cached_df = pd.DataFrame()


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
    <p><strong>Client ID length:</strong> {len(CLIENT_ID)}</p>
    <h2>Detail</h2>
    <pre>{html_escape(safe_str(detail))}</pre>
  </body>
</html>"""
    return Response(body, status=status_code, mimetype="text/html")


# -------------------------------------------------------------------------
# Layout
# -------------------------------------------------------------------------

app.layout = html.Div(
    [
        html.H1("Benefits Viewer"),
        html.Div(
            [
                html.Strong("Missing Posit environment variables: "),
                ", ".join(MISSING_CONFIG),
            ],
            id="config-warning",
            style={
                "display": "block" if MISSING_CONFIG else "none",
                "marginBottom": "0.75rem",
                "padding": "0.75rem",
                "border": "1px solid #b00020",
                "color": "#b00020",
                "fontFamily": "Arial",
            },
        ),
        html.Button("Fetch Data", id="btn-fetch"),
        html.Div(id="status-msg", style={"marginTop": "0.5rem"}),
        dash_table.DataTable(
            id="preview",
            page_size=20,
            style_table={"overflowX": "auto"},
            style_cell={"textAlign": "left", "fontFamily": "Arial", "fontSize": 12},
        ),
    ]
)


# -------------------------------------------------------------------------
# Callbacks
# -------------------------------------------------------------------------

@app.callback(
    Output("preview", "data"),
    Output("preview", "columns"),
    Output("status-msg", "children"),
    Input("btn-fetch", "n_clicks"),
    prevent_initial_call=True,
)
def fetch_and_display(n_clicks):
    global cached_df

    if not n_clicks:
        raise PreventUpdate

    if MISSING_CONFIG:
        return [], [], (
            "App is missing required environment variables: "
            f"{', '.join(MISSING_CONFIG)}."
        )

    token = auth.get_token()
    if not token:
        return [], [], "No OAuth token - please log in."

    headers = {"Authorization": f"Bearer {token}"}
    log = []

    rows = fetch_paginated(BENEFITS_URL, headers, log=log)

    if not rows:
        return [], [], "No data returned from the benefits API or error during fetch."

    flattened = [flatten_json(r) for r in rows]
    df = pd.DataFrame(flattened)
    cached_df = df

    cols = [{"name": c, "id": c} for c in df.columns]
    status = f"Loaded {len(df)} rows from {BENEFITS_URL}."

    return df.to_dict("records"), cols, status


if __name__ == "__main__":
    app.run(
        debug=env("BENEFITS_VIEWER_DEBUG", default="true").lower() == "true",
        host=env("HOST", default="127.0.0.1"),
        port=int(env("PORT", default="8050")),
    )
