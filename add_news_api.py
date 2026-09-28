with open("server.py", "r", encoding="utf-8") as f:
    server = f.read()

# 在get_stock_chart函数之前添加新闻接口
news_api = """

@app.route('/api/stock/<code>/news')
def get_stock_news(code):
    """获取个股近期新闻/公告"""
    clean_code = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
    
    # 判断市场
    if clean_code.startswith('6'):
        market_code = f"sh{clean_code}"
        secid = f"1.{clean_code}"
    else:
        market_code = f"sz{clean_code}"
        secid = f"0.{clean_code}"
    
    try:
        # 使用东方财富新闻接口
        url = f"https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery&param=%7B%22uid%22%3A%22%22%2C%22keyword%22%3A%22{clean_code}%22%2C%22type%22%3A%5B%22cmsArticleWebOld%22%5D%2C%22client%22%3A%22web%22%2C%22clientType%22%3A%22web%22%2C%22clientVersion%22%3A%22curr%22%2C%22param%22%3A%7B%22cmsArticleWebOld%22%3A%7B%22searchScope%22%3A%22default%22%2C%22sort%22%3A%22default%22%2C%22pageIndex%22%3A1%2C%22pageSize%22%3A10%2C%22preTag%22%3A%22%22%2C%22postTag%22%3A%22%22%7D%7D%7D"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://so.eastmoney.com/'
        }
        
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        text = response.text
        
        # 解析JSONP
        start = text.find('(')
        end = text.rfind(')')
        
        if start >= 0 and end > start:
            import json as json_lib
            data = json_lib.loads(text[start+1:end])
            
            articles = data.get('result', {}).get('cmsArticleWebOld', {}).get('list', [])
            
            result = []
            for article in articles[:8]:
                result.append({
                    'title': article.get('title', '').replace('<em>', '').replace('</em>', ''),
                    'date': article.get('date', ''),
                    'source': article.get('mediaName', ''),
                    'url': article.get('url', '')
                })
            
            return jsonify({'success': True, 'data': result})
        
        return jsonify({'success': False, 'error': '获取新闻失败'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

"""

# 在get_stock_chart之前插入
server = server.replace("@app.route('/api/stock/<code>')", news_api + "@app.route('/api/stock/<code>')")

with open("server.py", "w", encoding="utf-8") as f:
    f.write(server)

print("server.py news API added")
