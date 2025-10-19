# affiliates/awin.py
import os
import requests
import random
from datetime import datetime, timedelta

AWIN_API_TOKEN = os.getenv("AWIN_API_TOKEN")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")

def generate_awin_link(programme_id, destination_url):
    """
    Create an Awin deep link (cread). Returns the tracking URL or None.
    """
    try:
        endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/cread/links"
        headers = {"Authorization": f"Bearer {AWIN_API_TOKEN}"}
        payload = {
            "campaign": "slickofficials",
            "destination": destination_url,
            "programmeId": programme_id
        }
        r = requests.post(endpoint, json=payload, headers=headers, timeout=15)
        if r.status_code in (200, 201):
            data = r.json()
            return data.get("link") or data.get("trackingUrl") or data.get("tracking_link")
        else:
            print(f"[Awin] generate_awin_link failed {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Awin] generate_awin_link exception: {e}")
    return None

def poll_awin_approvals():
    """
    Poll Awin for recently joined programmes or approvals.
    Returns list of dicts: {"post_text","link","image_url","category","source","name"}
    """
    results = []
    if not AWIN_API_TOKEN or not AWIN_PUBLISHER_ID:
        print("[Awin] Missing AWIN_API_TOKEN or AWIN_PUBLISHER_ID")
        return results

    try:
        endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes"
        headers = {"Authorization": f"Bearer {AWIN_API_TOKEN}"}
        params = {"relationship": "joined", "startDate": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")}
        r = requests.get(endpoint, headers=headers, params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            programmes = data if isinstance(data, list) else data.get("programmes", data)
            for prog in programmes:
                programmeId = prog.get("programmeId") or prog.get("id")
                name = prog.get("programmeName") or prog.get("name") or "Partner"
                dest = prog.get("clickThroughUrl") or prog.get("website") or prog.get("siteUrl") or prog.get("domain")
                link = generate_awin_link(programmeId, dest) if programmeId and dest else dest
                results.append({
                    "post_text": f"Check out {name} — great deals waiting! [Link]",
                    "link": link or dest,
                    "image_url": f"https://i.imgur.com/affiliate{random.randint(1,10)}.jpg",
                    "category": prog.get("category", "affiliate"),
                    "source": "awin",
                    "name": name
                })
        else:
            print(f"[Awin] poll failed {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Awin] poll exception: {e}")
    return results
