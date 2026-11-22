#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""探测2：修正 Content-Type/body 格式，找出 Chat 接口正确请求形态。结果写 community.json._probe2"""
import os, json, time, re
import urllib.request, urllib.error

BASE = "https://www.kimi.com/apiv2"
AUTH = "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "community.json")
RT = os.environ.get("KIMI_RT", "").strip() or os.environ.get("KIMI_REFRESH_TOKEN", "").strip()

def H(ct="application/json"):
    return {"Content-Type": ct, "Accept": "application/json",
        "x-msh-platform": "web", "x-msh-version": "2.1.0",
        "R-Timezone": "Asia/Shanghai", "X-Language": "zh-CN",
        "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36"}

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

def call(path, body, token, ct="application/json", timeout=150):
    try:
        data = json.dumps(body, ensure_ascii=False).encode()
        req = urllib.request.Request(BASE + "/" + path, data=data,
              headers=dict(H(ct), Authorization="Bearer " + token), method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"http": r.status, "ct_r": r.headers.get("Content-Type",""), "raw": r.read().decode("utf-8","ignore")[:8000]}
    except urllib.error.HTTPError as e:
        return {"http": e.code, "ct_r": e.headers.get("Content-Type",""), "raw": e.read().decode("utf-8","ignore")[:8000]}
    except Exception as e:
        return {"http": -1, "raw": "EXC: " + repr(e)}

def renew():
    req = urllib.request.Request(AUTH, data=json.dumps({"refreshToken": RT}).encode(),
          headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.loads(r.read().decode())
    a = deep_find(d, ["accessToken", "access_token"])
    if not a: raise RuntimeError("renew failed")
    return a

def main():
    res = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "tries": {}}
    try:
        at = renew()
        res["at_len"] = len(at)
        # 用已知能成功的接口验证 token 有效
        ok = call("moment.v1.SearchService/SearchMoments", {"query":"HTML","sessionId":""}, at, timeout=60)
        res["sanity"] = {"http": ok["http"], "raw": ok["raw"][:300]}
        prompt = "写一个网页，一个大红按钮点了显示Hello World，只输出完整HTML代码"
        # 纯 JSON body，无 $typeName；role 用数值；content.case 用 text
        msg_base = {"id":"", "parentId":"", "role":1,
            "blocks":[{"content":{"case":"text","value":{"content":prompt}}}],
            "scenario":"OKC"}
        bodies = {
            "plain_enum": {"chatId":"", "scenario":"OKC", "tools":[], "message":msg_base,
                           "options":{"thinking":False}},
            "plain_role_num": {"chatId":"", "scenario":"OKC", "message":{**msg_base,"role":1}},
            "no_scenario": {"chatId":"", "message":{"role":1,"blocks":[{"content":{"case":"text","value":{"content":prompt}}}]}},
            "content_case_string": {"chatId":"", "scenario":"OKC", "message":{"role":1,
                "blocks":[{"content":{"case":"text","value":{"content":prompt}}}]}, "options":{}},
        }
        for name, body in bodies.items():
            r = call("kimi.gateway.chat.v1.ChatService/Chat", body, at, timeout=150)
            res["tries"][name] = {"http": r["http"], "ct": r.get("ct_r",""), "raw": r["raw"][:2500]}
    except Exception as e:
        res["error"] = repr(e)
    try:
        d = json.load(open(OUT, encoding="utf-8"))
    except Exception:
        d = {"works": []}
    d["_probe2"] = res
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    print("done", json.dumps(res, ensure_ascii=False)[:2000])

if __name__ == "__main__":
    main()
