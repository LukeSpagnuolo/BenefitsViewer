
from dataclasses import dataclass
from typing import Any, Optional

import dash_bootstrap_components as dbc
from dash import Input, Output, State, html
import dash


@dataclass(frozen=True)
class OffcanvasIds:
    prefix: str
    offcanvas: str
    toggle_button: str


class OffcanvasComponent:
    """
    Generic Offcanvas + toggle button + callback wiring.

    Usage:
        off = OffcanvasComponent(app, id_prefix="filters", title="Filters", children=my_filters_layout)
        layout = html.Div([off.offcanvas, off.toggle_button])

    Notes:
      - IDs are derived from id_prefix for safe reuse.
      - Registers only the toggle callback.
      - Does not assume anything about the content (filters) inside.
    """

    def __init__(
        self,
        app=None,
        *,
        id_prefix: str,
        children,
        title: str = "Panel",
        placement: str = "end",
        is_open_default: bool = False,
        toggle_children=None,
        toggle_color: str = "secondary",
        toggle_classname: str = "",
        offcanvas_kwargs: Optional[dict] = None,
        button_kwargs: Optional[dict] = None,
    ):
        self.app = app or dash.get_app()

        # ids
        self.ids = OffcanvasIds(
            prefix=id_prefix,
            offcanvas=f"{id_prefix}-offcanvas",
            toggle_button=f"{id_prefix}-toggle",
        )

        offcanvas_kwargs = offcanvas_kwargs or {}
        button_kwargs = button_kwargs or {}

        self.offcanvas = dbc.Offcanvas(
            children,
            id=self.ids.offcanvas,
            title=title,
            is_open=is_open_default,
            placement=placement,
            **offcanvas_kwargs,
        )

        if toggle_children is None:
            toggle_children = html.I(className="bi bi-sliders me-1")

        self.toggle_button = dbc.Button(
            toggle_children,
            id=self.ids.toggle_button,
            n_clicks=0,
            color=toggle_color,
            className=toggle_classname,
            **button_kwargs,
        )

        self._register_callbacks()

    def _register_callbacks(self):
        @self.app.callback(
            Output(self.ids.offcanvas, "is_open", allow_duplicate=True),
            Input(self.ids.toggle_button, "n_clicks"),
            State(self.ids.offcanvas, "is_open"),
            prevent_initial_call=True,
        )
        def _toggle(n_clicks, is_open):
            if n_clicks:
                return not is_open
            return is_open
