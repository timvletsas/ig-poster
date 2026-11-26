"""3D Poster Studio - cloud poster.
Runs on GitHub Actions. Publishes every post in queue.json whose time has come.
Supports IMAGE, CAROUSEL, REELS and STORIES.
"""
import os, re, sys, json, time, subprocess, datetime, urllib.parse
import requests

API = "https://graph.facebook.com/v24.0"
TOKEN = os.environ.get("IG_TOKEN", "")
IG_ID = os.environ.get("IG_USER_ID", "")
QUEUE = os.environ.get("QUEUE_FILE", "queue.json")   # other pages: queues/<page>.json
STATS = os.environ.get("STATS_FILE", "stats.json")
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
    start = time.time(); last = None
    while time.time() - start < timeout:
        st = requests.get(f"{API}/{cid}", params={"fields": "status_code,status", "access_token": TOKEN}, timeout=60).json()
        code = st.get("status_code")
        if st != last:
            log("  processing:", st); last = st
        if code == "FINISHED":
            return
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram could not process media: {st.get('status', code)}")
        time.sleep(6)
    raise RuntimeError(f"Timed out waiting for Instagram to process media (last status: {last})")


def video_container(path, extra, ready_timeout=None):
    """Upload a video directly (resumable). If that fails or stalls, use the public URL instead."""
    try:
        r = api_post(f"{IG_ID}/media", {**extra, "upload_type": "resumable"})
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            up = requests.post(r["uri"], data=f, timeout=900, headers={
                "Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(size)}).json()
        log("  upload:", up)
        if not up.get("success", True) and "id" not in up:
            raise RuntimeError(str(up))
        if ready_timeout:
            wait_ready(r["id"], ready_timeout)
        return r["id"]
    except Exception as e:
        log("Direct upload failed or stalled, trying public URL:", e)
        return api_post(f"{IG_ID}/media", {**extra, "video_url": raw_url(path)})["id"]


def is_video(p):
    return p.lower().endswith(VIDEO_EXT)


TZ_NAME = "Europe/Athens"


def local_now():
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo(TZ_NAME))
    except Exception:
        return datetime.datetime.now(datetime.timezone.utc)


def nominee_no():
    """Mon=1 ... Fri=5 (Greece time)."""
    return min(5, local_now().weekday() + 1)


def push_files(paths, msg):
    """Commit generated images and push them so Instagram can download them."""
    for attempt in range(4):
        for pth in paths:
            git("add", pth)
        git("commit", "-m", msg, check=False)
        if git("push", "origin", f"HEAD:{BRANCH}", check=False).returncode == 0:
            time.sleep(12)
            return
        git("pull", "--rebase", "origin", BRANCH, check=False)
    raise RuntimeError("could not push generated images")


def build_spot(post):
    """Nominee cover + artist slides + close-ups + 'vote on Saturday' end card."""
    import spot
    from PIL import Image
    imgs = [m for m in post["media"] if not is_video(m)]
    src = imgs[0] if imgs else art_src(post)   # video-only posts: use a frame from the first video
    if not src:
        return
    folder = os.path.dirname(src)
    with Image.open(src) as im:
        ratio = im.width / im.height
    num = nominee_no()
    sp = post.get("spotlight") or {}
    cover, end = os.path.join(folder, "s_cover.jpg"), os.path.join(folder, "s_end.jpg")
    spot.nominee_cover(src, cover, num, sp.get("title", ""), post.get("artist", ""))
    spot.nominee_end(src, end, num, post.get("artist", ""), ratio)
    free = 10 - len(post["media"]) - 2
    details = []
    if free > 0:
        for i, box in enumerate(spot.detail_boxes(src, min(2, free), ratio)):
            pth = os.path.join(folder, f"s_detail{i + 1}.jpg")
            spot.detail_slide(src, pth, box, i + 1, ratio)
            details.append(pth)
    push_files([cover, end, *details], f"spotlight slides for {post['id']}")
    post["media"] = [cover, *post["media"], *details, end]
    post["type"] = "CAROUSEL"


# ---------------- weekly cycle: Saturday vote, Sunday results ----------------
def week_key(dt=None):
    y, w, _ = (dt or local_now()).isocalendar()
    return f"{y}-W{w:02d}"


def at_or_after(hhmm):
    h, m = map(int, hhmm.split(":"))
    n = local_now()
    return (n.hour, n.minute) >= (h, m)


def week_nominees(q):
    """Spotlight posts published Mon-Fri of the current week (max 5, in order)."""
    now = local_now()
    monday = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for p in q["posts"]:
        if p.get("status") != "posted" or not (p.get("nominee") or p.get("spot")) or not p.get("posted_at") or not p.get("ig_media_id"):
            continue
        t = datetime.datetime.fromisoformat(p["posted_at"].replace("Z", "+00:00")).astimezone(now.tzinfo)
        if monday <= t and t.weekday() <= 4:
            out.append((t, p))
    out.sort(key=lambda x: x[0])
    return [p for _, p in out][:5]


def ffmpeg_bin():
    import shutil
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def art_src(p):
    """The artist's first image (skip our generated slides). Video-only posts: grab a frame."""
    for m in p.get("media", []):
        if not is_video(m) and "/s_" not in m and os.path.exists(m):
            return m
    for m in p.get("media", []):
        if is_video(m) and os.path.exists(m):
            frame = os.path.join(os.path.dirname(m), "s_frame.jpg")
            if not os.path.exists(frame):
                subprocess.run([ffmpeg_bin(), "-y", "-loglevel", "error", "-ss", "1", "-i", m, "-frames:v", "1", "-q:v", "2", frame], check=False)
            if os.path.exists(frame):
                return frame
    return None


def ig_handle(artist):
    a = (artist or "").strip().lstrip("@")
    return a if re.fullmatch(r"[A-Za-z0-9._]{1,30}", a) else ""


def publish_images(paths, caption, tags=None, collaborators=None):
    """Publish a carousel (or single image) from repo image paths. tags: list per slide of usernames."""
    kids = []
    for i, pth in enumerate(paths):
        data = {"image_url": raw_url(pth), "is_carousel_item": "true"}
        u = (tags or [None] * len(paths))[i]
        if u:
            spots = u if isinstance(u, list) else [(u, 0.5, 0.9)]
            data["user_tags"] = json.dumps([{"username": n, "x": round(x, 3), "y": round(y, 3)} for n, x, y in spots if n])
        try:
            k = api_post(f"{IG_ID}/media", data)["id"]
        except Exception:
            data.pop("user_tags", None)
            k = api_post(f"{IG_ID}/media", data)["id"]
        wait_ready(k); kids.append(k)
    base = {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption}
    if collaborators:
        try:
            cid = api_post(f"{IG_ID}/media", {**base, "collaborators": json.dumps(collaborators[:3])})["id"]
        except Exception as e:
            log("  collaborators refused, posting without:", e)
            cid = api_post(f"{IG_ID}/media", base)["id"]
    else:
        cid = api_post(f"{IG_ID}/media", base)["id"]
    wait_ready(cid)
    return api_post(f"{IG_ID}/media_publish", {"creation_id": cid})["id"]


def publish_story(path):
    cid = api_post(f"{IG_ID}/media", {"media_type": "STORIES", "image_url": raw_url(path)})["id"]
    wait_ready(cid)
    return api_post(f"{IG_ID}/media_publish", {"creation_id": cid})["id"]


def count_votes(media_id, n):
    votes, voters, url = [0] * n, set(), f"{API}/{media_id}/comments"
    params = {"fields": "text,username", "limit": 50, "access_token": TOKEN}
    for _ in range(40):
        r = requests.get(url, params=params, timeout=60).json()
        if "error" in r:
            log("  can't read comments (needs instagram_manage_comments):", r["error"].get("message"))
            return None
        for c in r.get("data", []):
            m = re.search(r"\b([1-9])\b", c.get("text", ""))
            who = c.get("username") or c.get("id")
            if m and 1 <= int(m.group(1)) <= n and who not in voters:
                voters.add(who); votes[int(m.group(1)) - 1] += 1
        url = (r.get("paging") or {}).get("next"); params = None
        if not url: break
    return votes


def engagement(media_id):
    r = requests.get(f"{API}/{media_id}", params={"fields": "like_count,comments_count", "access_token": TOKEN}, timeout=60).json()
    return (r.get("like_count") or 0) + 3 * (r.get("comments_count") or 0)


def run_cycle(q, cyc):
    """Saturday: vote post + story. Sunday: podium + winner stories. Returns changed cycle state or None."""
    import spot
    cfg = q.get("cycle_cfg") or {}
    if not cfg.get("enabled"):
        return None
    now, wk = local_now(), week_key()
    state = dict(cyc.get(wk) or {})
    folder = f"media/cycle/{wk}"
    os.makedirs(folder, exist_ok=True)
    # ---- Saturday vote
    if now.weekday() == 5 and at_or_after(cfg.get("sat", "12:00")) and not state.get("vote_id"):
        noms = [p for p in week_nominees(q) if art_src(p)]
        if len(noms) < 2:
            log("Cycle: not enough nominees this week for a vote:", len(noms)); state["vote_skipped"] = True
            return {wk: state}
        srcs = [art_src(p) for p in noms]; shorts = [spot.short(p.get("artist")) for p in noms]
        cover = f"{folder}/vote_cover.jpg"; spot.vote_cover(srcs, shorts, cover)
        slides = []
        for i, (sp_, p) in enumerate(zip(srcs, noms)):
            pth = f"{folder}/vote_{i + 1}.jpg"; spot.vote_slide(sp_, pth, i + 1, spot.credit(p.get("artist"))); slides.append(pth)
        story = f"{folder}/vote_story.jpg"; spot.vote_story(srcs, shorts, story)
        push_files([cover, *slides, story], f"vote {wk}")
        lines = "\n".join(f"{i + 1} - {spot.credit(p.get('artist'))}" for i, p in enumerate(noms))
        cap = (f"🗳 VOTE: Artwork of the Week\n\nComment the number of your favorite 👇\n\n{lines}\n\n"
               f"🏆 Winners revealed tomorrow!\n\n🎨 Are you a 3D artist and want to be featured? Send us a DM 📩\n\n#3droyals #3dart #3dartist #artoftheweek #3dcommunity")
        mid = publish_images([cover, *slides], cap, tags=[None] + [ig_handle(p.get("artist")) for p in noms])
        state.update({"vote_id": mid, "nominees": [{"id": p["id"], "artist": p.get("artist"), "src": art_src(p), "media_id": p.get("ig_media_id"), "title": (p.get("spotlight") or {}).get("title") or ""} for p in noms]})
        log("Cycle: vote posted", mid)
        try:
            state["vote_story"] = publish_story(story)
        except Exception as e:
            log("  vote story failed:", e)
        return {wk: state}
    # ---- Sunday results
    if now.weekday() == 6 and at_or_after(cfg.get("sun", "09:00")) and state.get("vote_id") and not state.get("results_id"):
        noms = state["nominees"]; n = len(noms)
        votes = count_votes(state["vote_id"], n)
        eng = [engagement(x["media_id"]) if x.get("media_id") else 0 for x in noms]
        use_votes = votes is not None and sum(votes) >= 5
        score = [(votes[i] if use_votes else 0) * 100000 + eng[i] for i in range(n)]
        order = sorted(range(n), key=lambda i: -score[i])[:3]
        win = [noms[i] for i in order]
        srcs = [w["src"] for w in win]; shorts = [spot.short(w["artist"]) for w in win]
        pod = f"{folder}/podium.jpg"; pod_tags = None
        if os.path.exists(spot.PODIUM_TPL):
            spots = spot.podium_tpl(srcs, [spot.credit(w["artist"]) for w in win], pod, f"Week {int(wk.split('W')[-1])}")
            pod_tags = [(ig_handle(w["artist"]), x, y) for w, (x, y) in zip(win, spots) if ig_handle(w["artist"])] or None
        else:
            spot.podium(srcs, shorts, pod)
        slides, stories = [], []
        if os.path.exists(spot.CERT_TPL):
            wl = f"WEEK {int(wk.split('W')[-1])} · {wk[:4]}"
            if os.path.exists(spot.LOGO_W):
                spot.watermark(pod)
            for k, w in enumerate(win):
                pth = f"{folder}/winner_{k + 1}.jpg"
                spot.certificate(w["src"], pth, spot.credit(w["artist"]), w.get("title", ""), k + 1, wl); slides.append(pth)
            ps = f"{folder}/podium_story.jpg"; spot.to_story(pod, ps); stories.append(ps)
            cs = f"{folder}/certificate_story.jpg"
            spot.certificate(win[0]["src"], cs, spot.credit(win[0]["artist"]), win[0].get("title", ""), 1, wl, story=True); stories.append(cs)
        else:
            for k, w in enumerate(win):
                pth = f"{folder}/winner_{k + 1}.jpg"; spot.winner_slide(w["src"], pth, k + 1, spot.credit(w["artist"])); slides.append(pth)
                st_ = f"{folder}/winner_story_{k + 1}.jpg"; spot.winner_story(w["src"], st_, k + 1, spot.credit(w["artist"])); stories.append(st_)
        push_files([pod, *slides, *stories], f"results {wk}")
        medal = ["🥇", "🥈", "🥉"]
        lines = "\n".join(f"{medal[k]} {spot.credit(w['artist'])}" + (f" ({votes[order[k]]} votes)" if use_votes else "") for k, w in enumerate(win))
        cap = (f"🏆 Artwork of the Week: RESULTS\n\n{lines}\n\nCongrats to the winners and thank you for voting! 👑\n"
               f"New nominees start Monday, vote again on Saturday 🗳\n\n🎨 Are you a 3D artist and want to be featured? Send us a DM 📩\n\n#3droyals #3dart #3dartist #artoftheweek #3dcommunity")
        collabs = list(dict.fromkeys(h for h in (ig_handle(w["artist"]) for w in win) if h))
        mid = publish_images([pod, *slides], cap, tags=[pod_tags] + [ig_handle(w["artist"]) for w in win], collaborators=collabs)
        state.update({"results_id": mid, "winners": [w["id"] for w in win], "votes": votes, "ranked_by": "votes" if use_votes else "engagement"})
        log("Cycle: results posted", mid)
        for k, st_ in enumerate(stories):
            try:
                publish_story(st_)
            except Exception as e:
                log(f"  winner story {k + 1} failed:", e)
        return {wk: state}
    return None


def handle(post):
    """Instagram username to tag/invite, or '' (names with spaces = ArtStation artists, not on Instagram)."""
    a = (post.get("artist") or "").strip().lstrip("@")
    if re.search(r"\b(on|in)\s+art\s?station\b", post.get("caption", ""), re.I):
        return ""  # credited as an ArtStation artist in the caption -> not on Instagram
    return a if re.fullmatch(r"[A-Za-z0-9._]{1,30}", a) and a.lower() != "artist" else ""


def week_no(queue_posts, extra_posted):
    """How many-th post of this week (Mon-Sun, Greece time) this one is."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Athens")
    except Exception:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz)
    monday = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    n = extra_posted
    for p in queue_posts:
        t = p.get("posted_at")
        if p.get("status") == "posted" and t and datetime.datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(tz) >= monday:
            n += 1
    return n + 1


def publish(post, with_tags=True):
    media = post["media"]
    caption = post.get("caption", "")
    t = post["type"]
    h = handle(post) if with_tags else ""
    tag_img = {"user_tags": json.dumps([{"username": h, "x": 0.5, "y": 0.92}])} if h and post.get("tag_artist") else {}
    tag_vid = {"user_tags": json.dumps([{"username": h}])} if h and post.get("tag_artist") else {}
    collab = {"collaborators": json.dumps([h])} if h and post.get("collab") else {}
    if t == "IMAGE":
        cid = api_post(f"{IG_ID}/media", {"image_url": raw_url(media[0]), "caption": caption, **tag_img, **collab})["id"]
    elif t == "REELS":
        cid = video_container(media[0], {"media_type": "REELS", "caption": caption, "share_to_feed": "true", **tag_vid, **collab}, ready_timeout=300)
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
                k = api_post(f"{IG_ID}/media", {"image_url": raw_url(m), "is_carousel_item": "true", **tag_img})["id"]
            wait_ready(k)
            kids.append(k)
        cid = api_post(f"{IG_ID}/media", {"media_type": "CAROUSEL", "children": ",".join(kids), "caption": caption, **collab})["id"]
    else:
        raise RuntimeError(f"Unknown post type {t}")
    wait_ready(cid)
    mid = api_post(f"{IG_ID}/media_publish", {"creation_id": cid})["id"]
    link = requests.get(f"{API}/{mid}", params={"fields": "permalink", "access_token": TOKEN}, timeout=60).json().get("permalink")
    return mid, link


def snapshot():
    """Once per day: save account stats so the app can track growth / followers lost."""
    today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    try:
        stats = json.load(open(STATS, encoding="utf-8"))
    except Exception:
        stats = {"daily": [], "online": {}}
    if any(d.get("date") == today for d in stats["daily"]):
        return None
    g = lambda path, **p: requests.get(f"{API}/{path}", params={**p, "access_token": TOKEN}, timeout=60).json()
    prof = g(IG_ID, fields="followers_count,follows_count,media_count")
    if "error" in prof:
        log("Stats snapshot failed:", prof["error"].get("message"))
        return None
    day = {"date": today, "followers": prof.get("followers_count"), "follows": prof.get("follows_count"), "media": prof.get("media_count")}
    ins = g(f"{IG_ID}/insights", metric="reach,total_interactions,accounts_engaged,views", period="day", metric_type="total_value")
    for m in ins.get("data", []):
        day[m["name"]] = (m.get("total_value") or {}).get("value")
    of = g(f"{IG_ID}/insights", metric="online_followers", period="lifetime")
    for m in of.get("data", []):
        for v in m.get("values", []):
            if isinstance(v.get("value"), dict) and v["value"]:
                stats.setdefault("online", {})[v["end_time"][:10]] = v["value"]
    stats["daily"].append(day)
    stats["daily"] = stats["daily"][-800:]
    log("Stats snapshot:", day)
    return stats


def save(results, stats, cycle=None):
    """Write changes into the latest repo state and push (retries on conflicts)."""
    for attempt in range(5):
        git("fetch", "origin", BRANCH)
        git("reset", "--hard", f"origin/{BRANCH}")
        if results or cycle:
            q = json.load(open(QUEUE, encoding="utf-8"))
            if cycle:
                q.setdefault("cycle", {}).update(cycle)
            for p in q["posts"]:
                if p["id"] in results:
                    p.update(results[p["id"]])
            json.dump(q, open(QUEUE, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
            git("add", QUEUE)
        if stats:
            os.makedirs(os.path.dirname(STATS) or ".", exist_ok=True)
            json.dump(stats, open(STATS, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            git("add", STATS)
        if git("commit", "-m", "bot: update status/stats", check=False).returncode != 0:
            return
        if git("push", "origin", f"HEAD:{BRANCH}", check=False).returncode == 0:
            log("Saved.")
            return
        time.sleep(3)
    log("WARNING: could not save after retries")


def main():
    if not TOKEN or not IG_ID:
        log("ERROR: IG_TOKEN / IG_USER_ID secrets missing. Open the app -> Settings -> Sync to cloud.")
        sys.exit(1)
    stats = None
    try:
        stats = snapshot()
    except Exception as e:
        log("Stats snapshot error:", e)
    q = json.load(open(QUEUE, encoding="utf-8"))
    now = datetime.datetime.now(datetime.timezone.utc)
    due = [p for p in q["posts"] if p.get("status") == "scheduled"
           and datetime.datetime.fromisoformat(p["scheduled_at"].replace("Z", "+00:00")) <= now]
    due.sort(key=lambda p: p["scheduled_at"])
    results = {}
    for p in due[:MAX_PER_RUN]:
        log(f"Publishing {p['id']} ({p['type']})")
        num = week_no(q["posts"], sum(1 for r in results.values() if r["status"] == "posted"))
        if "{week_no}" in p.get("caption", ""):
            p["caption"] = p["caption"].replace("{week_no}", str(num))
        if "{nominee_no}" in p.get("caption", ""):
            p["caption"] = p["caption"].replace("{nominee_no}", str(nominee_no()))
        if p.get("spot") and p["type"] in ("IMAGE", "CAROUSEL"):
            try:
                build_spot(p)
            except Exception as e:
                log("  spotlight slides failed, posting the artwork only:", e)
        stamp = now.isoformat().replace("+00:00", "Z")
        try:
            try:
                mid, link = publish(p)
            except Exception as e:
                if handle(p) and (p.get("tag_artist") or p.get("collab")):
                    log("  failed with artist tag, retrying without:", e)
                    mid, link = publish(p, with_tags=False)
                else:
                    raise
            results[p["id"]] = {"status": "posted", "posted_at": stamp, "ig_media_id": mid, "permalink": link, "error": None, "caption": p.get("caption", ""), "media": p.get("media"), "type": p.get("type")}
            log("  posted:", link)
        except Exception as e:
            results[p["id"]] = {"status": "failed", "error": str(e), "failed_at": stamp}
            log("  FAILED:", e)
    if not due:
        log("Nothing due.")
    cyc_update = None
    try:
        q2 = json.load(open(QUEUE, encoding="utf-8"))
        for p in q2["posts"]:
            if p["id"] in results: p.update(results[p["id"]])
        cyc_update = run_cycle(q2, q2.get("cycle") or {})
    except Exception as e:
        log("Cycle error:", e)
    save(results, stats, cyc_update)
    if any(r["status"] == "failed" for r in results.values()):
        sys.exit(1)


if __name__ == "__main__":
    main()
