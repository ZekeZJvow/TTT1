import requests
import json
import urllib3
urllib3.disable_warnings()

code = '000002'

# 东方财富公告接口
url = 'https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=5&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0&stock_list=' + code
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}

print('Testing Eastmoney announcement API...')
try:
    response = requests.get(url, headers=headers, timeout=10, verify=False)
    data = response.json()
    print('Code:', data.get('code'))
    print('Message:', data.get('message'))
    if data.get('data') and data['data'].get('list'):
        print('Announcements:', len(data['data']['list']))
        for item in data['data']['list'][:3]:
            print(' ', item.get('notice_date', '')[:10], '-', item.get('title', '')[:50])
except Exception as e:
    print('Error:', e)
