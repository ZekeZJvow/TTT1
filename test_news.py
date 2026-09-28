import requests
import urllib3
import re
urllib3.disable_warnings()

code = '000002'
url = 'http://basic.10jqka.com.cn/' + code + '/news.html'
headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://basic.10jqka.com.cn/'}

response = requests.get(url, headers=headers, timeout=10, verify=False)
response.encoding = 'gbk'
html = response.text

# 查找新闻标题
pattern = r'target="_blank">(.*?)</a>'
matches = re.findall(pattern, html)

print('Found', len(matches), 'items')
for i, title in enumerate(matches[:8]):
    clean = re.sub(r'<.*?>', '', title).strip()
    if clean and len(clean) > 5:
        print(str(i+1) + '.', clean[:60])
