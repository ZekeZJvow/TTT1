import requests, json, urllib3
urllib3.disable_warnings()

# 格式1: qfqday
url1 = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600664,day,,,60,qfq"
# 格式2: 不带qfq
url2 = "https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param=sh600664,day,,,60"
# 格式3: 日线接口
url3 = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol=sh600664&scale=240&ma=no&datalen=60"

headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.qq.com/"}

for i, url in enumerate([url1, url2], 1):
    print(f"\n=== 格式{i} ===")
    print(f"URL: {url[:80]}...")
    try:
        resp = requests.get(url, headers=headers, timeout=10, verify=False)
        data = resp.json()
        print(f"顶层keys: {list(data.keys())}")
        d = data.get("data")
        print(f"data类型: {type(d).__name__}")
        if isinstance(d, dict):
            for k in list(d.keys())[:3]:
                v = d[k]
                if isinstance(v, dict):
                    for k2 in list(v.keys())[:5]:
                        v2 = v[k2]
                        if isinstance(v2, list):
                            print(f"  {k}.{k2}: list, len={len(v2)}")
                            if len(v2) > 0:
                                print(f"    first: {v2[0]}")
                        else:
                            print(f"  {k}.{k2}: {type(v2).__name__}")
                elif isinstance(v, list):
                    print(f"  {k}: list, len={len(v)}")
                    if len(v) > 0:
                        print(f"    first: {v[0]}")
        elif isinstance(d, list):
            print(f"data是list, len={len(d)}")
            if len(d) > 0:
                print(f"  first: {d[0]}")
    except Exception as e:
        print(f"错误: {e}")

# 测试新浪接口
print("\n=== 新浪K线接口 ===")
try:
    resp3 = requests.get(url3, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"}, timeout=10, verify=False)
    text = resp3.text
    # 解析JSONP
    start = text.find('(')
    end = text.rfind(')')
    if start >= 0 and end > start:
        json_str = text[start+1:end]
        klines = json.loads(json_str)
        print(f"数据条数: {len(klines)}")
        if len(klines) > 0:
            print(f"前3条:")
            for k in klines[:3]:
                print(f"  {k}")
            print(f"后3条:")
            for k in klines[-3:]:
                print(f"  {k}")
    else:
        print(f"响应: {text[:300]}")
except Exception as e:
    print(f"错误: {e}")
