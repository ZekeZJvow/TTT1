import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 删除旧的新闻API
old_start = content.find("@app.route('/api/stock/<code>/news')")
if old_start > 0:
    # 找到下一个路由
    next_route = content.find("@app.route('/api/stock/<code>')", old_start)
    if next_route > 0:
        content = content[:old_start] + content[next_route:]

# 新的新闻API（使用同花顺）
news_api = """
@app.route('/api/stock/<code>/news')
def get_stock_news(code):
    clean_code = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
    try:
        import re
        url = 'http://basic.10jqka.com.cn/' + clean_code + '/news.html'
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'http://basic.10jqka.com.cn/'}
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        response.encoding = 'gbk'
        html = response.text
        
        # 提取新闻列表
        items = re.findall(r'<li>.*?<a href="(.*?)"[^>]*>(.*?)</a>.*?</li>', html, re.DOTALL)
        
        result = []
        for link, title in items[:8]:
            clean_title = re.sub(r'<.*?>', '', title).strip()
            if clean_title and len(clean_title) > 5:
                result.append({
                    'title': clean_title,
                    'date': '',
                    'source': '同花顺',
                    'url': link if link.startswith('http') else 'http://basic.10jqka.com.cn' + link
                })
        
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

"""

target = "@app.route('/api/stock/<code>')"
idx = content.find(target)
content = content[:idx] + news_api + content[idx:]

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done! News API updated to use 10jqka')
