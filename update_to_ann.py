import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 查找并替换新闻API
old_api_start = content.find("@app.route('/api/stock/<code>/news')")
old_api_end = content.find("@app.route('/api/stock/<code>')")

if old_api_start > 0 and old_api_end > old_api_start:
    new_api = """@app.route('/api/stock/<code>/news')
def get_stock_news(code):
    clean_code = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
    try:
        url = 'https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size=8&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0&stock_list=' + clean_code
        headers = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://data.eastmoney.com/'}
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        data = response.json()
        
        result = []
        if data.get('data') and data['data'].get('list'):
            for item in data['data']['list'][:8]:
                result.append({
                    'title': item.get('title', ''),
                    'date': item.get('notice_date', '')[:10] if item.get('notice_date') else '',
                    'source': '东方财富公告',
                    'url': 'https://data.eastmoney.com/notices/detail/' + clean_code + '/' + item.get('art_code', '') + '.html'
                })
        
        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

"""
    content = content[:old_api_start] + new_api + content[old_api_end:]

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done! News API updated to use Eastmoney announcements')
