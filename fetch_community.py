#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断：SearchMoments 返回结构 + 前端同款调用能否拿到数据。只读，不改 community.json。
结果 print 到 stdout，从 workflow 日志读取。"""
import os, sys, json, time
import urllib.request, urllib.error

BASE = "https://www.kimi.com/apiv2"
AUTH = "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"
RT = os.environ.get("KIMI_REFRESH_TOKEN", "").strip()
HEAD = {"Content-Type":"application/json","Accept":"application/json",
        "x-msh-platform":"web","x-msh-version":"2.1.0",
        "R-Timezone":"Asia/Shanghai","X-Language":"zh-CN"}

def deep_find(o,names,d=0):
    if d>8 or not o or not isinstance(o,(dict,list)): return None
    if isinstance(o,list):
        for x in o:
            r=deep_find(x,names,d+1)
            if r: return r
        return None
    for k in names:
        if k in o and isinstance(o[k],str) and o[k]: return o[k]
    for v in o.values():
        r=deep_find(v,names,d+1)
        if r: return r
    return None

def renew():
    req=urllib.request.Request(AUTH,data=json.dumps({"refreshToken":RT}).encode(),headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=30) as r: d=json.loads(r.read())
    return deep_find(d,["accessToken","access_token"])

def call(at,path,payload):
    h=dict(HEAD,Authorization="Bearer "+at)
    req=urllib.request.Request(BASE+"/"+path,data=json.dumps(payload).encode(),headers=h,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=30) as r: return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:
        try: return e.code,json.loads(e.read())
        except: return e.code,None

def main():
    at=renew()
    print("AT_LEN",len(at))
    # 1. 单次调用（抓取脚本同款）
    st,d=call(at,"moment.v1.SearchService/SearchMoments",{"query":"游戏","sessionId":"diag-"+str(int(time.time()*1000))})
    print("SINGLE_HTTP",st)
    if d:
        print("TOP_KEYS",list(d.keys())[:20])
        ms=d.get("moments") or d.get("relatedMoments") or []
        print("MOMENTS_LEN",len(ms) if isinstance(ms,list) else "not-list")
        print("NEXT_TOKEN",d.get("_nextPageToken") or d.get("nextPageToken"))
        if ms:
            x=ms[0]
            print("MOMENT0_KEYS",list(x.keys()) if isinstance(x,dict) else type(x))
            m=x.get("moment",x)
            if isinstance(m,dict):
                print("M0_id",m.get("id"))
                print("M0_content_keys",list((m.get("content") or {}).keys())[:15] if isinstance(m.get("content"),dict) else m.get("content"))
                print("M0_stat",m.get("stat"))
                print("M0_author",list((m.get("author") or {}).keys()))
    # 2. 前端同款：同毫秒 sessionId 并发
    sid="live-"+str(int(time.time()*1000))
    results=[]
    for q in ["游戏","HTML","作品"]:
        st2,d2=call(at,"moment.v1.SearchService/SearchMoments",{"query":q,"sessionId":sid})
        n=len((d2 or {}).get("moments") or []) if d2 else -1
        results.append((q,st2,n))
    print("SAME_SID_CONCURRENT",results)
    # 3. 不同 sessionId 顺序
    results2=[]
    for q in ["游戏","HTML","作品"]:
        st3,d3=call(at,"moment.v1.SearchService/SearchMoments",{"query":q,"sessionId":"sep-"+str(int(time.time()*1000))+q})
        n=len((d3 or {}).get("moments") or []) if d3 else -1
        results2.append((q,st3,n))
    print("DIFF_SID",results2)

if __name__=="__main__":
    main()
