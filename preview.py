"""Render the real 'Artwork of the Week' slides for every scheduled post into previews/,
so the app can show exactly how each post will look. Runs when the queue changes."""
import os, json, copy, shutil, hashlib, datetime, time
os.environ.setdefault("GITHUB_REPOSITORY", "timvletsas/ig-poster")
import post
from zoneinfo import ZoneInfo

TZ = ZoneInfo(post.TZ_NAME if hasattr(post, "TZ_NAME") else "Europe/Athens")
IDX = "previews/index.json"
post.push_files = lambda paths, msg: None

q = json.load(open("queue.json", encoding="utf-8"))
idx = json.load(open(IDX, encoding="utf-8")) if os.path.exists(IDX) else {}
sched = {p["id"]: p for p in q["posts"] if p.get("status") == "scheduled"}
changed = False
ENGINE = hashlib.sha1(open("spot.py", "rb").read() + open("post.py", "rb").read()).hexdigest()[:12]

for pid in list(idx):
    if pid not in sched:
        shutil.rmtree(f"previews/{pid}", ignore_errors=True); del idx[pid]; changed = True

for pid, p in sched.items():
    t = datetime.datetime.fromisoformat(p["scheduled_at"].replace("Z", "+00:00")).astimezone(TZ)
    num = min(5, t.weekday() + 1)
    sig = hashlib.sha1(json.dumps([p["media"], p.get("spotlight"), p.get("artist"), p.get("caption"),
                                   num, p.get("spot"), p["type"], ENGINE], ensure_ascii=False).encode()).hexdigest()
    old = idx.get(pid)
    if old and old.get("sig") == sig and all(os.path.exists(m) for m in old["media"]):
        continue
    pp = copy.deepcopy(p)
    post.nominee_no = lambda n=num: n
    if pp.get("spot") and pp["type"] in ("IMAGE", "CAROUSEL"):
        try:
            post.build_spot(pp)
        except Exception as e:
            print("preview failed for", pid, e)
    d = f"previews/{pid}"
    shutil.rmtree(d, ignore_errors=True); os.makedirs(d, exist_ok=True)
    out = []
    for i, m in enumerate(pp["media"]):
        if "/s_" in m:
            dst = f"{d}/{i:02d}_{os.path.basename(m)}"; shutil.move(m, dst); out.append(dst)
        else:
            out.append(m)
    idx[pid] = {"sig": sig, "src": p["media"], "media": out, "type": pp["type"],
                "caption": pp.get("caption", "").replace("{nominee_no}", str(num))}
    changed = True
    print("rendered", pid, len(out), "slides")

if changed:
    os.makedirs("previews", exist_ok=True)
    json.dump(idx, open(IDX, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for attempt in range(5):
        post.git("add", "-A", "previews")
        post.git("commit", "-m", "Update post previews", check=False)
        if post.git("push", "origin", "HEAD:main", check=False).returncode == 0:
            print("previews pushed"); break
        post.git("pull", "--rebase", "origin", "main", check=False); time.sleep(3)
else:
    print("previews up to date")
