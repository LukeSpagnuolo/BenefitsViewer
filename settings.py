import os

from dotenv import load_dotenv

load_dotenv()

"""
.env example

CLIENT_ID=<from oauth>
CLIENT_SECRET=<from oauth>

SITE_URL=http://<address>:8000
APP_URL=http://<address>:8050

"""

def env(*names, default=None):
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return default


SITE_URL = env("BENEFITS_VIEWER_SITE", "SITE_URL", default="http://127.0.0.1:8000").rstrip("/")
APP_URL = env("BENEFITS_VIEWER_APP_URL", "APP_URL", default="http://127.0.0.1:8050").rstrip("/")

AUTH_URL = env("BENEFITS_VIEWER_AUTH_URL", default=f"{SITE_URL}/o/authorize")
TOKEN_URL = env("BENEFITS_VIEWER_TOKEN_URL", default=f"{SITE_URL}/o/token/")
CLIENT_ID = env("BENEFITS_VIEWER_CLIENT_ID", "CLIENT_ID")
CLIENT_SECRET = env("BENEFITS_VIEWER_CLIENT_SECRET", "CLIENT_SECRET")

BENEFITS_PARTNERS_ENDPOINT = "/api/benefits/partners/"
BENEFITS_REDEMPTIONS_ENDPOINT = "/api/benefits/redemptions/"
BENEFITS_REDEMPTIONS_PARTNER_FILTER = env("BENEFITS_REDEMPTIONS_PARTNER_FILTER", default="partner_id")
