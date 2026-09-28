import requests
import urllib3
urllib3.disable_warnings()

url = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?stock_type=a&type=hour&list_type=normal"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.10jqka.com.cn/",
    "Accept": "application/json, text/plain, */*",
}

try:
    response = requests.get(url, headers=headers, timeout=15, verify=False)
    print(f"状态码: {response.status_code}")
    data = response.json()
    print(f"返回结构: {list(data.keys())}")
    if "stock_list" in data:
        print(f"数据条数: {len(data['stock_list'])}")
        print(f"第一条: {data['stock_list'][0].get('name')} ({data['stock_list'][0].get('code')})")
    else:
        print(f"返回内容: {str(data)[:200]}")
except Exception as e:
    print(f"错误类型: {type(e).__name__}")
    print(f"错误信息: {e}")
