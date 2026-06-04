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

import pandas as pd
import requests
from dash import Dash, Input, Output, dash_table, html
from dash.exceptions import PreventUpdate
from dash_auth_external import DashAuthExternal
from requests.exceptions import ConnectTimeout, ConnectionError, ReadTimeout


def env(name, default=None):
    return os.environ.get(name, default)


# -------------------------------------------------------------------------
# Runtime Config
# -------------------------------------------------------------------------

REQUIRED_CONFIG = (
    "BENEFITS_VIEWER_CLIENT_ID",
    "BENEFITS_VIEWER_CLIENT_SECRET",
    "BENEFITS_VIEWER_APP_URL",
)
MISSING_CONFIG = [name for name in REQUIRED_CONFIG if not os.environ.get(name)]

CLIENT_ID = env("BENEFITS_VIEWER_CLIENT_ID", "")
CLIENT_SECRET = env("BENEFITS_VIEWER_CLIENT_SECRET", "")

# Django site that hosts OAuth + API.
SITE = env("BENEFITS_VIEWER_SITE", "https://apps.csipacific.ca").rstrip("/")

# Public URL where this Dash app is reachable. In Posit Connect, set this to
# the content URL shown after publishing, without a trailing slash.
APP_URL = env("BENEFITS_VIEWER_APP_URL", "http://127.0.0.1:8050").rstrip("/")

AUTH_URL = env("BENEFITS_VIEWER_AUTH_URL", f"{SITE}/o/authorize")
TOKEN_URL = env("BENEFITS_VIEWER_TOKEN_URL", f"{SITE}/o/token/")
BENEFITS_URL = env("BENEFITS_VIEWER_BENEFITS_URL", f"{SITE}/api/benefits/partners/")

PAGE_LIMIT = int(env("BENEFITS_VIEWER_PAGE_LIMIT", "50"))
MAX_RETRIES = int(env("BENEFITS_VIEWER_MAX_RETRIES", "5"))
BACKOFF_SEC = float(env("BENEFITS_VIEWER_BACKOFF_SEC", "1.5"))
REQUEST_TIMEOUT = (
    float(env("BENEFITS_VIEWER_CONNECT_TIMEOUT", "10")),
    float(env("BENEFITS_VIEWER_READ_TIMEOUT", "90")),
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

auth = DashAuthExternal(AUTH_URL, TOKEN_URL, APP_URL, CLIENT_ID, CLIENT_SECRET)
server = auth.server
app = Dash(__name__, server=server)

cached_df = pd.DataFrame()


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
        debug=env("BENEFITS_VIEWER_DEBUG", "true").lower() == "true",
        host=env("HOST", "127.0.0.1"),
        port=int(env("PORT", "8050")),
    )
