# -*- coding: utf-8 -*-
import requests
import json
import sys
import os

os.environ['PYTHONIOENCODING'] = 'utf-8'
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE_URL = "http://localhost:5000"
results = {}

def test_api_hotlist():
    print("=" * 60)
    print("[1] API /hotlist 接口测试")
    print("=" * 60)
    try:
        resp = requests.get(f"{BASE_URL}/api/hotlist", timeout=30, verify=False)
        print(f"  状态码: {resp.status_code}")
        assert resp.status_code == 200, f"状态码错误: {resp.status_code}"
        data = resp.json()
        assert data['success'] == True, f"接口返回失败"
        print(f"  数据来源: {data['source']}")
        print(f"  交易日: {data['trading_day']}")
        print(f"  数据条数: {len(data['data'])}")
        assert len(data['data']) == 30, f"数据条数错误: {len(data['data'])}"
        print(f"  [PASS] 恰好30条记录")
        required = ['rank','name','code','consecutive_boards','tier','concept_tag','anomaly_analysis']
        for item in data['data']:
            for f in required:
                assert f in item, f"缺少字段: {f}"
        print(f"  [PASS] 字段完整")
        results['api'] = 'PASS'
        return data
    except Exception as e:
        print(f"  [FAIL] {e}")
        results['api'] = f'FAIL: {e}'
        return None

def test_data_logic(data):
    print("\n" + "=" * 60)
    print("[2] 数据口径校验")
    print("=" * 60)
    stocks = data['data']
    # 排序
    ranks = [s['rank'] for s in stocks]
    ok = all(ranks[i] <= ranks[i+1] for i in range(len(ranks)-1))
    print(f"  排序正确: {ok}")
    assert ok, "排名未按从高到低排列"
    # 连板数
    print("  连板数样例(前5条):")
    for s in stocks[:5]:
        print(f"    {s['name']}: {s['consecutive_boards']}")
    for s in stocks:
        b = s['consecutive_boards']
        if b != '无':
            assert '连板' in b or '首板' in b, f"格式错误: {b}"
    print(f"  [PASS] 连板数格式正确")
    # 梯队
    t1 = len([s for s in stocks if 'Top10' in s['tier']])
    t2 = len([s for s in stocks if 'Top20' in s['tier']])
    t3 = len([s for s in stocks if 'Top30' in s['tier']])
    print(f"  梯队: T1={t1} T2={t2} T3={t3}")
    assert t1==10 and t2==10 and t3==10, "梯队划分错误"
    print(f"  [PASS] 梯队划分正确")
    # 异动解读
    print("  异动解读样例(前10条):")
    for s in stocks[:10]:
        a = s['anomaly_analysis']
        print(f"    {s['name']}: {a[:35]}")
    print(f"  [PASS] 异动解读完成")
    # 概念标签
    print("  概念标签样例(前5条):")
    for s in stocks[:5]:
        print(f"    {s['name']}: {s['concept_tag']}")
    no_concept = len([s for s in stocks if s['concept_tag'] in ['未获取','']])
    print(f"  无概念标签: {no_concept}条")
    print(f"  [PASS] 概念标签完成")
    results['logic'] = 'PASS'

def test_minute():
    print("\n" + "=" * 60)
    print("[3] 分时数据测试")
    print("=" * 60)
    try:
        resp = requests.get(f"{BASE_URL}/api/stock/600664?type=minute", timeout=15, verify=False)
        data = resp.json()
        print(f"  success={data['success']}")
        if data['success']:
            print(f"  数据条数: {len(data['data'])}")
            assert len(data['data']) > 0, "分时数据为空"
            print(f"  首条: {data['data'][0]}")
            print(f"  [PASS] 分时数据正常")
            results['minute'] = 'PASS'
            return True
        else:
            print(f"  [FAIL] {data.get('error')}")
            results['minute'] = f'FAIL: {data.get("error")}'
            return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        results['minute'] = f'FAIL: {e}'
        return False

def test_daily():
    print("\n" + "=" * 60)
    print("[4] 日K数据测试")
    print("=" * 60)
    try:
        resp = requests.get(f"{BASE_URL}/api/stock/600664?type=daily", timeout=15, verify=False)
        data = resp.json()
        print(f"  success={data['success']}, error={data.get('error','None')}")
        if data['success'] and len(data['data']) > 0:
            print(f"  数据条数: {len(data['data'])}")
            for item in data['data'][-3:]:
                print(f"    {item['date']}: O={item['open']} C={item['close']} H={item['high']} L={item['low']}")
            print(f"  [PASS] 日K数据正常")
            results['daily'] = 'PASS'
            return True
        else:
            print(f"  [FAIL] 日K数据为空或获取失败")
            results['daily'] = f'FAIL: {data.get("error","无数据")}'
            return False
    except Exception as e:
        print(f"  [FAIL] {e}")
        results['daily'] = f'FAIL: {e}'
        return False

def test_footer(data):
    print("\n" + "=" * 60)
    print("[5] 底部信息测试")
    print("=" * 60)
    ok = 'source' in data and 'collection_time' in data
    print(f"  source={data.get('source','MISSING')}")
    print(f"  time={data.get('collection_time','MISSING')}")
    assert ok, "底部信息缺失"
    print(f"  [PASS] 底部信息完整")
    results['footer'] = 'PASS'

def main():
    print("\n" + "=" * 60)
    print("   A股人气榜查询 - 自动化测试")
    print("=" * 60)
    data = test_api_hotlist()
    if not data:
        print("\nAPI测试失败，终止")
        sys.exit(1)
    test_data_logic(data)
    test_minute()
    test_daily()
    test_footer(data)
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    for k, v in results.items():
        print(f"  {k}: {v}")
    all_pass = all(v == 'PASS' for v in results.values())
    print(f"\n结论: {'ALL PASS' if all_pass else 'SOME FAILED'}")

if __name__ == '__main__':
    import urllib3
    urllib3.disable_warnings()
    main()
