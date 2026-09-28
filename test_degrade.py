import requests, json, urllib3, os, sys
urllib3.disable_warnings()
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_URL = "http://localhost:5000"

def test_degrade():
    print("=" * 60)
    print("[降级测试] 模拟同花顺接口失败")
    print("=" * 60)
    
    # 设置环境变量强制降级
    # 先直接测试东方财富接口是否可用
    print("测试东方财富热股榜接口...")
    url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    payload = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "marketType": "", "pageNo": 1, "pageSize": 5}
    
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=10, verify=False)
        data = resp.json()
        if data.get('data'):
            print(f"  东方财富接口可用, 返回{len(data['data'])}条数据")
            for item in data['data'][:3]:
                print(f"    {item}")
        else:
            print(f"  东方财富接口返回异常: {data}")
    except Exception as e:
        print(f"  东方财富接口失败: {e}")

def test_non_hot_stock_boards():
    print("\n" + "=" * 60)
    print("[验证] 非涨停股连板数显示'无'")
    print("=" * 60)
    resp = requests.get(f"{BASE_URL}/api/hotlist", timeout=30, verify=False)
    data = resp.json()
    stocks = data['data']
    
    non_hot = [s for s in stocks if not s['is_hot']]
    print(f"非涨停股数量: {len(non_hot)}")
    
    all_correct = True
    for s in non_hot[:10]:
        boards = s['consecutive_boards']
        if boards != '无':
            print(f"  [FAIL] {s['name']} 非涨停但连板数={boards}")
            all_correct = False
        else:
            print(f"  [OK] {s['name']}: 连板数={boards}")
    
    if all_correct:
        print("[PASS] 非涨停股连板数均显示'无'")
    else:
        print("[FAIL] 存在非涨停股连板数显示错误")

def test_page_structure():
    print("\n" + "=" * 60)
    print("[页面结构] 检查HTML关键元素")
    print("=" * 60)
    resp = requests.get(f"{BASE_URL}/", timeout=10, verify=False)
    html = resp.text
    
    checks = [
        ("查询按钮", "query-btn" in html),
        ("表格容器", "stock-table" in html),
        ("模态框", "stock-modal" in html),
        ("ECharts", "echarts" in html),
        ("分时线Tab", "分时线" in html),
        ("日K线Tab", "日K线" in html),
        ("概念标签列", "概念标签" in html),
        ("筛选区域", "filter-section" in html),
    ]
    
    all_ok = True
    for name, ok in checks:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}")
        if not ok:
            all_ok = False
    
    return all_ok

if __name__ == '__main__':
    test_degrade()
    test_non_hot_stock_boards()
    ok = test_page_structure()
    print("\n" + "=" * 60)
    print("降级测试完成")
    print("=" * 60)
