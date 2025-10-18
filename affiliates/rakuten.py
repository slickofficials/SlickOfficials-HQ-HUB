import requests
import os
from datetime import datetime, timedelta
import random

def generate_rakuten_link(advertiser_id, destination_url):
    endpoint = "https://api.rakutenmarketing.com/linklocator/1.0/getTrackingLink"
    params = {
        "wsToken": os.getenv("RAKUTEN_WEBSERVICES_TOKEN"),
        "securityToken": os.getenv("RAKUTEN_SECURITY_TOKEN", ""),
        "scopeId": os.getenv("RAKUTEN_SCOPE_ID"),
        "advertiserId": advertiser_id,
        "url": destination_url,
        "u1": "globalbot"
    }
    try:
        response = requests.get(endpoint, params=params, timeout=10)
        if response.status_code == 200:
            return response.json().get("trackingLink")
        print(f"Rakuten link error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Rakuten generate link exception: {e}")
    return None

def poll_rakuten_approvals(templates):
    endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
    params = {
        "wsToken": os.getenv("RAKUTEN_WEBSERVICES_TOKEN"),
        "securityToken": os.getenv("RAKUTEN_SECURITY_TOKEN", ""),
        "scopeId": os.getenv("RAKUTEN_SCOPE_ID"),
        "approvalStatus": "accepted",
        "startDate": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    }
    new_posts = []
    try:
        response = requests.get(endpoint, params=params, timeout=10)
        if response.status_code == 200:
            new_approvals = response.json().get("advertisers", [])
            for approval in new_approvals:
                link = generate_rakuten_link(approval.get("advertiserId"), approval.get("siteUrl"))
                if link:
                    matches = [t for t in templates if t.get("product_type") == approval.get("category", "wellness")]
                    template = random.choice(matches) if matches else random.choice(templates) if templates else {"template":"Check [Product] [Link]"}
                    post_text = template.get("template","").replace("[Product]", approval.get("advertiserName","Product")).replace("[Link]", link)
                    new_post = {
                        "post_text": post_text,
                        "platform": "instagram,facebook,twitter,tiktok",
                        "link": link,
                        "image_url": f"https://i.imgur.com/{approval.get('category','wellness')}{random.randint(1,10)}.jpg"
                    }
                    new_posts.append(new_post)
                    print(f"Rakuten new approval: {approval.get('advertiserName')} | Link: {link}")
    except Exception as e:
        print(f"Rakuten poll exception: {e}")
    return new_posts
