import requests
import os
from datetime import datetime, timedelta
import random
import pandas as pd

def post_content(posts, templates):
    if not posts:
        print("No more posts! Generating from templates...")
        fallback_products = [
            {"name": "Kila Custom Insoles", "url": "https://tidd.ly/3J1KeV2", "category": "insoles"},
            {"name": "Kapitalwise", "url": "https://tidd.ly/43ibfu7", "category": "finance"},
            {"name": "Diamond Smile FR", "url": "https://tidd.ly/4nanmAp", "category": "dental"},
            {"name": "Bell’s Reines", "url": "https://tidd.ly/3Jb6cEV", "category": "food"},
            {"name": "Awin USD", "url": "https://tidd.ly/46RRifY", "category": "affiliate"},
            {"name": "AliExpress", "url": "https://tidd.ly/3Jbg6GA", "category": "ecommerce"},
            {"name": "Neck Hammock", "url": "https://tidd.ly/4qyhB2L", "category": "wellness"},
            {"name": "Slimea", "url": "https://tidd.ly/3WbtvBv", "category": "weightloss"},
            {"name": "Timeshop24 DE", "url": "https://tidd.ly/4nWuz8s", "category": "watches"},
            {"name": "Bonne et Filou", "url": "https://tidd.ly/4hgNp7H", "category": "pet"},
            {"name": "Wondershare", "url": "https://click.linksynergy.com/deeplink?id=iejQuC2lIug&mid=37160&murl=https%3A%2F%2Fwww.wondershare.com%2F", "category": "software"}
        ]
        product = random.choice(fallback_products)
        matches = [t for t in templates if t.get("product_type") == product["category"]]
        template = random.choice(matches) if matches else random.choice(templates) if templates else {"template":"Check [Product] [Link]"}
        link = product["url"]
        post_text = template.get("template","").replace("[Product]", product["name"]).replace("[Link]", link)
        posts.append({
            "post_text": post_text,
            "platform": "instagram,facebook,twitter,tiktok",
            "link": link,
            "image_url": f"https://i.imgur.com/{product['category']}{random.randint(1, 10)}.jpg"
        })
        pd.DataFrame(posts).to_csv("data/posts.csv", index=False)

    batch_size = min(10, len(posts))
    batch_posts = posts[:batch_size]
    posts[:] = posts[batch_size:]

    endpoint = "https://app.publer.com/api/v1/posts/schedule"
    headers = {
        "Authorization": f"Bearer {os.getenv('PUBLER_API_KEY')}",
        "Publer-Workspace-Id": os.getenv("PUBLER_WORKSPACE_ID"),
        "Content-Type": "application/json"
    }
    payload = {
        "bulk": {
            "state": "scheduled",
            "posts": []
        }
    }

    for post in batch_posts:
        text = post.get("post_text","")
        platforms = [p.strip() for p in post.get("platform","").split(",") if p.strip()]
        image_url = post.get("image_url") or os.getenv("DEFAULT_IMAGE_URL")
        accounts = []
        for p in platforms:
            env_key = f"{p.upper()}_ACCOUNT_ID"
            acct_id = os.getenv(env_key)
            if acct_id:
                accounts.append({"id": acct_id})
        if not accounts:
            # If no accounts configured, skip scheduling this batch
            print("No social accounts configured in env vars (INSTAGRAM_ACCOUNT_ID, etc.). Skipping batch.")
            return

        post_data = {
            "networks": {
                "default": {
                    "type": "status",
                    "text": text
                }
            },
            "accounts": accounts,
            "scheduled_at": (datetime.utcnow() + timedelta(minutes=random.randint(1, 60))).isoformat() + "Z"
        }
        if image_url:
            post_data["networks"]["default"]["media"] = [{"id": image_url, "type": "image"}]
        payload["bulk"]["posts"].append(post_data)

    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=15)
        print(f"Publer batch ({batch_size} posts) status: {response.status_code} | Response: {response.text if response is not None else ''}")
    except Exception as e:
        print(f"Publer request failed: {e}")
    pd.DataFrame(posts).to_csv("data/posts.csv", index=False)
