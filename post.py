"""3D Poster Studio - cloud poster.
Runs on GitHub Actions. Publishes every post in queue.json whose time has come.
Supports IMAGE, CAROUSEL, REELS and STORIES.
"""
import os, sys, json, time, subprocess, datetime, urllib.parse
import requests

API = "https://graph.facebook.com/v24.0"
TOKEN = os.environ.get("IG_TOKEN", "")
IG_ID = os.environ.get("IG_USER_ID", "")
REPO = os.environ["GITHUB_REPOSITORY"]
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
MAX_PER_RUN = 3
VIDEO_EXT = (".mp4", ".mov")


def log(*a):
    print(*a, flush=True)


def git(*args, check=True):
    return subprocess.run(["git", *args], check=check, capture_output=True, text=True)


def raw_url(path):
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/" + urllib.parse.quote(path)


def api_post(path, data):
    data = {**data, "access_token": TOKEN}
    r = requests.post(f"{API}/{path}", data=data, timeout=120).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message", str(r["error"])))
    return r


def wait_ready(cid, timeout=600):
    start = time.time()
    while time.time() - start < timeout:
        st = requests.get(f"{API}/{cid}", params={"fields": "status_code,status", "access_token": TOKEN}, timeout=60).json()
        code = st.get("status_code")
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process media: {st.get('status', code)}")
        time.sleep(6)
    raise RuntimeError("Timed out waiting for Instagram to process media")


def video_container(path, extra):
    """Upload a video directly (resumable); fall back to public URL."""
    try:
        r = api_post(f"{IG_ID}/media", {**extra, "upload_type": "resumable"})
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            up = requests.post(r["uri"], data=f, timeout=900, headers={
                "Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(size)}).json()
        if not up.get("success", True) and "id" not in up:
            raise RuntimeError(str(up))
        return r["id"]
    except Exception as e:
        log("Resumable upload failed, trying URL:", e)
        return api_post(f"{IG_ID}/media", {**extra, "video_url": raw_url(path)})["id"]


def is_video(p):
    return p.lower().endswith(VIDEO_EXT)


def publish(post):
    media = post["media"]
    caption = post.get("caption", "")
    t = post["type"]
    if t == "IMAGE":
        cid = api_post(f"{IG_ID}/media", {"image_url": raw_url(media[0]), "caption": caption})["id"]
    elif t == "REELS":
        cid = video_container(media[0], {"media_type": "REELS", "caption": caption, "share_to_feed": "true"})
    elif t == "STORIES":
        if is_video(media[0]):
            cid = video_container(media[0], {"media_type": "STORIES"})
        else:
            cid = api_post(f"{IG_ID}/media", {"media_type": "STORIES", "image_url": raw_url(media[0])})["id"]
    elif t == "CAROUSEL":
        kids = []
        for m in media[:10]:
            if is_video(m):
                k = video_container(m, {"media_type": "VIDEO", "is_carousel_item": "true"})
            else:
                k = api_post(f"{IG_ID}/media", {"image_url": raw_url(m), "is_carousel_item": "true"})["id"]
            wait_ready(k)
            kids.append(k)
        cid = api_post(f"{IG_ID}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption})["id"]
    else:
        raise RuntimeError(f"Unknown post type {t}")
    wait_ready(cid)
    mid = api_post(f"{IG_ID}/media_publish", {"creation_id": cid})["id"]
    link = requests.get(f"{API}/{mid}", params={"fields": "permalink", "access_token": TOKEN}, timeout=60).json().get("permalink")
    return mid, link


def save_results(results):
    """Write status changes into the latest queue.json and push (retries on conflicts)."""
    for attempt in range(5):
        git("fetch", "origin", BRANCH)
        git("reset", "--hard", f"origin/{BRANCH}")
        q = json.load(open("queue.json", encoding="utf-8"))
        for p in q["posts"]:
            if p["id"] in results:
                p.update(results[p["id"]])
        json.dump(q, open("queue.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        git("add", "queue.json")
        if git("commit", "-m", "bot: update post status", check=False).returncode != 0:
            return
        if git("push", "origin", f"HEAD:{BRANCH}", check=False).returncode == 0:
            log("Saved status.")
            return
        time.sleep(3)
    log("WARNING: could not save status after retries")


def main():
    if not TOKEN or not IG_ID:
        log("ERROR: IG_TOKEN / IG_USER_ID secrets missing. Open the app -> Settings -> Sync to cloud.")
        sys.exit(1)
    q = json.load(open("queue.json", encoding="utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc)
    due = [p for p in q["posts"] if p.get("status") == "scheduled"
           and datetime.datetime.fromisoformat(p["scheduled_at"].replace("Z", "+00:00")) <= now]
    due.sort(key=lambda p: p["scheduled_at"])
    if not due:
        log("Nothing due.")
        return
    results = {}
    for p in due[:MAX_PER_RUN]:
        log(f"Publishing {p['id']} ({p['type']})")
        stamp = now.isoformat().replace("+00:00", "Z")
        try:
            mid, link = publish(p)
            results[p["id"]] = {"status": "posted", "posted_at": stamp, "ig_media_id": mid, "permalink": link, "error": None}
            log("  posted:", link)
        except Exception as e:
            results[p["id"]] = {"status": "failed", "error": str(e), "failed_at": stamp}
            log("  FAILED:", e)
    save_results(results)
    if any(r["status"] == "failed" for r in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
