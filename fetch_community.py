#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""诊断2：验证 _nextPageToken 翻页能否拿到第二页。只读 print，不改 community.json。"""
import os, json, time, urllib.request, urllib.error
BASE="https://www.kimi.com/apiv2"
AUTH="https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"
RT=os.environ.get("KIMI_REFRESH_TOKEN","").strip()
HEAD={"Content-Type":"application/json","Accept":"application/json","x-msh-platform":"web","x-msh-version":"2.1.0","R-Timezone":"Asia/Shanghai","X-Language":"zh-CN"}
def deep_find(o,names,d=0):
    if d>8 or not o or not isinstance(o,(dict,list)):return None
    if isinstance(o,list):
        for x in o:
            r=deep_find(x,names,d+1)
            if r:return r
        return None
    for k in names:
        if k in o and isinstance(o[k],str) and o[k]:return o[k]
    for v in o.values():
        r=deep_find(v,names,d+1)
        if r:return r
    return None
def renew():
    req=urllib.request.Request(AUTH,data=json.dumps({"refreshToken":RT}).encode(),headers={"Content-Type":"application/json"},method="POST")
    with urllib.request.urlopen(req,timeout=30) as r:d=json.loads(r.read())
    return deep_find(d,["accessToken","access_token"])
def call(at,payload):
    h=dict(HEAD,Authorization="Bearer "+at)
    req=urllib.request.Request(BASE+"/moment.v1.SearchService/SearchMoments",data=json.dumps(payload).encode(),headers=h,method="POST")
    try:
        with urllib.request.urlopen(req,timeout=30) as r:return r.status,json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:return e.code,json.loads(e.read())
        except:return e.code,None
def main():
    at=renew()
    q="游戏"; sid="feed-test-"+str(int(time.time()*1000))
    tok=""; ids=[]
    for page in range(1,6):
        body={"query":q,"sessionId":sid}
        if tok:body["_nextPageToken"]=tok
        st,d=call(at,body)
        if not d: print("PAGE",page,"HTTP",st,"no data");break
        ms=d.get("moments") or []
        page_ids=[str(x.get("moment",{}).get("id","")) for x in ms]
        new=[i for i in page_ids if i and i not in ids]
        ids+=new
        tok=d.get("nextPageToken") or ""
        print("PAGE",page,"HTTP",st,"got",len(ms),"new",len(new),"tok_len",len(str(tok)))
        if not tok: print("NO_MORE_TOKEN");break
        time.sleep(0.6)
    print("TOTAL_UNIQUE",len(ids))
if __name__=="__main__":main()
