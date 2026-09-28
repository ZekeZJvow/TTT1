import requests, json, urllib3
urllib3.disable_warnings()

resp = requests.get("http://localhost:5000/api/stock/603230?type=daily", timeout=15, verify=False)
data = resp.json()

if data['success']:
    klines = data['data']
    print(f"数据条数: {len(klines)}")
    
    # 找到2026-09-17的数据
    for i, item in enumerate(klines):
        if item['date'] == '2026-09-17':
            print(f"\n找到 2026-09-17:")
            print(f"  开: {item['open']}")
            print(f"  收: {item['close']}")
            print(f"  高: {item['high']}")
            print(f"  低: {item['low']}")
            
            if i > 0:
                prev = klines[i-1]
                print(f"\n前一日 {prev['date']}:")
                print(f"  收盘: {prev['close']}")
                
                change = (item['close'] - prev['close']) / prev['close'] * 100
                print(f"\n涨跌幅计算: ({item['close']} - {prev['close']}) / {prev['close']} * 100 = {change:.2f}%")
            break
    
    # 显示最近5条数据的涨跌幅
    print("\n最近5条数据的涨跌幅:")
    for i in range(max(0, len(klines)-5), len(klines)):
        item = klines[i]
        if i > 0:
            prev = klines[i-1]
            change = (item['close'] - prev['close']) / prev['close'] * 100
            print(f"  {item['date']}: 收{item['close']} 涨跌{change:.2f}%")
        else:
            print(f"  {item['date']}: 收{item['close']} (无前一日数据)")
else:
    print(f"获取失败: {data.get('error')}")
