import requests
import os
from datetime import datetime, timedelta

AWIN_API_URL = "https://api.awin.com/publishers/{publisher_id}/transactions"
AWIN_API_TOKEN = os.getenv("AWIN_API_TOKEN")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")

def poll_awin_approvals(_=None):
    if not (AWIN_API_TOKEN and AWIN_PUBLISHER_ID):
        print("[poll_awin] missing credentials")
        return []

    since = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
    url = AWIN_API_URL.format(publisher_id=AWIN_PUBLISHER_ID)
    params = {
        "startDate": since,
        "endDate": datetime.utcnow().strftime("%Y-%m-%d"),
        "status": "approved",
    }
    headers = {"Authorization": f"Bearer {AWIN_API_TOKEN}"}

    print("[poll_awin] checking approvals since", since)
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code != 200:
        print("[poll_awin] API error:", resp.status_code, resp.text)
        return []

    return resp.json()
