import requests, json
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36","Accept-Language":"es-PE,es;q=0.9","Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
P="https://www.eventbrite.com.pe/d/peru--lima/all-events/"
def t(n,f):
    try:
        r=f(); b=r.text
        print(f"{n}: {r.status_code} {len(b)//1000}KB sd={'__SERVER_DATA__' in b} ev={b.count('eventbrite.com.pe/e/')+b.count('eventbrite.com/e/')} | {b[:120]!r}")
    except Exception as e: print(n,"ERR",e)
t("base",lambda:requests.get(P,headers=UA,timeout=25))
t("com",lambda:requests.get("https://www.eventbrite.com/d/peru--lima/all-events/",headers=UA,timeout=25))
t("robots",lambda:requests.get("https://www.eventbrite.com.pe/robots.txt",headers=UA,timeout=25))
t("api_search",lambda:requests.post("https://www.eventbrite.com.pe/api/v3/destination/search/",headers={**UA,"Content-Type":"application/json","Referer":P},json={"event_search":{"places":["85682345"],"page_size":20}},timeout=25))
t("jina",lambda:requests.get("https://r.jina.ai/"+P,headers={"X-Return-Format":"html"},timeout=60))
t("jina_md",lambda:requests.get("https://r.jina.ai/"+P,timeout=60))
