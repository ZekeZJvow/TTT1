import requests
import urllib3
import re
import json
urllib3.disable_warnings()

code = '000002'
url = 'http://basic.10jqka.com.cn/' + code + '/news.html'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://basic.10jqka.com.cn/'}

response = requests.get(url, headers=headers, timeout=10, verify=False)
response.encoding = 'gbk'
html = response.text

print('HTML length:', len(html))

# 尝试不同的正则表达式
pattern1 = r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>'
matches1 = re.findall(pattern1, html)
print('Pattern1 matches:', len(matches1))
for i, (link, title) in enumerate(matches1[:5]):
    if len(title.strip()) > 5:
        print(f'  {i+1}. {title.strip()[:50]}')

# 直接输出HTML的一部分看看结构
print()
print('HTML snippet:')
print(html[5000:6000])
