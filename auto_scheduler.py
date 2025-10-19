# auto_scheduler.py
import time
from app import poll_and_append_job, posting_job, start_scheduler

print("🚀 SlickOfficials Scheduler started — hands-free mode activated")

# Start the same BackgroundScheduler (so we keep the same timing)
start_scheduler()

# Keep the worker alive forever (Render restarts it if it crashes)
while True:
    time.sleep(3600)
