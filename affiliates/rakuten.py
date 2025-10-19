import requests
import os
from datetime import datetime, timedelta

RAKUTEN_API_URL = "https://api.rakutenmarketing.com/events/1.0/transactions"
RAKUTEN_API_TOKEN = os.getenv("RAKUTEN_API_TOKEN")

def poll_rakuten_approvals(_=None):
    if not RAKUTEN_API_TOKEN:
        print("[poll_rakuten] missing credentials")
        return []

    since = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
    headers = {"Authorization": f"Bearer {RAKUTEN_API_TOKEN}"}
    params = {
        "start_date": since,
        "end_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "status": "approved",
    }

    print("[poll_rakuten] checking approvals since", since)
    resp = requests.get(RAKUTEN_API_URL, headers=headers, params=params)
    if resp.status_code != 200:
        print("[poll_rakuten] API error:", resp.status_code, resp.text)
        return []

    return resp.json()
