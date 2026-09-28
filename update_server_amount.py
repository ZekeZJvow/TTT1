import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 修改分时数据解析 - 添加成交金额
old_minute_parse = """                if minute_data:
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
                            })"""

new_minute_parse = """                if minute_data:
                    result = []
                    for item in minute_data:
                        parts = item.split(' ')
                        if len(parts) >= 4:
                            time_str = parts[0]
                            if len(time_str) == 4:
                                time_str = time_str[:2] + ':' + time_str[2:]
                            result.append({
                                'time': time_str,
                                'price': float(parts[1]) if parts[1] else 0,
                                'volume': int(parts[2]) if parts[2] else 0,
                                'amount': float(parts[3]) if parts[3] else 0
                            })"""

content = content.replace(old_minute_parse, new_minute_parse)

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done! Server updated')
