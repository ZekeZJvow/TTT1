with open("server.py", "r", encoding="utf-8") as f:
    server = f.read()

# 找到分时数据返回的代码，添加前一日收盘价
old_return = """                return jsonify({'success': True, 'data': result})
            else:
                return jsonify({'success': False, 'error': '无分时数据'})"""

new_return = """                # 获取前一日收盘价（使用日K接口）
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
                return jsonify({'success': False, 'error': '无分时数据'})"""

server = server.replace(old_return, new_return)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(server)

print("server.py updated")
