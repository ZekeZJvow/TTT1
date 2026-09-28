import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 修改分时图tooltip - 显示成交金额
old_minute_tooltip = """                    if (volume) {
                        const vol = volume.data;
                        html += '<div>成交量: <span style="color:#fff">' + (vol / 10000).toFixed(0) + '万</span></div>';
                    }
                    return html;
                }
                return '';
            }
        },
        legend: {
            data: ['价格', '成交量'],"""

new_minute_tooltip = """                    if (volume) {
                        const vol = volume.data;
                        html += '<div>成交金额: <span style="color:#fff">' + (vol / 100000000).toFixed(2) + '亿</span></div>';
                    }
                    return html;
                }
                return '';
            }
        },
        legend: {
            data: ['价格', '成交金额'],"""

content = content.replace(old_minute_tooltip, new_minute_tooltip)

# 修改日K图tooltip - 显示成交金额
old_daily_vol = """                    if (volume) {
                        const vol = volume.data;
                        html += '<div>成交量: <span style="color:#fff">' + (vol / 10000).toFixed(0) + '万</span></div>';
                    }"""

new_daily_vol = """                    if (volume) {
                        const vol = volume.data;
                        html += '<div>成交金额: <span style="color:#fff">' + (vol / 100000000).toFixed(2) + '亿</span></div>';
                    }"""

content = content.replace(old_daily_vol, new_daily_vol)

# 修改图例名称
content = content.replace("name: '成交量'", "name: '成交金额'")

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done! App updated')
