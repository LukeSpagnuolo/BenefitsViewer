# BenefitsViewer

Dash app for viewing benefits data from the CSIPacific API.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set the real OAuth values in `.env`, then export them before running:

```bash
set -a
source .env
set +a
python app.py
```

The local app defaults to `http://127.0.0.1:8050`.

## Posit Connect

This repo is ready for Posit Connect as a Dash app.

Required environment variables in Posit Connect:

```text
BENEFITS_VIEWER_CLIENT_ID
BENEFITS_VIEWER_CLIENT_SECRET
BENEFITS_VIEWER_APP_URL
```

If the first publish opens with a missing configuration message, add those
environment variables in the Posit Connect content settings and republish or
restart the app. `BENEFITS_VIEWER_APP_URL` should be the public URL for this
deployed Posit content.

Optional environment variables:

```text
BENEFITS_VIEWER_SITE=https://apps.csipacific.ca
BENEFITS_VIEWER_AUTH_URL=https://apps.csipacific.ca/o/authorize
BENEFITS_VIEWER_TOKEN_URL=https://apps.csipacific.ca/o/token/
BENEFITS_VIEWER_BENEFITS_URL=https://apps.csipacific.ca/api/benefits/partners/
```

Deploy with `rsconnect-python`:

```bash
rsconnect deploy dash \
  -n <saved-server-name> \
  --entrypoint app:app \
  .
```

After the first publish, set `BENEFITS_VIEWER_APP_URL` to the public Posit
Connect content URL and make sure the OAuth client redirect/callback URL uses
that same deployed URL.
