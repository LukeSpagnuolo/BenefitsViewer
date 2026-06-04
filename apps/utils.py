import requests
from settings import SITE_URL

def fetch_options(path, token, label_key, value_key, params=None, limit=1000):
    headers = {"Authorization": f"Bearer {token}"}

    if params and isinstance(params,dict):
        params.update({"limit": limit})
    else:
        params = {"limit": limit}

    resp = requests.get(f"{SITE_URL}{path}", params=params, headers=headers, timeout=5)
    resp.raise_for_status()

    items = resp.json()

    if 'results' in items:
        rv = [
            {"label": item.get(label_key), "value": item.get(value_key)}
            for item in items["results"]
            if item.get(value_key) is not None
        ]
    elif isinstance(items, list):
        rv = [{"label": val, "value": val} for val in items if val]
    else:
        rv = []

    rv = [{"label": o["label"], "value": str(o["value"])} for o in (rv or [])]

    return rv

def filters_to_params(raw: dict) -> dict:
    out = {}
    for k, v in (raw or {}).items():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        if isinstance(v, (list, tuple)):
            v = [x for x in v if x not in (None, "", [])]
            if not v:
                continue
            out[k] = ",".join(str(x) for x in v)
            continue
        out[k] = v
    return out