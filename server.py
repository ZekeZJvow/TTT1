# -*- coding: utf-8 -*-
"""
A股人气榜查询 - 后端代理服务器
"""

import os
import json
import time
import hashlib
import requests
import urllib3
from datetime import datetime, timedelta
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
from stock_data import get_stock_name, STOCK_NAMES

# 禁用SSL警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# 内存缓存
cache = {}
CACHE_TTL = 600  # 10分钟

# ==================== 交易日历 ====================

def get_last_trading_day(date=None):
    """获取最近的已完成交易日"""
    if date is None:
        date = datetime.now()
    
    for i in range(30):
        check_date = date - timedelta(days=i)
        if check_date.weekday() >= 5:
            continue
        return check_date.strftime('%Y-%m-%d')
    
    return (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')


def get_data_trading_day():
    """根据当前时刻确定数据所属交易日"""
    now = datetime.now()
    hour = now.hour
    minute = now.minute
    is_trading_day = now.weekday() < 5
    
    if not is_trading_day:
        return get_last_trading_day(now), "今日为节假日/非交易日，已回溯至最近交易日"
    
    current_minutes = hour * 60 + minute
    
    if current_minutes < 570:
        return get_last_trading_day(now - timedelta(days=1)), "今日未开盘，以下为上一交易日收盘数据"
    elif current_minutes < 900:
        return get_last_trading_day(now - timedelta(days=1)), "今日盘中，以下为上一交易日收盘数据"
    else:
        return now.strftime('%Y-%m-%d'), ""


# ==================== 缓存 ====================

def get_cache_key(url):
    return hashlib.md5(url.encode()).hexdigest()

def get_cached_data(key):
    if key in cache:
        data, timestamp = cache[key]
        if time.time() - timestamp < CACHE_TTL:
            return data
        else:
            del cache[key]
    return None

def set_cached_data(key, data):
    cache[key] = (data, time.time())


# ==================== 数据获取 ====================

def fetch_ths_hotlist():
    """获取同花顺人气榜数据"""
    url = "https://dq.10jqka.com.cn/fuyao/hot_list_data/out/hot_list/v1/stock?stock_type=a&type=hour&list_type=normal"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.10jqka.com.cn/',
        'Accept': 'application/json, text/plain, */*',
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=15, verify=False)
        response.raise_for_status()
        data = response.json()
        
        # 同花顺返回结构: {"status_code": 0, "data": {"stock_list": [...]}, "status_msg": "success"}
        stock_list = data.get('data', {}).get('stock_list', [])
        
        if stock_list and len(stock_list) > 0:
            return stock_list[:30], None
        else:
            return None, f"同花顺接口返回数据异常: {data.get('status_msg', '未知错误')}"
    except Exception as e:
        return None, f"同花顺接口请求失败: {str(e)}"


def fetch_eastmoney_hotlist():
    """获取东方财富热股榜"""
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Content-Type': 'application/json',
    }
    payload = {
        "appId": "appId01",
        "globalId": "786e4c21-70dc-435a-93bb-38",
        "marketType": "",
        "pageNo": 1,
        "pageSize": 30
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15, verify=False)
        response.raise_for_status()
        data = response.json()
        
        if 'data' in data and len(data['data']) > 0:
            return data['data'], None
        else:
            return None, "东方财富接口返回数据异常"
    except Exception as e:
        return None, f"东方财富接口请求失败: {str(e)}"


def fetch_eastmoney_batch_quote(codes):
    """批量获取东方财富实时行情（含名称和行业）"""
    secids = []
    for code in codes:
        clean = code.replace('SH','').replace('SZ','').replace('BJ','')
        if clean.startswith('6'):
            secids.append(f"1.{clean}")
        else:
            secids.append(f"0.{clean}")
    
    secids_str = ','.join(secids)
    url = f"https://push2.eastmoney.com/api/qt/ulist.np/get?secids={secids_str}&fields=f12,f14,f100&fltt=2"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://www.eastmoney.com/'
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10, verify=False)
        response.raise_for_status()
        data = response.json()
        
        result = {}
        if data and data.get('data') and data['data'].get('diff'):
            for item in data['data']['diff']:
                code = item.get('f12', '')
                name = item.get('f14', '')
                industry = item.get('f100', '')
                if code:
                    result[code] = {'name': name, 'industry': industry}
        return result, None
    except Exception as e:
        return {}, str(e)


# ==================== 数据处理 ====================

def get_secid_prefix(code):
    clean_code = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
    if clean_code.startswith('6'):
        return f"1.{clean_code}"
    else:
        return f"0.{clean_code}"


def process_consecutive_boards(popularity_tag):
    if not popularity_tag:
        return "无"
    
    import re
    match = re.search(r'(\d+)天(\d+)板', popularity_tag)
    if match:
        days = match.group(1)
        boards = match.group(2)
        return f"{boards}连板（{days}天{boards}板）"
    
    if '首板' in popularity_tag:
        return "首板（当日）"
    
    return "无"


def get_tier(order):
    if order <= 10:
        return "第一梯队·人气Top10"
    elif order <= 20:
        return "第二梯队·人气Top20"
    else:
        return "第三梯队·人气Top30"


def get_anomaly_analysis(item):
    if item.get('analyse_title'):
        return item['analyse_title'][:30]
    
    if item.get('analyse'):
        text = item['analyse'].replace('\n', ' ').strip()
        return text[:30]
    
    if item.get('topic') and item['topic'].get('title'):
        return item['topic']['title'][:30]
    
    return "无"


def process_ths_data(stock_list, quote_data):
    result = []
    
    for item in stock_list:
        code = item.get('code', '')
        clean_code = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
        name = item.get('name', '')
        order = item.get('order', 0)
        popularity_tag = item.get('tag', {}).get('popularity_tag', '') if item.get('tag') else ''
        
        # 从行情数据补充名称和行业
        quote = quote_data.get(clean_code, {})
        if not name and quote.get('name'):
            name = quote['name']
        elif not name:
            name = get_stock_name(clean_code)
        
        # 从 concept_tag 提取概念标签
        concept_tags = item.get('tag', {}).get('concept_tag', []) if item.get('tag') else []
        if concept_tags and isinstance(concept_tags, list):
            concept_str = ', '.join(concept_tags[:3])  # 最多取3个
        else:
            concept_str = '未获取'
        
        # 获取涨跌幅
        rise_and_fall = item.get('rise_and_fall', 0)
        
        result.append({
            'rank': order,
            'name': name or clean_code,
            'code': code,
            'rise_and_fall': rise_and_fall,
            'consecutive_boards': process_consecutive_boards(popularity_tag),
            'tier': get_tier(order),
            'concept_tag': concept_str,
            'anomaly_analysis': get_anomaly_analysis(item),
            'is_hot': bool(popularity_tag)
        })
    
    return result


def process_eastmoney_data(data_list, quote_data):
    result = []
    
    for i, item in enumerate(data_list[:30], 1):
        code = item.get('sc', '')
        clean_code = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
        
        # 从行情数据获取名称
        quote = quote_data.get(clean_code, {})
        name = quote.get('name', '') or get_stock_name(clean_code) or clean_code
        
        result.append({
            'rank': i,
            'name': name,
            'code': code,
            'rise_and_fall': 0,
            'consecutive_boards': "无",
            'tier': get_tier(i),
            'concept_tag': "降级模式，无数据",
            'anomaly_analysis': "无",
            'is_hot': False
        })
    
    return result


# ==================== API路由 ====================

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/api/hotlist')
def get_hotlist():
    cache_key = get_cache_key('hotlist')
    cached = get_cached_data(cache_key)
    if cached:
        return jsonify(cached)
    
    trading_day, message = get_data_trading_day()
    
    # 尝试获取同花顺数据
    stock_list, error = fetch_ths_hotlist()
    source = "同花顺人气榜"
    degraded = False
    
    if error or not stock_list:
        # 降级到东方财富
        eastmoney_data, error2 = fetch_eastmoney_hotlist()
        if eastmoney_data:
            codes = [item.get('sc', '') for item in eastmoney_data[:30]]
            quote_data, _ = fetch_eastmoney_batch_quote(codes)
            result_list = process_eastmoney_data(eastmoney_data, quote_data)
            source = "东方财富热股榜"
            degraded = True
        else:
            return jsonify({
                'success': False,
                'error': f"数据获取失败: {error or error2}"
            }), 500
    else:
        codes = [item.get('code', '') for item in stock_list[:30]]
        quote_data, _ = fetch_eastmoney_batch_quote(codes)
        result_list = process_ths_data(stock_list, quote_data)
    
    # 生成总结
    hot_count = sum(1 for item in result_list if item['is_hot'])
    total_count = len(result_list)
    
    if hot_count > total_count * 0.6:
        summary_hot = "涨停股占据多数"
    elif hot_count > total_count * 0.3:
        summary_hot = "涨停股与非涨停股参半"
    else:
        summary_hot = "多数为非涨停股"
    
    # 从概念标签提取主线方向
    all_concepts = []
    for item in result_list:
        if item['concept_tag'] and item['concept_tag'] != '未获取' and item['concept_tag'] != '降级模式，无数据':
            concepts = [c.strip() for c in item['concept_tag'].split(',')]
            all_concepts.extend(concepts)
    
    if all_concepts:
        from collections import Counter
        top_concept = Counter(all_concepts).most_common(1)[0][0]
        summary_main = f"人气主线集中在{top_concept}方向"
    else:
        summary_main = "暂无明显主线方向"
    
    collection_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    response_data = {
        'success': True,
        'trading_day': trading_day,
        'message': message,
        'source': source,
        'degraded': degraded,
        'collection_time': collection_time,
        'data': result_list,
        'summary': {
            'main_direction': summary_main,
            'hot_proportion': summary_hot
        }
    }
    
    set_cached_data(cache_key, response_data)
    return jsonify(response_data)



# ==================== 图表数据API ====================

def get_secid(code):
    """将股票代码转换为东方财富secid格式"""
    clean = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
    if clean.startswith('6'):
        return f"1.{clean}"
    else:
        return f"0.{clean}"




@app.route('/api/stock/<code>/news')
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

@app.route('/api/stock/<code>')
def get_stock_chart(code):
    """获取个股分时或日K数据"""
    chart_type = request.args.get('type', 'minute')
    clean_code = code.replace('SH', '').replace('SZ', '').replace('BJ', '')
    
    # 判断市场前缀
    if clean_code.startswith('6'):
        market_code = f"sh{clean_code}"
    else:
        market_code = f"sz{clean_code}"
    
    try:
        if chart_type == 'minute':
            # 使用腾讯接口获取分时数据
            url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={market_code}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer': 'https://finance.qq.com/'
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            data = response.json()
            
            # 腾讯返回结构: data -> sh600664 -> data -> data (数组)
            stock_data = data.get('data', {}).get(market_code, {})
            minute_data = stock_data.get('data', {}).get('data', [])
            
            if minute_data:
                result = []
                for item in minute_data:
                    parts = item.split(' ')
                    if len(parts) >= 3:
                        time_str = parts[0]
                        # 格式化时间 HHMM -> HH:MM
                        if len(time_str) == 4:
                            time_str = time_str[:2] + ':' + time_str[2:]
                        result.append({
                            'time': time_str,
                            'price': float(parts[1]) if parts[1] else 0,
                            'volume': int(parts[2]) if parts[2] else 0
                        })
                # 获取前一日收盘价（使用日K接口）
                prev_close = 0
                try:
                    kline_url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={market_code}&scale=240&ma=no&datalen=2"
                    kline_resp = requests.get(kline_url, headers=headers, timeout=10, verify=False)
                    kline_text = kline_resp.text
                    kline_start = kline_text.find('(')
                    kline_end = kline_text.rfind(')')
                    if kline_start >= 0 and kline_end > kline_start:
                        import json as json_lib
                        klines = json_lib.loads(kline_text[kline_start+1:kline_end])
                        if len(klines) >= 2:
                            prev_close = float(klines[-2].get('close', 0))
                except:
                    pass
                
                return jsonify({'success': True, 'data': result, 'prev_close': prev_close})
            else:
                return jsonify({'success': False, 'error': '无分时数据'})
                
        else:
            # 使用新浪K线接口（更稳定）
            url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var/CN_MarketDataService.getKLineData?symbol={market_code}&scale=240&ma=no&datalen=60"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Referer': 'https://finance.sina.com.cn/'
            }
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            text = response.text
            
            # 解析JSONP响应
            start = text.find('(')
            end = text.rfind(')')
            
            if start >= 0 and end > start:
                import json as json_lib
                kline_data = json_lib.loads(text[start+1:end])
                
                if kline_data:
                    result = []
                    for item in kline_data:
                        result.append({
                            'date': item.get('day', ''),
                            'open': float(item.get('open', 0)),
                            'close': float(item.get('close', 0)),
                            'high': float(item.get('high', 0)),
                            'low': float(item.get('low', 0)),
                            'volume': int(item.get('volume', 0))
                        })
                    return jsonify({'success': True, 'data': result})
            
            return jsonify({'success': False, 'error': '无日K数据'})
                
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


if __name__ == '__main__':
    print("=" * 50)
    print("A股人气榜查询服务已启动")
    print("访问地址: http://localhost:5000")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5000, debug=True)







