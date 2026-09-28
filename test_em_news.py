import requests
import json
import urllib3
urllib3.disable_warnings()

code = '000002'

# 东方财富股吧新闻接口
url = 'https://guba.eastmoney.com/interface/GetData.aspx?path=newslist&param=ps-5-p-1-type-1-code-' + code
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://guba.eastmoney.com/'}

print('URL:', url)
try:
    response = requests.get(url, headers=headers, timeout=10, verify=False)
    print('Status:', response.status_code)
    print('Content[:500]:', response.text[:500])
except Exception as e:
    print('Error:', e)

print()

# 尝试另一个东方财富接口
url2 = 'https://searchapi.eastmoney.com/bussiness/Web/GetCMSSearchList?type=0&pageindex=1&pagesize=5&keyword=' + code + '&name=zixun'
print('URL2:', url2)
try:
    response2 = requests.get(url2, headers=headers, timeout=10, verify=False)
    print('Status:', response2.status_code)
    print('Content[:500]:', response2.text[:500])
except Exception as e:
    print('Error:', e)
