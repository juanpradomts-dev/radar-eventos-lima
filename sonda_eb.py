import requests, json, secrets
UA={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128 Safari/537.36","Accept-Language":"es-PE,es;q=0.9"}
tok=secrets.token_hex(16)
for place in ("421186805","85675909"):
    body={"event_search":{"places":[place],"dates":"current_future","page":1,"page_size":50,"q":"","online_events_only":False},
          "expand.destination_event":["primary_venue","image","ticket_availability","primary_organizer"]}
    r=requests.post("https://www.eventbrite.com.pe/api/v3/destination/search/",
        headers={**UA,"Content-Type":"application/json","X-CSRFToken":tok,"Referer":"https://www.eventbrite.com.pe/d/peru--lima/all-events/"},
        cookies={"csrftoken":tok},data=json.dumps(body),timeout=25)
    try:
        j=r.json(); ev=(j.get("events") or {}); res=ev.get("results") or []
        print(place,r.status_code,len(res),ev.get("pagination"),[x.get("name") for x in res[:3]], list(res[0].keys())[:40] if res else str(j)[:200])
    except Exception as e: print(place,r.status_code,r.text[:200])
