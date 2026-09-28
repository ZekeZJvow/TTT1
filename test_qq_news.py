import requests
import json
import urllib3
urllib3.disable_warnings()

code = '000002'

# 腾讯财经个股新闻接口
url = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/news/info/search?stock=' + code + '&type=0&page=1&perpage=5'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://stockapp.finance.qq.com/'}

print('URL:', url)
try:
    response = requests.get(url, headers=headers, timeout=10, verify=False)
    data = response.json()
    print('Status:', response.status_code)
    print('Keys:', list(data.keys()))
    if data.get('data'):
        print('Data keys:', list(data['data'].keys()))
        if data['data'].get('list'):
            print('News count:', len(data['data']['list']))
            for item in data['data']['list'][:3]:
                print(' ', item.get('time', ''), '-', item.get('title', '')[:50])
except Exception as e:
    print('Error:', e)

# 备选：直接从HTML提取
print()
print('Trying alternative...')
url2 = 'https://stock.finance.qq.com/' + code + '/news'
try:
    response2 = requests.get(url2, headers=headers, timeout=10, verify=False)
    print('Status:', response2.status_code)
except Exception as e:
    print('Error:', e)
