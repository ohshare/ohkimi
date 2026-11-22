#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性探测：能否用我们自己的 token 走通「发消息→CreateChatShare→GetChatShareCard」
把每一步的完整响应写进 community.json 的 _probe 字段带回本地分析。
跑完务必恢复 fetch_community.py 原版！
"""
import os, sys, json, time, re
import urllib.request, urllib.error

BASE = "https://www.kimi.com/apiv2"
AUTH = "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "community.json")

RT = os.environ.get("KIMI_RT", "").strip() or os.environ.get("KIMI_REFRESH_TOKEN", "").strip()
HEAD = {
    "Content-Type": "application/json",
    "Accept": "application/json",
    "x-msh-platform": "web",
    "x-msh-version": "2.1.0",
    "R-Timezone": "Asia/Shanghai",
    "X-Language": "zh-CN",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
}

def deep_find(o, names, d=0):
    if d > 8 or not o or not isinstance(o, (dict, list)): return None
    if isinstance(o, list):
        for x in o:
            r = deep_find(x, names, d+1)
            if r: return r
        return None
    for k in names:
        if k in o and isinstance(o[k], str) and o[k]: return o[k]
    for v in o.values():
        r = deep_find(v, names, d+1)
        if r: return r
    return None

def deep_collect(o, key, out, d=0):
    if d > 12 or not o or not isinstance(o, (dict, list)): return
    if isinstance(o, list):
        for x in o: deep_collect(x, key, out, d+1)
        return
    for k, v in o.items():
        if k == key and isinstance(v, str): out.append(v)
        deep_collect(v, key, out, d+1)

def call(path, body, token, timeout=90):
    try:
        req = urllib.request.Request(BASE + "/" + path,
              data=json.dumps(body, ensure_ascii=False).encode(),
              headers=dict(HEAD, Authorization="Bearer " + token), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read().decode("utf-8", "ignore")
            return {"http": r.status, "raw": raw[:20000]}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "raw": e.read().decode("utf-8", "ignore")[:20000]}
    except Exception as e:
        return {"http": -1, "raw": "EXC: " + str(e)}

def renew():
    req = urllib.request.Request(AUTH, data=json.dumps({"refreshToken": RT}).encode(),
          headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    a = deep_find(d, ["accessToken", "access_token"])
    if not a: raise RuntimeError("renew failed: " + json.dumps(d, ensure_ascii=False)[:500])
    return a

def probe_chat(at):
    """方案A: OKC 场景让 Kimi 生成 HTML；返回各种 id 与原始响应"""
    out = {}
    msg = {
        "$typeName": "kimi.chat.v1.ChatMessage",
        "refVotes": [], "id": "", "parentId": "", "childrenMessageIds": [],
        "role": "ROLE_USER",
        "blocks": [{
            "$typeName": "kimi.chat.v1.Block", "id": "", "parentId": "", "messageId": "",
            "content": {"case": "text", "value": {
                "$typeName": "kimi.chat.v1.TextBlock",
                "content": "帮我生成一个HTML网页，内容是一个大大的红色按钮，点击后显示 Hello World。直接给出完整 HTML 代码。"
            }}
        }],
        "scenario": "OKC", "labels": [], "references": [], "isGoal": False
    }
    body = {
        "$typeName": "kimi.gateway.chat.v1.ChatRequest",
        "chatId": "", "kimiplusId": "", "scenario": "OKC", "projectId": "",
        "tools": [], "message": msg,
        "options": {"$typeName": "kimi.gateway.chat.v1.ChatRequestOptions", "thinking": False}
    }
    r = call("kimi.gateway.chat.v1.ChatService/Chat", body, at, timeout=150)
    raw = r["raw"]
    ids = {}
    for key in ("chatId", "chat_id", "messageId", "message_id", "artifactId", "artifact_id"):
        col = []
        deep_collect(try_json(raw), key, col)
        if not col:
            col = re.findall(r'"%s"\s*:\s*"([^"]+)"' % key, raw)
        ids[key] = list(dict.fromkeys(col))[:8]
    out["OKC-chat"] = {"http": r["http"], "ids": ids, "raw_head": raw[:6000]}
    return out

def try_json(s):
    try: return json.loads(s)
    except Exception:
        # SSE: 抽 data: 行里的 json
        objs = []
        for line in s.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                line = line[5:].strip()
            if line.startswith("{"):
                try: objs.append(json.loads(line))
                except Exception: pass
        return objs

def probe_share(at, chat_id, msg_ids):
    out = {}
    for pname, path, body in [
        ("CreateChatShare", "kimi.gateway.chat.v1.ChatService/CreateChatShare",
         {"chatId": chat_id, "messageIds": msg_ids}),
        ("ShareChatToCommunity", "kimi.gateway.chat.v1.ChatService/ShareChatToCommunity",
         {"chatId": chat_id, "messageIds": msg_ids}),
    ]:
        r = call(path, body, at)
        j = try_json(r["raw"])
        ids = {}
        for key in ("id", "shareId", "url", "chatShareId"):
            col = []
            deep_collect(j, key, col)
            ids[key] = list(dict.fromkeys(col))[:5]
        out[pname] = {"http": r["http"], "ids": ids, "raw": r["raw"][:4000]}
    return out

def probe_card(at, share_ids):
    out = {}
    for sid in share_ids[:5]:
        r = call("moment.v1.MomentService/GetChatShareCard", {"chatShareId": sid}, at)
        out[sid] = {"http": r["http"], "raw": r["raw"][:4000]}
    return out

def main():
    result = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": {}}
    try:
        at = renew()
        result["steps"]["renew"] = {"ok": True, "len": len(at)}
        result["steps"]["chat"] = probe_chat(at)
        # 从 chat 结果里提取 chatId/messageId 再试 share
        chat = result["steps"]["chat"].get("OKC-chat", {})
        ids = chat.get("ids", {})
        chat_ids = ids.get("chatId", [])
        msg_ids = ids.get("messageId", [])
        if chat_ids and msg_ids:
            result["steps"]["share"] = probe_share(at, chat_ids[0], msg_ids[:3])
            share_ids = []
            for v in result["steps"]["share"].values():
                share_ids += v.get("ids", {}).get("id", [])
                share_ids += v.get("ids", {}).get("shareId", [])
            result["steps"]["card"] = probe_card(at, share_ids)
        else:
            result["steps"]["share"] = {"skipped": "no chatId/messageId", "chat_ids": chat_ids, "msg_ids": msg_ids}
    except Exception as e:
        result["error"] = repr(e)
    # 写回 community.json（不破坏 works）
    try:
        d = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        d = {"works": []}
    d["_probe"] = result
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    print("probe done:", json.dumps(result, ensure_ascii=False)[:3000])

if __name__ == "__main__":
    main()
