"""3D Royals visuals: weekly nominee posts, Saturday vote, Sunday podium (rendered by the cloud bot)."""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
FB = os.path.join(HERE, "fonts", "Poppins-Bold.ttf")
FM = os.path.join(HERE, "fonts", "Poppins-Medium.ttf")
PURPLE, CYAN = (124, 58, 237), (34, 211, 238)
GOLD, SILVER, BRONZE = (245, 196, 66), (200, 205, 214), (205, 127, 70)
WHITE, LILAC, DARK = (255, 255, 255), (196, 181, 253), (11, 13, 20)
BRAND = "@3droyals"


def fb(px, s=1.0): return ImageFont.truetype(FB, max(8, int(px * s)))
def fm(px, s=1.0): return ImageFont.truetype(FM, max(8, int(px * s)))


def grad(w, h, a=PURPLE, b=CYAN):
    row = Image.new("RGB", (max(1, w), 1))
    for x in range(max(1, w)):
        t = x / max(1, w - 1)
        row.putpixel((x, 0), tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3)))
    return row.resize((max(1, w), max(1, h)))


def vshade(img, y0, y1, a0, a1):
    W, H = img.size
    m = Image.new("L", (1, max(1, y1 - y0)))
    for y in range(m.size[1]):
        m.putpixel((0, y), int(255 * (a0 + (a1 - a0) * y / max(1, m.size[1] - 1))))
    full = Image.new("L", (W, H), 0)
    full.paste(m.resize((W, m.size[1])), (0, y0))
    return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), img, full)


def grad_text(img, cx, y, text, px, maxw=960):
    """Gradient headline centered at cx with its baseline at y, shrunk to fit maxw (never clipped)."""
    f = fb(px)
    while f.size > 20 and (f.getbbox(text, anchor="ms")[2] - f.getbbox(text, anchor="ms")[0]) > maxw:
        f = fb(f.size - 4)
    l, t, r, b = f.getbbox(text, anchor="ms"); p = 6
    w, h = r - l + 2 * p, b - t + 2 * p
    mk = Image.new("L", (w, h), 0); ImageDraw.Draw(mk).text((p - l, p - t), text, font=f, fill=255, anchor="ms")
    img.paste(grad(w, h), (int(cx + l - p), int(y + t - p)), mk)


def pill(img, x, y, text, font, fill=None, pad=(18, 10), color=WHITE, center=False):
    d = ImageDraw.Draw(img)
    tw = d.textlength(text, font=font)
    h = font.size + pad[1] * 2
    w = int(tw + pad[0] * 2)
    if center: x = int(x - w / 2)
    bg = grad(w, h) if fill is None else Image.new("RGB", (w, h), fill)
    m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=255)
    img.paste(bg, (int(x), int(y)), m)
    ImageDraw.Draw(img).text((x + w / 2, y + h / 2), text, font=font, fill=color, anchor="mm")
    return w, h


def wrap(d, text, font, maxw, lines=2):
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw or not cur: cur = t
        else: out.append(cur); cur = w
    if cur: out.append(cur)
    if len(out) > lines:
        out = out[:lines]
        while d.textlength(out[-1] + "…", font=font) > maxw and " " in out[-1]: out[-1] = out[-1].rsplit(" ", 1)[0]
        out[-1] += "…"
    return out


def cover_fit(src, W, H):
    return ImageOps.fit(Image.open(src).convert("RGB") if isinstance(src, str) else src, (W, H), Image.LANCZOS)


def blurred_bg(src, W, H, dark=0.45):
    bg = cover_fit(src, W, H).filter(ImageFilter.GaussianBlur(45))
    return Image.blend(bg, Image.new("RGB", (W, H), DARK), 1 - dark)


def accent_bar(img, s):
    W, H = img.size
    img.paste(grad(W, max(2, int(14 * s))), (0, H - max(2, int(14 * s))))


def credit(artist):
    """'@handle' for Instagram users, 'Name on ArtStation' for everyone else."""
    import re
    a = (artist or "").strip()
    if not a: return ""
    h = a.lstrip("@")
    return "@" + h if re.fullmatch(r"[A-Za-z0-9._]{1,30}", h) else f"{h} on ArtStation"


def short(artist):
    """Compact label for small spaces: @handle, or just the name for ArtStation artists."""
    c = credit(artist)
    return c.replace(" on ArtStation", "") if c else ""


# ---------------- Mon–Fri nominee post ----------------
def nominee_cover(src, dst, num, title, artist, total=5):
    img = Image.open(src).convert("RGB"); W, H = img.size; s = W / 1080
    img = vshade(img, 0, int(H * .34), .75, 0); img = vshade(img, int(H * .56), H, 0, .9)
    _, ph = pill(img, 48 * s, 48 * s, f"NOMINEE #{num} OF {total}", fb(34, s))
    d = ImageDraw.Draw(img)
    d.text((52 * s, 48 * s + ph + 12 * s), "ARTWORK OF THE WEEK", font=fm(24, s), fill=WHITE, anchor="lt")
    # progress: Mon..Fri dots, then Sat vote, Sun winners
    y = 48 * s + ph + 58 * s; x = 54 * s
    for i in range(total):
        r = 9 * s
        d.ellipse([x, y, x + 2 * r, y + 2 * r], fill=(CYAN if i < num else (90, 90, 110)))
        x += 2 * r + 10 * s
    d.text((x + 6 * s, y + 9 * s), "SAT VOTE  ·  SUN WINNERS", font=fm(20, s), fill=(220, 220, 235), anchor="lm")
    base = H - 56 * s
    d.text((W - 48 * s, base), "3D ROYALS", font=fb(26, s), fill=(230, 230, 240), anchor="rs")
    yy = base
    if artist:
        d.text((48 * s, yy), f"by {credit(artist)}", font=fm(36, s), fill=LILAC, anchor="ls"); yy -= 54 * s
    if title:
        for i, line in enumerate(reversed(wrap(d, f"“{title}”", fb(64, s), W - 96 * s))):
            d.text((48 * s, yy - i * 72 * s), line, font=fb(64, s), fill=WHITE, anchor="ls")
    accent_bar(img, s); img.save(dst, "JPEG", quality=93)


def nominee_end(src, dst, num, artist, ratio):
    W, H = 1080, int(round(1080 / ratio))
    img = blurred_bg(src, W, H); cx = W / 2
    k = min(1.0, H / 1150)                       # shrink the layout on landscape / square posts
    y = (H - 760 * k) / 2                         # content block (~760*k tall) centered vertically
    pill(img, cx, y, f"NOMINEE #{num} OF 5", fb(30, k), center=True, pad=(int(18 * k), int(10 * k))); d = ImageDraw.Draw(img)
    y += 135 * k; d.text((cx, y), "VOTE ON", font=fb(64, k), fill=WHITE, anchor="ms")
    y += 150 * k; grad_text(img, cx, y, "SATURDAY", int(150 * k), maxw=W - 120); d = ImageDraw.Draw(img)
    y += 70 * k; d.text((cx, y), "for the Artwork of the Week", font=fm(42, k), fill=WHITE, anchor="ms")
    y += 60 * k; d.text((cx, y), "Winners revealed on Sunday", font=fm(32, k), fill=(210, 210, 225), anchor="ms")
    y += 70 * k; d.rectangle([cx - 90 * k, y, cx + 90 * k, y + 3], fill=(120, 120, 140))
    if artist:
        y += 80 * k; line = f"Art by {credit(artist)}"; f = fb(44, k)
        while d.textlength(line, font=f) > W - 100 and f.size > 18: f = fb(f.size - 2)
        d.text((cx, y), line, font=f, fill=LILAC, anchor="ms")
    y += 64 * k; d.text((cx, y), f"Follow {BRAND} so you don't miss the vote", font=fm(32, k), fill=(225, 225, 235), anchor="ms")
    d.text((cx, H - 52 * k), "3D ROYALS", font=fb(26, k), fill=(230, 230, 240), anchor="ms")
    accent_bar(img, 1); img.save(dst, "JPEG", quality=92)


def detail_boxes(src, k=2, ratio=0.8):
    """Most detailed regions (fractions). Skips weak/low-res crops."""
    import numpy as np
    im = Image.open(src).convert("L"); W, H = im.size
    if W < 900 or k <= 0: return []
    sw = 96; sh = int(96 * H / W)
    e = np.asarray(im.resize((sw, sh)).filter(ImageFilter.FIND_EDGES), dtype=float)
    ww = int(sw * .42); wh = int(ww / ratio)
    if wh >= sh: return []
    I = e.cumsum(0).cumsum(1)
    def S(x, y): return I[y + wh - 1, x + ww - 1] - (I[y - 1, x + ww - 1] if y else 0) - (I[y + wh - 1, x - 1] if x else 0) + (I[y - 1, x - 1] if x and y else 0)
    mean = e.mean() * ww * wh
    cands = sorted(((S(x, y), x, y) for y in range(2, sh - wh - 2, 2) for x in range(2, sw - ww - 2, 2)), reverse=True)
    out = []
    for sc, x, y in cands:
        if sc < mean * 1.25: break  # not clearly more detailed than average -> skip
        if all(max(0, min(x, b[0]) + ww - max(x, b[0])) * max(0, min(y, b[1]) + wh - max(y, b[1])) < .15 * ww * wh for b in out):
            out.append((x, y))
        if len(out) >= k: break
    return [(x / sw, y / sh, ww / sw, wh / sh) for x, y in out]


def detail_slide(src, dst, box, i, ratio):
    im = Image.open(src).convert("RGB"); W, H = im.size
    x, y, w, h = box
    crop = im.crop((int(x * W), int(y * H), int((x + w) * W), int((y + h) * H))).resize((1080, int(1080 / ratio)), Image.LANCZOS)
    pill(crop, 40, 40, f"DETAIL {i}", fb(30), fill=(18, 18, 30))
    accent_bar(crop, 1); crop.save(dst, "JPEG", quality=92)


# ---------------- Saturday vote ----------------
def thumb_with_num(src, size, num):
    t = cover_fit(src, size, size)
    m = Image.new("L", (size, size), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * .08), fill=255)
    d = ImageDraw.Draw(t); r = int(size * .13)
    d.ellipse([14, 14, 14 + 2 * r, 14 + 2 * r], fill=(255, 255, 255)); d.text((14 + r, 14 + r), str(num), font=fb(r * 1.3), fill=DARK, anchor="mm")
    return t, m


def vote_cover(srcs, handles, dst, week_label=""):
    W, H = 1080, 1350; img = blurred_bg(srcs[0], W, H, .30); d = ImageDraw.Draw(img); cx = W / 2
    pill(img, cx, 56, "ARTWORK OF THE WEEK", fb(30), center=True); d = ImageDraw.Draw(img)
    grad_text(img, cx, 280, "VOTE", 170); d = ImageDraw.Draw(img)
    d.text((cx, 352), "Comment the number of your favorite", font=fm(38), fill=WHITE, anchor="ms")
    n = len(srcs); size = 300; gap = 28
    rows = [srcs[:3], srcs[3:]] if n > 3 else [srcs]
    y = 410; k = 0
    for row in rows:
        x = cx - (len(row) * size + (len(row) - 1) * gap) / 2
        for sp in row:
            t, m = thumb_with_num(sp, size, k + 1); img.paste(t, (int(x), int(y)), m)
            d = ImageDraw.Draw(img); d.text((x + size / 2, y + size + 34), handles[k][:22], font=fm(24), fill=LILAC, anchor="ms")
            x += size + gap; k += 1
        y += size + 70
    d.text((cx, H - 70), "Winners revealed Sunday  ·  3D ROYALS", font=fb(26), fill=(230, 230, 240), anchor="ms")
    accent_bar(img, 1); img.save(dst, "JPEG", quality=92)


def vote_slide(src, dst, num, handle, ratio=0.8):
    W, H = 1080, int(1080 / ratio); img = cover_fit(src, W, H)
    img = vshade(img, 0, int(H * .26), .78, 0); img = vshade(img, int(H * .72), H, 0, .85); d = ImageDraw.Draw(img)
    r = 70; d.ellipse([48, 44, 48 + 2 * r, 44 + 2 * r], fill=WHITE); d.text((48 + r, 44 + r), str(num), font=fb(96), fill=DARK, anchor="mm")
    d.text((48 + 2 * r + 28, 44 + r - 26), "VOTE", font=fb(46), fill=WHITE, anchor="lm")
    d.text((48 + 2 * r + 28, 44 + r + 26), f"Comment {num} below", font=fm(32), fill=(225, 225, 235), anchor="lm")
    d.text((48, H - 60), handle, font=fb(44), fill=LILAC, anchor="ls"); d.text((W - 48, H - 60), "3D ROYALS", font=fb(26), fill=(230, 230, 240), anchor="rs")
    accent_bar(img, 1); img.save(dst, "JPEG", quality=92)


def vote_story(srcs, handles, dst):
    W, H = 1080, 1920; img = blurred_bg(srcs[0], W, H, .28); d = ImageDraw.Draw(img); cx = W / 2
    pill(img, cx, 250, "ARTWORK OF THE WEEK", fb(34), center=True); d = ImageDraw.Draw(img)
    grad_text(img, cx, 490, "VOTE NOW", 140); d = ImageDraw.Draw(img)
    size, gap = 300, 40; y = 540; k = 0
    for row in [srcs[:2], srcs[2:4], srcs[4:5]]:
        if not row: continue
        x = cx - (len(row) * size + (len(row) - 1) * gap) / 2
        for sp in row:
            t, m = thumb_with_num(sp, size, k + 1); img.paste(t, (int(x), int(y)), m)
            d = ImageDraw.Draw(img); d.text((x + size / 2, y + size + 34), handles[k][:24], font=fm(26), fill=LILAC, anchor="ms")
            x += size + gap; k += 1
        y += size + 56
    d.text((cx, H - 300), "Comment your number on today's post", font=fb(38), fill=WHITE, anchor="ms")
    d.text((cx, H - 245), "Winners revealed Sunday", font=fm(30), fill=(220, 220, 235), anchor="ms")
    accent_bar(img, 1); img.save(dst, "JPEG", quality=92)


# ---------------- Sunday results ----------------
MEDAL = {1: (GOLD, "1ST"), 2: (SILVER, "2ND"), 3: (BRONZE, "3RD")}


def podium(srcs, handles, dst):
    """srcs/handles ordered 1st, 2nd, 3rd."""
    W, H = 1080, 1350; img = blurred_bg(srcs[0], W, H, .28); d = ImageDraw.Draw(img); cx = W / 2
    pill(img, cx, 56, "ARTWORK OF THE WEEK", fb(30), center=True); d = ImageDraw.Draw(img)
    grad_text(img, cx, 270, "RESULTS", 140); d = ImageDraw.Draw(img)
    cols = [(2, cx - 330, 330), (1, cx, 450), (3, cx + 330, 250)]   # place, center x, block height
    base = H - 90; size = 290
    for place, x, bh in cols:
        if place > len(srcs): continue
        col, lab = MEDAL[place]
        d.rounded_rectangle([x - 150, base - bh, x + 150, base], radius=18, fill=tuple(int(c * .85) for c in col))
        d.text((x, base - bh + 70), lab, font=fb(56), fill=DARK, anchor="ms")
        d.text((x, base - bh + 118), handles[place - 1][:20], font=fm(26), fill=DARK, anchor="ms")
        t, m = thumb_with_num(srcs[place - 1], size, place)
        ImageDraw.Draw(t).ellipse([0, 0, 0, 0])
        img.paste(t, (int(x - size / 2), int(base - bh - size - 22)), m)
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([x - size / 2, base - bh - size - 22, x + size / 2, base - bh - 22], radius=int(size * .08), outline=col, width=8)
    accent_bar(img, 1); img.save(dst, "JPEG", quality=92)


def winner_slide(src, dst, place, handle, ratio=0.8):
    W, H = 1080, int(1080 / ratio); img = cover_fit(src, W, H)
    img = vshade(img, 0, int(H * .24), .75, 0); img = vshade(img, int(H * .70), H, 0, .88); d = ImageDraw.Draw(img)
    col, lab = MEDAL[place]
    pill(img, 48, 48, f"{lab} PLACE  ·  ARTWORK OF THE WEEK", fb(32), fill=col, color=DARK); d = ImageDraw.Draw(img)
    d.text((48, H - 60), handle, font=fb(48), fill=WHITE, anchor="ls"); d.text((W - 48, H - 60), "3D ROYALS", font=fb(26), fill=(230, 230, 240), anchor="rs")
    accent_bar(img, 1); img.save(dst, "JPEG", quality=92)


def winner_story(src, dst, place, handle):
    W, H = 1080, 1920; img = blurred_bg(src, W, H, .35); d = ImageDraw.Draw(img); cx = W / 2
    col, lab = MEDAL[place]
    pill(img, cx, 250, "WINNER" if place == 1 else f"{lab} PLACE", fb(40), fill=col, color=DARK, center=True); d = ImageDraw.Draw(img)
    d.text((cx, 390), "Artwork of the Week", font=fb(58), fill=WHITE, anchor="ms")
    art = Image.open(src).convert("RGB"); art.thumbnail((860, 940), Image.LANCZOS)
    x, y = int(cx - art.width / 2), 450
    d.rounded_rectangle([x - 8, y - 8, x + art.width + 8, y + art.height + 8], radius=26, fill=col)
    m = Image.new("L", art.size, 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, art.width - 1, art.height - 1], radius=20, fill=255)
    img.paste(art, (x, y), m); d = ImageDraw.Draw(img)
    y2 = y + art.height + 110
    d.text((cx, y2), handle, font=fb(56), fill=LILAC, anchor="ms")
    d.text((cx, y2 + 70), f"on {BRAND}", font=fm(36), fill=WHITE, anchor="ms")
    accent_bar(img, 1); img.save(dst, "JPEG", quality=92)
