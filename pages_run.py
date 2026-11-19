"""Run the poster for every extra page in pages.json (the main page runs from post.py directly)."""
import json, os, subprocess, sys
try:
    pages = json.load(open("pages.json", encoding="utf-8")).get("pages", [])
except FileNotFoundError:
    pages = []
bad = 0
for pg in pages:
    if not pg.get("ig_user_id") or not os.path.exists(pg["queue"]):
        continue
    print(f"===== page {pg['key']} =====", flush=True)
    env = {**os.environ, "IG_USER_ID": pg["ig_user_id"], "QUEUE_FILE": pg["queue"], "STATS_FILE": pg["stats"]}
    if subprocess.run([sys.executable, "post.py"], env=env).returncode != 0:
        bad += 1
sys.exit(1 if bad else 0)
