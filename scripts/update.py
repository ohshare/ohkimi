#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kimi 社区博主粉丝榜 · 服务端自动更新脚本
由 GitHub Actions / cron 调用：续期 token -> 抓取 -> 合并去重 -> 生成网页。
"""

import os, sys, json, time, base64, hashlib, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = "https://www.kimi.com/apiv2"
AUTH = "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"
TOKEN_ENC = os.path.join(ROOT, "token.enc")
DATA = os.path.join(ROOT, "data.json")
STATE = os.path.join(ROOT, "state.json")
TPL = os.path.join(ROOT, "template.html")
OUT = os.path.join(ROOT, "index.html")

PASSPHRASE = os.environ.get("TOKEN_PASSPHRASE", "")
ENV_RT = os.environ.get("KIMI_REFRESH_TOKEN", "").strip()

CORE = ['', 'Kimi', 'AI', '提示词', '教程', '工具', '游戏', '绘画', '写作', '编程', '副业', '效率', '学习', '职场', '生活',
        '设计', 'Agent', '智能体', '网页', '小程序', '文案', '翻译', 'PPT', '数据分析', '代码', '小说', '故事', '音乐', '视频',
        '科研', '考研', '留学', '面试', '简历', '电商', '自媒体', '公众号', '小红书', '抖音', 'B站', '办公', 'Excel',
        '法律', '心理', '健身', '美食', '旅行', '摄影', '动画', '3D', '模型', '开源', '产品', '创业', '投资', '理财',
        '英语', '数学', '物理', '历史', '哲学', '科幻', '二次元', '表情包', '头像', '壁纸', '闲聊', '日常', '分享', '作品']
CORE_PER_RUN = 14
LEARNED_PER_RUN = 8
MAX_BATCH = 24
MAX_LEARNED = 240
MAX_PAGES = 2
MAX_REFRESH = 320

HEAD = {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'x-msh-platform': 'web',
    'x-msh-version': '2.1.0',
    'R-Timezone': 'Asia/Shanghai',
    'X-Language': 'zh-CN',
    'User-Agent': 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36',
}


def log(*a):
    print(*a, flush=True)


# ---------------- token 存取 ----------------
def fernet():
    if not PASSPHRASE:
        return None
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(hashlib.pbkdf2_hmac('sha256', PASSPHRASE.encode(), b'kimi-rank-v1', 120000))
    return Fernet(key)


def load_refresh_token():
    f = fernet()
    if os.path.exists(TOKEN_ENC) and f:
        try:
            return f.decrypt(open(TOKEN_ENC, 'rb').read()).decode()
        except Exception as e:
            log('⚠ token.enc 解密失败，回退到环境变量：', e)
    if ENV_RT:
        return ENV_RT
    raise SystemExit('❌ 没有 refresh_token：请设置 KIMI_REFRESH_TOKEN secret，或确认 token.enc 与 TOKEN_PASSPHRASE 匹配')


def save_refresh_token(rt):
    f = fernet()
    if not f:
        log('⚠ 未设置 TOKEN_PASSPHRASE，无法安全保存轮换后的 token；本次仍可运行，但下次可能失效')
        return
    open(TOKEN_ENC, 'wb').write(f.encrypt(rt.encode()))


# ---------------- 刷新 access_token ----------------
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


def refresh_access_token(rt):
    body = json.dumps({'refreshToken': rt}).encode()
    req = urllib.request.Request(AUTH, data=body, method='POST',
                                 headers={'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        detail = ''
        try:
            detail = e.read().decode()[:300]
        except Exception:
            pass
        raise SystemExit(f'❌ 续期失败 HTTP {e.code}：{detail}\n   说明 refresh_token 可能已失效，需要重新登录 Kimi 并更新 secret。')
    at = deep_find(data, ['accessToken', 'access_token'])
    nrt = deep_find(data, ['refreshToken', 'refresh_token'])
    if not at:
        raise SystemExit('❌ 续期响应里没找到 access_token：' + json.dumps(data, ensure_ascii=False)[:300])
    return at, (nrt or rt)


# ---------------- API ----------------
def api(path, body, access):
    req = urllib.request.Request(BASE + '/' + path, method='POST',
                                 headers=dict(HEAD, Authorization='Bearer ' + access),
                                 data=json.dumps(body).encode())
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None


# ---------------- 抓取 ----------------
def build_batch(state):
    batch = []
    cur = state.get('kwCursor', 0) % len(CORE)
    for i in range(CORE_PER_RUN):
        batch.append(CORE[(cur + i) % len(CORE)])
    state['kwCursor'] = (cur + CORE_PER_RUN) % len(CORE)

    for k in state.get('learned', [])[:LEARNED_PER_RUN]:
        if k not in batch:
            batch.append(k)
    for k in state.get('learned', [])[:4]:
        v = k + ' 教程'
        if v not in batch and len(batch) < MAX_BATCH:
            batch.append(v)
    j = 0
    while len(batch) < MAX_BATCH and j < len(CORE):
        k = CORE[(state['kwCursor'] + j) % len(CORE)]
        if k not in batch:
            batch.append(k)
        j += 1
    seen, out = set(), []
    for k in batch:
        k = str(k).strip()
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out[:MAX_BATCH]


def add_kw(s, out):
    s = str(s).lstrip('#').strip()
    if 2 <= len(s) <= 20 and not s.isdigit():
        out[s] = 1


def harvest(obj, out, depth=0):
    if depth > 6 or obj is None:
        return
    if isinstance(obj, list):
        for v in obj[:12]:
            harvest(v, out, depth + 1)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if any(t in k.lower() for t in ('topic', 'tag', 'hashtag')):
                if isinstance(v, str):
                    add_kw(v, out)
                elif isinstance(v, list):
                    for x in v:
                        if isinstance(x, str):
                            add_kw(x, out)
                        elif isinstance(x, dict):
                            add_kw(x.get('name') or x.get('title') or '', out)
                elif isinstance(v, dict):
                    add_kw(v.get('name') or v.get('title') or '', out)
            if isinstance(v, (dict, list)):
                harvest(v, out, depth + 1)


def get_author(moment):
    m = moment.get('moment', moment) if isinstance(moment, dict) else {}
    ub = (m.get('author') or {}).get('userBase') or m.get('author') or {}
    av = (ub.get('avatarImage') or {}).get('url') or (ub.get('avatar') if isinstance(ub.get('avatar'), str) else '') or ''
    return ub.get('userId'), ub.get('name') or '匿名', av


def run():
    rt = load_refresh_token()
    log('① 续期 access_token…')
    at, nrt = refresh_access_token(rt)
    if nrt != rt:
        save_refresh_token(nrt)
    log('   ✅ 成功')

    # 现有数据（去重基础）
    data = {'updated_at': '', 'source': 'Kimi 社区（发现）', 'bloggers': []}
    if os.path.exists(DATA):
        try:
            data = json.load(open(DATA, encoding='utf-8'))
        except Exception:
            pass
    author_map = {}
    for r in data.get('bloggers', []):
        if r.get('userId') or r.get('name'):
            author_map[r.get('userId') or r.get('name')] = dict(r)
    existing = set(author_map.keys())
    log(f'   已有 {len(author_map)} 位博主')

    state = {'kwCursor': 0, 'learned': []}
    if os.path.exists(STATE):
        try:
            state = json.load(open(STATE, encoding='utf-8'))
        except Exception:
            pass

    batch = build_batch(state)
    log(f'② 本轮 {len(batch)} 个关键词：' + ' / '.join([k or '默认' for k in batch[:10]]))

    learned = {}
    risk = False
    for qi, q in enumerate(batch):
        tok = None
        for _ in range(MAX_PAGES):
            body = {'query': q, 'sessionId': 'rank-' + str(int(time.time() * 1000))}
            if tok:
                body['_nextPageToken'] = tok
            st, resp = api('moment.v1.SearchService/SearchMoments', body, at)
            if st == 401:
                at, nrt = refresh_access_token(load_refresh_token())
                save_refresh_token(nrt)
                st, resp = api('moment.v1.SearchService/SearchMoments', body, at)
            if st == 403:
                risk = True
                break
            if st != 200 or not resp:
                break
            ms = resp.get('moments') or resp.get('relatedMoments') or []
            for m in ms:
                uid, name, avatar = get_author(m)
                if uid and uid not in author_map:
                    author_map[uid] = {'userId': uid, 'name': name, 'avatar': avatar,
                                       'followers': None, 'following': None, 'likes': None, 'bio': ''}
                mm = m.get('moment', m) if isinstance(m, dict) else {}
                harvest(mm, learned)
            tok = resp.get('_nextPageToken') or resp.get('nextPageToken')
            if not tok or not ms:
                break
            time.sleep(0.7 if risk else 0.18)
        if risk:
            log('   ⚠ 触发风控，提前收尾')
            break
        if qi % 6 == 5:
            log(f'   搜索进度 {qi + 1}/{len(batch)} · 累计 {len(author_map)} 位')
        time.sleep(0.18)

    # 学到的词并入
    if learned:
        merged = list(learned.keys()) + state.get('learned', [])
        seen, out = set(), []
        for k in merged:
            if k not in seen:
                seen.add(k)
                out.append(k)
        state['learned'] = out[:MAX_LEARNED]
    log(f'   本轮学到 {len(learned)} 个新词，词库共 {len(state.get("learned", []))} 个')

    # 新博主优先抓资料
    all_a = list(author_map.values())
    new_a = [a for a in all_a if a.get('userId') not in existing]
    old_a = [a for a in all_a if a.get('userId') in existing]
    todo = (new_a + old_a)[:MAX_REFRESH]
    log(f'③ 读取 {len(todo)} 位博主资料（新增 {len(new_a)}）…')

    for i, a in enumerate(todo):
        st, resp = api('moment.v1.UserService/GetUserProfile', {'userId': a['userId']}, at)
        if st == 401:
            at, nrt = refresh_access_token(load_refresh_token())
            save_refresh_token(nrt)
            st, resp = api('moment.v1.UserService/GetUserProfile', {'userId': a['userId']}, at)
        if st == 403:
            log('   ⚠ 读取资料触发风控，收尾')
            break
        if st == 200 and resp:
            ub = resp.get('userBase') or (resp.get('userInfo') or {}).get('userBase') or {}
            stt = resp.get('userStat') or (resp.get('userInfo') or {}).get('userStat') or {}
            cur = author_map[a['userId']]
            cur['name'] = ub.get('name') or cur.get('name') or '匿名'
            cur['avatar'] = (ub.get('avatarImage') or {}).get('url') or (ub.get('avatar') if isinstance(ub.get('avatar'), str) else '') or cur.get('avatar') or ''
            cur['bio'] = ub.get('bio') or ub.get('description') or ub.get('intro') or cur.get('bio') or ''
            cur['followers'] = int(stt.get('followerNum') or 0)
            cur['following'] = int(stt.get('followingNum') or stt.get('followNum') or 0)
            cur['likes'] = int(stt.get('momentLikesNum') or stt.get('likeNum') or 0)
        if i % 40 == 39:
            log(f'   资料进度 {i + 1}/{len(todo)}')
        time.sleep(0.7 if risk else 0.14)

    rows = [r for r in author_map.values() if r.get('followers') is not None]
    rows.sort(key=lambda x: x.get('followers') or 0, reverse=True)

    data['updated_at'] = time.strftime('%Y-%m-%dT%H:%M', time.gmtime())  # UTC，网页会转北京时间
    data['source'] = 'Kimi 社区（发现）'
    data['bloggers'] = [{
        'name': r.get('name') or '匿名',
        'followers': r.get('followers') or 0,
        'following': r.get('following') or 0,
        'likes': r.get('likes') or 0,
        'bio': r.get('bio') or '',
        'avatar': r.get('avatar') or '',
        'url': '',
        'userId': r.get('userId') or ''
    } for r in rows]

    json.dump(data, open(DATA, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    json.dump(state, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

    log(f'✅ 完成：{len(rows)} 位博主（本轮新增 {len(new_a)}）→ data.json')
    log(f'   榜首：{rows[0]["name"]} {rows[0]["followers"]} 粉丝' if rows else '   （无数据）')


if __name__ == '__main__':
    run()
