#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compatibility launcher.

Posit Connect should use app.py with entrypoint app:app. This file is kept so
existing local habits like `python Benefits_Viewer_2.0.py` still work.
"""

from app import app, env


if __name__ == "__main__":
    app.run(
        debug=env("BENEFITS_VIEWER_DEBUG", default="true").lower() == "true",
        host=env("HOST", default="127.0.0.1"),
        port=int(env("PORT", default="8050")),
    )
