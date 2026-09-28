import requests
import json
import urllib3
urllib3.disable_warnings()

code = 'sz000002'

# 新浪财经个股新闻接口
url = 'https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=5&zhibo_id=152&tag_id=0&dire=f&dpc=1'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.sina.com.cn/'}

print('Testing Sina live feed...')
try:
    response = requests.get(url, headers=headers, timeout=10, verify=False)
    data = response.json()
    print('Status:', data.get('result', {}).get('status', {}).get('code'))
    if data.get('result', {}).get('data'):
        feed = data['result']['data'].get('feed', {})
        print('Feed keys:', list(feed.keys()) if feed else 'empty')
except Exception as e:
    print('Error:', e)

print()

# 尝试新浪7x24小时新闻
url2 = 'https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=5&zhibo_id=152&tag_id=0&dire=f&dpc=1'
print('Testing Sina 7x24...')
try:
    response2 = requests.get(url2, headers=headers, timeout=10, verify=False)
    print('Status code:', response2.status_code)
    print('Content[:300]:', response2.text[:300])
except Exception as e:
    print('Error:', e)
