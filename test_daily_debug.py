import requests, json, urllib3
urllib3.disable_warnings()

url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600664,day,,60,qfq"
headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.qq.com/"}
resp = requests.get(url, headers=headers, timeout=15, verify=False)
data = resp.json()

print("顶层keys:", list(data.keys()))
d = data.get("data")
print("data类型:", type(d).__name__)

if isinstance(d, dict):
    for k in d.keys():
        v = d[k]
        print(f"  {k}: type={type(v).__name__}")
        if isinstance(v, dict):
            for k2 in v.keys():
                v2 = v[k2]
                tname = type(v2).__name__
                if isinstance(v2, list):
                    print(f"    {k2}: list, len={len(v2)}")
                    if len(v2) > 0:
                        print(f"      first: {v2[0]}")
                else:
                    print(f"    {k2}: {tname}")
        elif isinstance(v, list):
            print(f"    list, len={len(v)}")
            if len(v) > 0:
                print(f"      first: {v[0]}")
elif isinstance(d, list):
    print("data是list, len=", len(d))
    if len(d) > 0:
        print("  first:", d[0])
        if isinstance(d[0], list):
            print("  first item len:", len(d[0]))
        elif isinstance(d[0], dict):
            print("  first item keys:", list(d[0].keys()))
