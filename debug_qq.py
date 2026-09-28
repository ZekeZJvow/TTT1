import requests
import json
import urllib3
urllib3.disable_warnings()

code = '000002'
url = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/news/info/search?stock=' + code + '&type=0&page=1&perpage=5'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://stockapp.finance.qq.com/'}

response = requests.get(url, headers=headers, timeout=10, verify=False)
data = response.json()

print('code:', data.get('code'))
print('msg:', data.get('msg'))
print('data type:', type(data.get('data')))
if data.get('data'):
    print('data:', json.dumps(data['data'], ensure_ascii=False)[:500])
