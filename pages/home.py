import csv
import io
from datetime import datetime

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, dash_table, dcc, html, no_update
from dash.exceptions import PreventUpdate
import requests

from auth_setup import auth
from layout.offcanvas import OffcanvasComponent
from settings import (
    BENEFITS_PARTNERS_ENDPOINT,
    BENEFITS_REDEMPTIONS_ENDPOINT,
    SITE_URL,
)


dash.register_page(__name__, path="/home")


PAGE_LIMIT = 100
SUMMARY_PAGE_LIMIT = 1000
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

REDEMPTION_SUMMARY_COLUMNS = [
    "partner_name",
    "redemption_count",
    "institution_counts",
    "sport_counts",
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
        "filename": "benefits_redemptions_summary",
        "columns": REDEMPTION_SUMMARY_COLUMNS,
        "default_columns": REDEMPTION_SUMMARY_COLUMNS,
        "summary": True,
        "bounded_summary": True,
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


def _option_value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _first_value(row, candidates, default=""):
    for key in candidates:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _format_counts(counts):
    if not counts:
        return ""
    return ", ".join(
        f"{name}: {count}"
        for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))
    )


def _redemption_partner_name(row):
    return str(
        _first_value(
            row,
            [
                "benefit.partner.name",
                "benefit.partner_name",
                "partner.name",
                "partner_name",
            ],
            default="Unknown partner",
        )
    )


def _redemption_institution(row):
    return str(_first_value(row, ["institution", "institution.name"], default="Unknown institution"))


def _redemption_sport(row):
    return str(_first_value(row, ["profile.sport.name", "profile.sport", "sport.name", "sport"], default="Unknown sport"))


def summarize_redemptions(rows):
    groups = {}

    for row in rows:
        key = _redemption_partner_name(row)

        if key not in groups:
            groups[key] = {
                "partner_name": key,
                "redemption_count": 0,
                "_institution_counts": {},
                "_sport_counts": {},
            }

        summary = groups[key]
        summary["redemption_count"] += 1

        institution = _redemption_institution(row)
        summary["_institution_counts"][institution] = summary["_institution_counts"].get(institution, 0) + 1

        sport = _redemption_sport(row)
        summary["_sport_counts"][sport] = summary["_sport_counts"].get(sport, 0) + 1

    rows = []
    for summary in groups.values():
        rows.append(
            {
                "partner_name": summary["partner_name"],
                "redemption_count": summary["redemption_count"],
                "institution_counts": _format_counts(summary["_institution_counts"]),
                "sport_counts": _format_counts(summary["_sport_counts"]),
            }
        )

    return sorted(
        rows,
        key=lambda row: (-row["redemption_count"], row["partner_name"].lower()),
    )


def filter_redemptions_by_partner(rows, partner_name):
    if not partner_name:
        return []
    expected = str(partner_name).strip().lower()
    return [
        row
        for row in rows
        if _redemption_partner_name(row).strip().lower() == expected
    ]


def _extract_rows(payload, source_key):
    if isinstance(payload, dict) and "results" in payload:
        return payload.get("results") or [], payload.get("count"), payload.get("next")
    if isinstance(payload, dict) and isinstance(payload.get(source_key), list):
        return payload.get(source_key) or [], None, None
    if isinstance(payload, dict) and isinstance(payload.get("data"), list):
        return payload.get("data") or [], None, None
    if isinstance(payload, list):
        return payload, None, None
    if isinstance(payload, dict):
        return [payload], None, None
    return [], None, None


def fetch_partner_options(token):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = SITE_URL.rstrip("/") + BENEFITS_PARTNERS_ENDPOINT
    params = {"limit": SUMMARY_PAGE_LIMIT}
    options = []
    seen = set()

    while url:
        response = requests.get(url, headers=headers, params=params, timeout=60)
        response.raise_for_status()
        page_rows, _total, next_url = _extract_rows(response.json(), "partners")

        for raw_row in page_rows:
            row = _flatten_json(raw_row)
            label = _option_value(row, "name")
            value = _option_value(row, "name", "id")
            if not label or not value or value in seen:
                continue
            options.append({"label": label, "value": value})
            seen.add(value)

        url = next_url
        params = None

    return sorted(options, key=lambda option: option["label"].lower())


def fetch_redemptions_page(endpoint, token, next_url=None):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = next_url or (SITE_URL.rstrip("/") + endpoint)
    params = None if next_url else {"limit": SUMMARY_PAGE_LIMIT}

    response = requests.get(url, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    page_rows, total, next_url = _extract_rows(response.json(), "redemptions")
    raw_rows = [_flatten_json(row) for row in page_rows]

    return raw_rows, total, next_url


def fetch_benefits_page(endpoint, token, source_key, partner_value=None):
    cfg = _source_config(source_key)
    if cfg.get("summary"):
        raw_page_rows, total, next_url = fetch_redemptions_page(endpoint, token)
        matching_rows = filter_redemptions_by_partner(raw_page_rows, partner_value)
        return (
            summarize_redemptions(matching_rows),
            total,
            bool(next_url),
            len(matching_rows),
            raw_page_rows,
            next_url,
        )

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    url = SITE_URL.rstrip("/") + endpoint
    params = {"limit": PAGE_LIMIT}

    response = requests.get(url, headers=headers, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()

    rows, total, next_url = _extract_rows(payload, source_key)

    rows = [_flatten_json(row) for row in rows]
    return rows, total, bool(next_url), len(rows), [], None


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
        dcc.Store(id="redemptions-raw-rows-store", data=[]),
        dcc.Store(id="redemptions-next-url-store"),
        dcc.Store(id="redemptions-total-store"),
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

        html.Div(
            [
                dbc.Label("Partner", className="mb-1"),
                dcc.Dropdown(
                    id="redemptions-partner-select",
                    options=[],
                    value=None,
                    clearable=True,
                    placeholder="Select a partner...",
                ),
            ],
            id="redemptions-partner-control",
            className="mb-3",
            style={"display": "none"},
        ),

        html.Div(
            dbc.Button(
                [html.I(className="bi bi-plus-circle me-1"), "Load More"],
                id="load-more-redemptions-btn",
                color="secondary",
                disabled=True,
            ),
            id="load-more-redemptions-control",
            className="mb-3",
            style={"display": "none"},
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
    Output("redemptions-partner-select", "options"),
    Input("benefits-source-tabs", "active_tab"),
    prevent_initial_call=False,
)
def load_redemptions_partner_options(source_key):
    if source_key != "redemptions":
        return []

    try:
        token = auth.get_token()
    except Exception:
        return []

    try:
        return fetch_partner_options(token)
    except requests.RequestException:
        return []


@dash.callback(
    Output("redemptions-partner-control", "style"),
    Input("benefits-source-tabs", "active_tab"),
)
def toggle_redemptions_partner_control(source_key):
    if source_key == "redemptions":
        return {"display": "block"}
    return {"display": "none"}


@dash.callback(
    Output("load-more-redemptions-control", "style"),
    Output("load-more-redemptions-btn", "disabled"),
    Input("benefits-source-tabs", "active_tab"),
    Input("redemptions-partner-select", "value"),
    Input("redemptions-next-url-store", "data"),
)
def toggle_load_more_control(source_key, partner_value, next_url):
    if source_key != "redemptions":
        return {"display": "none"}, True
    return {"display": "block"}, not bool(partner_value and next_url)


@dash.callback(
    Output("benefits-rows-store", "data"),
    Output("redemptions-raw-rows-store", "data"),
    Output("redemptions-next-url-store", "data"),
    Output("redemptions-total-store", "data"),
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
    Input("redemptions-partner-select", "value"),
    State("columns-select", "value"),
    prevent_initial_call=False,
)
def load_benefits_rows(source_key, _refresh_clicks, partner_value, selected_columns):
    cfg = _source_config(source_key)
    columns = _available_columns(cfg, [])
    defaults = _default_columns(cfg, columns)

    try:
        token = auth.get_token()
    except Exception:
        return [], [], None, None, [], source_key, [], [], [], "No access token yet.", "warning", True

    try:
        rows, total, has_more, raw_count, raw_rows, next_url = fetch_benefits_page(
            cfg["endpoint"],
            token,
            source_key,
            partner_value=partner_value,
        )
    except requests.RequestException as exc:
        return [], [], None, None, [], source_key, [], [], [], f"Could not load {cfg['label']}: {exc}", "danger", True
    except Exception as exc:
        return [], [], None, None, [], source_key, [], [], [], f"Unexpected error loading {cfg['label']}: {exc}", "danger", True

    columns = _available_columns(cfg, rows)
    defaults = _default_columns(cfg, columns)
    selected = [column for column in (selected_columns or []) if column in columns]
    if not selected:
        selected = defaults or columns

    if cfg.get("summary"):
        if not partner_value:
            if total is not None and has_more:
                message = (
                    f"Loaded first {len(raw_rows)} of {total} redemptions. "
                    "Select a partner to summarize this scanned set."
                )
            else:
                message = (
                    f"Loaded {len(raw_rows)} redemptions. "
                    "Select a partner to summarize this scanned set."
                )
        elif total is not None and has_more:
            message = (
                f"Found {raw_count} matching redemptions on this page. "
                "Use Load More to scan the next page."
            )
        else:
            message = (
                f"Found {raw_count} matching redemptions. "
                "Full redemptions set has been scanned."
            )
    elif total is not None and has_more:
        message = f"Loaded first {len(rows)} of {total} {cfg['label'].lower()} rows."
    else:
        message = f"Loaded {len(rows)} {cfg['label'].lower()} rows."

    return (
        rows,
        raw_rows,
        next_url,
        total,
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
    Output("benefits-rows-store", "data", allow_duplicate=True),
    Output("redemptions-raw-rows-store", "data", allow_duplicate=True),
    Output("redemptions-next-url-store", "data", allow_duplicate=True),
    Output("rows-toast", "children", allow_duplicate=True),
    Output("rows-toast", "icon", allow_duplicate=True),
    Output("rows-toast", "is_open", allow_duplicate=True),
    Input("load-more-redemptions-btn", "n_clicks"),
    State("redemptions-next-url-store", "data"),
    State("redemptions-raw-rows-store", "data"),
    State("redemptions-partner-select", "value"),
    prevent_initial_call=True,
)
def load_more_redemptions(n_clicks, next_url, current_rows, partner_value):
    if not n_clicks or not next_url or not partner_value:
        raise PreventUpdate

    try:
        token = auth.get_token()
    except Exception:
        return no_update, no_update, no_update, "No access token yet.", "warning", True

    try:
        page_rows, _total, next_page_url = fetch_redemptions_page(
            BENEFITS_REDEMPTIONS_ENDPOINT,
            token,
            next_url=next_url,
        )
    except requests.RequestException as exc:
        return no_update, no_update, no_update, f"Could not load more redemptions: {exc}", "danger", True

    combined_rows = (current_rows or []) + page_rows
    matching_rows = filter_redemptions_by_partner(combined_rows, partner_value)
    summary_rows = summarize_redemptions(matching_rows)

    if next_page_url:
        message = (
            f"Scanned {len(combined_rows)} redemptions and found {len(matching_rows)} matching rows. "
            "More pages are available."
        )
    else:
        message = (
            f"Scanned {len(combined_rows)} redemptions and found {len(matching_rows)} matching rows. "
            "Full redemptions set has been scanned."
        )

    return summary_rows, combined_rows, next_page_url, message, "success", True


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
