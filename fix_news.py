import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

target = '@' + 'app.route' + chr(40) + "'/api/stock/<code>'" + chr(41)
idx = content.find(target)

news_code = chr(10) + '@' + 'app.route' + chr(40) + "'/api/stock/<code>/news'" + chr(41) + chr(10)
news_code += 'def get_stock_news(code):' + chr(10)
news_code += '    clean_code = code.replace("SH", "").replace("SZ", "").replace("BJ", "")' + chr(10)
news_code += '    try:' + chr(10)
news_code += '        url = "https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22" + clean_code + "%22%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%2C%22client%22%3A%22web%22%2C%22clientType%22%3A%22web%22%2C%22clientVersion%22%3A%22curr%22%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A10%2C%22preTag%22%3A%22%22%2C%22postTag%22%3A%22%22%7D%7D%7D"' + chr(10)
news_code += '        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://so.eastmoney.com/"}' + chr(10)
news_code += '        response = requests.get(url, headers=headers, timeout=10, verify=False)' + chr(10)
news_code += '        text = response.text' + chr(10)
news_code += '        start = text.find("(")' + chr(10)
news_code += '        end = text.rfind(")")' + chr(10)
news_code += '        if start >= 0 and end > start:' + chr(10)
news_code += '            import json as json_lib' + chr(10)
news_code += '            data = json_lib.loads(text[start+1:end])' + chr(10)
news_code += "            articles = data.get('result', {}).get('cmsArticleWebOld', {}).get('list', [])" + chr(10)
news_code += '            result = []' + chr(10)
news_code += '            for a in articles[:8]:' + chr(10)
news_code += "                result.append({'title': a.get('title', '').replace('<em>', '').replace('</em>', ''), 'date': a.get('date', ''), 'source': a.get('mediaName', ''), 'url': a.get('url', '')})" + chr(10)
news_code += "            return jsonify({'success': True, 'data': result})" + chr(10)
news_code += "        return jsonify({'success': False, 'error': 'no data'})" + chr(10)
news_code += '    except Exception as e:' + chr(10)
news_code += "        return jsonify({'success': False, 'error': str(e)})" + chr(10) * 2

content = content[:idx] + news_code + content[idx:]
with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done!')
