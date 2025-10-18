# SlickOfficials Auto HQ - Deployable Project

## Setup
1. Add your environment variables in Render (or .env locally):
   - AWIN_API_TOKEN, AWIN_PUBLISHER_ID
   - RAKUTEN_WEBSERVICES_TOKEN, RAKUTEN_SECURITY_TOKEN, RAKUTEN_SCOPE_ID
   - PUBLER_API_KEY, PUBLER_WORKSPACE_ID
   - INSTAGRAM_ACCOUNT_ID, FACEBOOK_ACCOUNT_ID, TWITTER_ACCOUNT_ID, TIKTOK_ACCOUNT_ID
   - DEFAULT_IMAGE_URL (optional)
   - MANUAL_RUN_TOKEN (a secure secret)

2. Deploy to Render (or run locally).

## How it works
- This version is cron-friendly: no infinite background loop.
- Use the `/run/<token>` endpoint to trigger affiliate approval checks.
- Use the `/post/<token>` endpoint to schedule a batch of posts to Publer.
