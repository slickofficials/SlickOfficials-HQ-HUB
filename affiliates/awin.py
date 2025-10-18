import requests
import os
from datetime import datetime, timedelta
import random

def generate_awin_link(programme_id, destination_url):
    endpoint = f"https://api.awin.com/publishers/{os.getenv('AWIN_PUBLISHER_ID')}/cread/links"
    headers = {"Authorization": f"Bearer {os.getenv('AWIN_API_TOKEN')}"}
    payload = {
        "campaign": "globalbot",
        "destination": destination_url,
        "programmeId": programme_id
    }
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json().get("link")
        print(f"Awin link error: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Awin generate link exception: {e}")
    return None

def poll_awin_approvals(templates):
    endpoint = f"https://api.awin.com/publishers/{os.getenv('AWIN_PUBLISHER_ID')}/programmes"
    headers = {"Authorization": f"Bearer {os.getenv('AWIN_API_TOKEN')}"}
    params = {
        "relationship": "joined",
        "startDate": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "endDate": datetime.now().strftime("%Y-%m-%d")
    }
    new_posts = []
    try:
        response = requests.get(endpoint, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            new_approvals = response.json()
            for approval in new_approvals:
                link = generate_awin_link(approval.get("programmeId"), approval.get("clickThroughUrl"))
                if link:
                    matches = [t for t in templates if t.get("product_type") == approval.get("category", "wellness")]
                    template = random.choice(matches) if matches else random.choice(templates) if templates else {"template":"Check [Product] [Link]"}
                    post_text = template.get("template", "").replace("[Product]", approval.get("programmeName","Product")).replace("[Link]", link)
                    new_post = {
                        "post_text": post_text,
                        "platform": "instagram,facebook,twitter,tiktok",
                        "link": link,
                        "image_url": f"https://i.imgur.com/{approval.get('category','wellness')}{random.randint(1,10)}.jpg"
                    }
                    new_posts.append(new_post)
                    print(f"Awin new approval: {approval.get('programmeName')} | Link: {link}")
    except Exception as e:
        print(f"Awin poll exception: {e}")
    return new_posts
