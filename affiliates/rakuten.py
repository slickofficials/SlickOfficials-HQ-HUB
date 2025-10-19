# affiliates/rakuten.py
import os
import requests
import random
from datetime import datetime, timedelta

RAKUTEN_WS_TOKEN = os.getenv("RAKUTEN_WEBSERVICES_TOKEN")
RAKUTEN_SECURITY_TOKEN = os.getenv("RAKUTEN_SECURITY_TOKEN", "")
RAKUTEN_SCOPE_ID = os.getenv("RAKUTEN_SCOPE_ID")

def generate_rakuten_link(advertiser_id, destination_url):
    """
    Uses Rakuten LinkLocator to create a tracking link.
    """
    try:
        endpoint = "https://api.rakutenmarketing.com/linklocator/1.0/getTrackingLink"
        params = {
            "wsToken": RAKUTEN_WS_TOKEN,
            "securityToken": RAKUTEN_SECURITY_TOKEN,
            "scopeId": RAKUTEN_SCOPE_ID,
            "advertiserId": advertiser_id,
            "url": destination_url,
            "u1": "slickofficials"
        }
        r = requests.get(endpoint, params=params, timeout=15)
        if r.status_code == 200:
            data = r.json()
            return data.get("trackingLink") or data.get("url")
        else:
            print(f"[Rakuten] generate link failed {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Rakuten] generate exception: {e}")
    return None

def poll_rakuten_approvals():
    """
    Poll Rakuten for accepted advertisers or approvals within last 7 days.
    Returns list of dicts similar to Awin poll.
    """
    results = []
    if not RAKUTEN_WS_TOKEN:
        print("[Rakuten] Missing RAKUTEN_WEBSERVICES_TOKEN")
        return results

    try:
        endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
        params = {
            "wsToken": RAKUTEN_WS_TOKEN,
            "securityToken": RAKUTEN_SECURITY_TOKEN,
            "scopeId": RAKUTEN_SCOPE_ID,
            "approvalStatus": "accepted",
            "startDate": (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
        }
        r = requests.get(endpoint, params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            advertisers = data.get("advertisers", [])
            for adv in advertisers:
                adv_id = adv.get("advertiserId") or adv.get("id")
                name = adv.get("advertiserName") or adv.get("name")
                site = adv.get("siteUrl") or adv.get("domain")
                link = generate_rakuten_link(adv_id, site) if adv_id and site else site
                results.append({
                    "post_text": f"Grab a deal from {name} — don't miss out! [Link]",
                    "link": link or site,
                    "image_url": f"https://i.imgur.com/affiliate{random.randint(1,10)}.jpg",
                    "category": adv.get("category", "affiliate"),
                    "source": "rakuten",
                    "name": name
                })
        else:
            print(f"[Rakuten] poll failed {r.status_code}: {r.text}")
    except Exception as e:
        print(f"[Rakuten] poll exception: {e}")
    return results
