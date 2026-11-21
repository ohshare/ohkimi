#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kimi 社区数据流抓取：动态 + HTML 作品 + 评论 -> community.json

已实测接口（2026-11-21）：
  POST moment.v1.SearchService/SearchMoments      {query, sessionId}
  POST moment.v1.CommentService/ListComments      {momentId, pageSize}
  动态字段：content.title / chatShareCard.htmlFile.cdnUrl / coverImage / stat.commentNum / author
  评论字段：comments[].content.text / author.name / createTime

用法：
  export KIMI_TOKEN="<access_token>"   # 或用 KIMI_RT 自动续期
  python3 fetch_community.py
"""
import os, sys, json, time, re, html
import urllib.request, urllib.error

BASE = "https://www.kimi.com/apiv2"
AUTH = "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "community.json")

AT = os.environ.get("KIMI_TOKEN", "").strip()
RT = os.environ.get("KIMI_RT", "").strip()

HEAD = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "x-msh-platform": "web",
    "x-msh-version": "2.1.0",
    "R-Timezone": "Asia/Shanghai",
    "X-Language": "zh-CN",
    "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36",
}

QUERIES = ["游戏", "HTML", "小游戏", "作品", "AI", "教程", "工具", "绘画", "网页", "创意", "互动", "代码"]
PAGES = 2
COMMENT_LIMIT = 8          # 每条动态最多抓几条评论
MAX_MOMENTS = 120          # 最多收录多少条动态


def deep_find(obj, names, depth=0):
    if depth > 6 or obj is None:
        return None
    if isinstance(obj, dict):
        for n in names:
            if n in obj and isinstance(obj[n], str) and obj[n]:
                return obj[n]
        for v in obj.values():
            r = deep_find(v, names, depth + 1)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = deep_find(v, names, depth + 1)
            if r:
                return r
    return None


def ensure_token():
    global AT
    if AT:
        return AT
    if not RT:
        sys.exit("❌ 需要 KIMI_TOKEN 或 KIMI_RT")
    body = json.dumps({"refreshToken": RT}).encode()
    req = urllib.request.Request(AUTH, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        d = json.loads(r.read().decode())
    at = deep_find(d, ["accessToken", "access_token"])
    if not at:
        sys.exit("❌ 续期失败")
    AT = at
    return AT


def call(path, payload):
    h = dict(HEAD, Authorization="Bearer " + ensure_token())
    req = urllib.request.Request(BASE + "/" + path, method="POST", headers=h,
                                 data=json.dumps(payload).encode())
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


def author_of(x):
    a = x.get("author") or {}
    ub = a.get("userBase") or a
    av = ""
    ai = ub.get("avatarImage") or {}
    if isinstance(ai, dict):
        av = ai.get("url") or ""
    elif isinstance(ai, str):
        av = ai
    if not av and isinstance(ub.get("avatar"), str):
        av = ub["avatar"]
    return {
        "id": ub.get("userId") or ub.get("id") or "",
        "name": ub.get("name") or "匿名",
        "avatar": av,
        "bio": ub.get("bio") or "",
    }


def thumb(url):
    """保留 x-tos-process 的 resize 参数（缩略图），避免加载原图几MB"""
    if not url:
        return ""
    return url


def images_of(content):
    """提取 content.media.images（图文动态的配图），用缩略图"""
    media = content.get("media") or {}
    out = []
    for im in (media.get("images") or [])[:9]:
        u = im.get("thumbnailUrl") or im.get("originUrl") or ""
        if u:
            out.append(thumb(u))
    return out


def extract_html(segments):
    """从聊天 segments 里提取 html 代码块（备用：cdnUrl 失效时可用）"""
    for seg in segments or []:
        txt = seg.get("text") or ""
        m = re.search(r"```html\s*(.*?)```", txt, re.S | re.I)
        if m and len(m.group(1)) > 200:
            return m.group(1).strip()
    return ""


def norm_moment(x):
    m = x.get("moment", x)
    if not isinstance(m, dict):
        return None
    c = m.get("content") or {}
    if isinstance(c, str):
        c = {"title": c}

    card = m.get("chatShareCard") or {}
    hf = card.get("htmlFile") or {}
    cover = hf.get("coverImage") or {}
    cover_url = cover.get("originUrl") or cover.get("thumbnailUrl") or ""
    # originUrl 带 x-tos-process 参数，取干净原图
    if cover_url and "x-tos-process" in cover_url:
        cover_url = cover_url.split("?")[0]

    segs = (c.get("chatInfo") or {}).get("segments") or []
    title = c.get("title") or ""
    if not title:
        for s in segs:
            if s.get("role") == "CHAT_ROLE_USER" and s.get("text"):
                title = s["text"][:80]
                break

    # 正文 text/excerpt + 配图 media.images + 缩略封面
    body = (c.get("text") or c.get("excerpt") or "").strip()
    imgs = images_of(c)
    if cover_url and "x-tos-process" in cover_url and "resize" not in cover_url:
        # 封面原图 -> 换成 480 缩略图
        cover_url = re.sub(r"image%2Fauto-orient%2C1%2Fstrip",
                           "image%2Fauto-orient%2C1%2Fstrip%2Fresize%2Cw_480%2Ch_480%2Cm_mfit", cover_url)

    st = m.get("stat") or {}
    mid = str(m.get("id") or "")
    if not mid:
        return None

    return {
        "id": mid,
        "title": title,
        "text": body[:600],
        "images": imgs,
        "author": author_of(m),
        "create_time": m.get("createTime") or m.get("publishTime") or "",
        "likes": int(st.get("likeNum") or 0),
        "comment_num": int(st.get("commentNum") or 0),
        "html_url": hf.get("cdnUrl") or "",
        "html_code": extract_html(segs) if hf.get("cdnUrl") else "",
        "cover": cover_url,
        "prompt": hf.get("remixPrompt") or "",
        "comments": [],
    }


def fetch_comments(mid, limit):
    d = None
    for attempt in range(3):
        try:
            st, d = call("moment.v1.CommentService/ListComments",
                         {"momentId": mid, "pageSize": limit})
            break
        except Exception:
            time.sleep(1 + attempt)
    if not d:
        return []
    out = []
    for c in (d.get("comments") or [])[:limit]:
        txt = (c.get("content") or {}).get("text") or ""
        if not txt:
            continue
        stt = c.get("stat") or {}
        out.append({
            "author": author_of(c),
            "text": txt,
            "time": c.get("createTime") or "",
            "likes": int(stt.get("likeNum") or 0),
        })
    return out


def load_rank_map():
    """读粉丝榜 data.json，建立 userId -> 排名/粉丝数 映射"""
    path = os.path.join(HERE, "data.json")
    if not os.path.exists(path):
        return {}
    try:
        d = json.load(open(path, encoding="utf-8"))
        rows = d.get("bloggers", [])
        rows = sorted(rows, key=lambda x: -(x.get("followers") or 0))
        m = {}
        for i, r in enumerate(rows, 1):
            uid = r.get("userId") or ""
            if uid:
                m[uid] = {"rank": i, "followers": r.get("followers") or 0}
        return m
    except Exception:
        return {}


def main():
    ensure_token()
    rank_map = load_rank_map()
    print("▶ 抓取社区动态…（粉丝榜索引 %d 人）" % len(rank_map))
    seen = {}
    for q in QUERIES:
        tok = None
        for _ in range(PAGES):
            payload = {"query": q, "sessionId": "community-" + str(int(time.time() * 1000))}
            if tok:
                payload["_nextPageToken"] = tok
            st, d = call("moment.v1.SearchService/SearchMoments", payload)
            if st != 200 or not d:
                if st == 401:
                    global AT
                    AT = ""   # 强制下次续期
                break
            ms = d.get("moments") or d.get("relatedMoments") or []
            for x in ms:
                w = norm_moment(x)
                if w:
                    seen[w["id"]] = w
            tok = d.get("_nextPageToken") or d.get("nextPageToken")
            if not tok or not ms:
                break
            time.sleep(0.2)
        print(f"  [{q}] 累计 {len(seen)}")
        time.sleep(0.2)
        if len(seen) >= MAX_MOMENTS:
            break

    rows = list(seen.values())
    # 优先有 HTML 作品的、评论多的
    rows.sort(key=lambda w: (bool(w["html_url"]), w["comment_num"], w["likes"]), reverse=True)
    rows = rows[:MAX_MOMENTS]

    print(f"▶ 抓取评论（{min(len(rows), 60)} 条动态）…")
    for i, w in enumerate(rows[:60], 1):
        if w["comment_num"] > 0:
            w["comments"] = fetch_comments(w["id"], COMMENT_LIMIT)
            time.sleep(0.15)
        if i % 20 == 0:
            print(f"  {i}/{len(rows)}")

    # 给作者补充粉丝榜排名
    for w in rows:
        r = rank_map.get(w["author"]["id"])
        w["author"]["rank"] = r["rank"] if r else 0
        w["author"]["followers"] = r["followers"] if r else 0

    # 热度分：点赞 + 评论*3，供排行榜用
    for w in rows:
        w["hot"] = w["likes"] + w["comment_num"] * 3

    out = {
        "updated_at": time.strftime("%Y-%m-%d %H:%M"),
        "total": len(rows),
        "html_count": sum(1 for w in rows if w["html_url"]),
        "works": rows,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"✅ 完成：{len(rows)} 条动态 / {out['html_count']} 个 HTML 作品 → {OUT}")


if __name__ == "__main__":
    main()
