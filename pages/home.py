import csv
import io
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dash_table, dcc, html
from dash.exceptions import PreventUpdate
import requests

from auth_setup import auth
from layout.offcanvas import OffcanvasComponent
from settings import BENEFITS_PARTNERS_ENDPOINT, BENEFITS_REDEMPTIONS_ENDPOINT, SITE_URL


dash.register_page(__name__, path="/home")


PAGE_LIMIT = 100
DEFAULT_PAGE_SIZE = 25

PARTNER_COLUMNS = [
    "id",
    "created_at",
    "updated_at",
    "name",
    "description",
    "logo",
    "address_line_1",
    "address_line_2",
    "city",
    "state_or_province",
    "postal_code",
    "country",
    "url",
    "created_by",
    "updated_by",
    "updated_by_profile",
    "institutions",
    "relevant_campuses",
]

PARTNER_DEFAULT_COLUMNS = [
    "name",
    "description",
    "address_line_1",
    "city",
    "state_or_province",
    "postal_code",
    "country",
    "url",
    "institutions",
    "relevant_campuses",
]

SOURCES = {
    "partners": {
        "label": "Partners",
        "endpoint": BENEFITS_PARTNERS_ENDPOINT,
        "filename": "benefits_partners",
        "columns": PARTNER_COLUMNS,
        "default_columns": PARTNER_DEFAULT_COLUMNS,
    },
    "redemptions": {
        "label": "Redemptions",
        "endpoint": BENEFITS_REDEMPTIONS_ENDPOINT,
        "filename": "benefits_redemptions",
    },
}


def _source_config(source_key):
    return SOURCES.get(source_key) or SOURCES["partners"]


def _safe_cell(value):
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return ", ".join(str(_safe_cell(item)) for item in value if _safe_cell(item) != "")
    if isinstance(value, dict):
        return ", ".join(
            f"{key}: {_safe_cell(item)}"
            for key, item in value.items()
            if _safe_cell(item) != ""
        )
    return str(value)


def _flatten_json(value, prefix=""):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            next_key = f"{prefix}.{key}" if prefix else str(key)
            out.update(_flatten_json(item, next_key))
        return out

    if isinstance(value, list):
        return {prefix: _safe_cell(value)}

    return {prefix: _safe_cell(value)}


def _columns_from_rows(rows):
    columns = []
    seen = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    return columns


def _available_columns(cfg, rows):
    return list(cfg.get("columns") or _columns_from_rows(rows))


def _default_columns(cfg, available_columns):
    defaults = cfg.get("default_columns") or available_columns
    return [column for column in defaults if column in available_columns]


def _column_options(columns):
    return [{"label": column, "value": column} for column in columns]


def _table_columns(columns):
    return [{"id": column, "name": column} for column in columns]


def _subset_rows(rows, columns):
    return [{column: row.get(column, "") for column in columns} for row in rows]


def fetch_benefits_page(endpoint, token, source_key):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = SITE_URL.rstrip("/") + endpoint
    params = {"limit": PAGE_LIMIT}

    response = requests.get(url, headers=headers, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    total = None
    has_more = False

    if isinstance(payload, dict) and "results" in payload:
        rows = payload.get("results") or []
        total = payload.get("count")
        has_more = bool(payload.get("next"))
    elif isinstance(payload, dict) and isinstance(payload.get(source_key), list):
        rows = payload.get(source_key) or []
    elif isinstance(payload, dict) and isinstance(payload.get("data"), list):
        rows = payload.get("data") or []
    elif isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = [payload]
    else:
        rows = []

    return [_flatten_json(row) for row in rows], total, has_more


fields_layout = [
    dbc.Label("Fields", className="mt-3"),
    dcc.Checklist(
        id="columns-select",
        options=[],
        value=[],
        inputStyle={"marginRight": "0.5rem"},
        labelStyle={"display": "block", "marginBottom": "0.35rem"},
        style={
            "maxHeight": "60vh",
            "overflowY": "auto",
        },
        persistence=False,
    ),
    dbc.Button("Apply Fields", id="apply-columns", color="primary", className="mt-3"),
]

fields_panel = OffcanvasComponent(
    id_prefix="benefits-fields",
    title="Fields",
    children=fields_layout,
    placement="end",
    toggle_classname="me-2",
    toggle_children=html.I(className="bi bi-table"),
)


layout = dbc.Container(
    [
        dcc.Store(id="benefits-rows-store", data=[]),
        dcc.Store(id="available-columns-store", data=[]),
        dcc.Store(id="applied-columns-store", data=[]),
        dcc.Store(id="active-source-store", data="partners"),
        dcc.Download(id="download-csv"),

        html.Div(
            dbc.Toast(
                id="rows-toast",
                header="Benefits Data",
                is_open=False,
                dismissable=True,
                duration=2500,
                icon="info",
            ),
            style={
                "position": "fixed",
                "top": "1rem",
                "left": "50%",
                "transform": "translateX(-50%)",
                "width": "420px",
                "maxWidth": "90vw",
                "zIndex": 2000,
            },
        ),

        dbc.Row(
            [
                dbc.Col([html.H3("Benefits Data")]),
                dbc.Col(
                    [
                        dbc.Button(
                            html.I(className="bi bi-arrow-clockwise"),
                            id="refresh-data-btn",
                            color="secondary",
                            className="me-2",
                            title="Refresh",
                        ),
                        dbc.Button(
                            html.I(className="bi bi-download"),
                            id="download-csv-btn",
                            color="secondary",
                            className="me-2",
                            title="Download CSV",
                        ),
                        fields_panel.toggle_button,
                    ],
                    width="auto",
                    className="ms-auto d-flex justify-content-end",
                ),
            ],
            className="my-3 align-items-start",
        ),

        dbc.Tabs(
            [
                dbc.Tab(label=cfg["label"], tab_id=key)
                for key, cfg in SOURCES.items()
            ],
            id="benefits-source-tabs",
            active_tab="partners",
            className="mb-3",
        ),

        fields_panel.offcanvas,

        dash_table.DataTable(
            id="rows-table",
            columns=[],
            data=[],
            page_action="native",
            page_current=0,
            page_size=DEFAULT_PAGE_SIZE,
            sort_action="native",
            filter_action="native",
            style_table={
                "overflowX": "auto",
            },
            style_cell={
                "fontFamily": "Arial, sans-serif",
                "fontSize": "0.875rem",
                "padding": "0.25rem 0.5rem",
                "textAlign": "left",
                "whiteSpace": "normal",
                "height": "auto",
                "minWidth": "120px",
                "maxWidth": "320px",
            },
            style_header={
                "fontFamily": "Arial, sans-serif",
                "fontSize": "0.875rem",
                "fontWeight": "600",
                "textAlign": "left",
            },
        ),
    ],
    fluid=True,
)


@dash.callback(
    Output("benefits-rows-store", "data"),
    Output("available-columns-store", "data"),
    Output("active-source-store", "data"),
    Output("columns-select", "options"),
    Output("columns-select", "value"),
    Output("applied-columns-store", "data"),
    Output("rows-toast", "children"),
    Output("rows-toast", "icon"),
    Output("rows-toast", "is_open"),
    Input("benefits-source-tabs", "active_tab"),
    Input("refresh-data-btn", "n_clicks"),
    State("columns-select", "value"),
    prevent_initial_call=False,
)
def load_benefits_rows(source_key, _refresh_clicks, selected_columns):
    cfg = _source_config(source_key)

    try:
        token = auth.get_token()
    except Exception:
        return [], [], source_key, [], [], [], "No access token yet.", "warning", True

    try:
        rows, total, has_more = fetch_benefits_page(cfg["endpoint"], token, source_key)
    except requests.RequestException as exc:
        return [], [], source_key, [], [], [], f"Could not load {cfg['label']}: {exc}", "danger", True
    except Exception as exc:
        return [], [], source_key, [], [], [], f"Unexpected error loading {cfg['label']}: {exc}", "danger", True

    columns = _available_columns(cfg, rows)
    defaults = _default_columns(cfg, columns)
    selected = [column for column in (selected_columns or []) if column in columns]
    if not selected:
        selected = defaults or columns

    if total is not None and has_more:
        message = f"Loaded first {len(rows)} of {total} {cfg['label'].lower()} rows."
    else:
        message = f"Loaded {len(rows)} {cfg['label'].lower()} rows."

    return (
        rows,
        columns,
        source_key,
        _column_options(columns),
        selected,
        selected,
        message,
        "success",
        True,
    )


@dash.callback(
    Output("applied-columns-store", "data", allow_duplicate=True),
    Output("benefits-fields-offcanvas", "is_open", allow_duplicate=True),
    Input("apply-columns", "n_clicks"),
    State("columns-select", "value"),
    State("available-columns-store", "data"),
    State("active-source-store", "data"),
    prevent_initial_call=True,
)
def apply_columns(_n, columns_value, available_columns, source_key):
    cfg = _source_config(source_key)
    applied = [column for column in (columns_value or []) if column in (available_columns or [])]
    return applied or _default_columns(cfg, available_columns or []), False


@dash.callback(
    Output("rows-table", "columns"),
    Output("rows-table", "data"),
    Output("rows-table", "page_current"),
    Input("benefits-rows-store", "data"),
    Input("applied-columns-store", "data"),
)
def render_table(rows, columns):
    columns = columns or _columns_from_rows(rows or [])
    return _table_columns(columns), _subset_rows(rows or [], columns), 0


@dash.callback(
    Output("download-csv", "data"),
    Input("download-csv-btn", "n_clicks"),
    State("benefits-source-tabs", "active_tab"),
    State("benefits-rows-store", "data"),
    State("applied-columns-store", "data"),
    prevent_initial_call=True,
)
def download_rows(n_clicks, source_key, rows, columns):
    if not n_clicks:
        raise PreventUpdate

    rows = rows or []
    columns = columns or _columns_from_rows(rows)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(_subset_rows(rows, columns))

    cfg = _source_config(source_key)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return {
        "content": buf.getvalue(),
        "filename": f"{cfg['filename']}_{timestamp}.csv",
        "type": "text/csv",
    }
