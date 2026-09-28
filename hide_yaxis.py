import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app.js', 'r', encoding='utf-8') as f:
    content = f.read()

# 隐藏分时图的成交量Y轴标签
old_minute_yaxis = """            {
                type: 'value',
                gridIndex: 1,
                axisLabel: { color: '#a0a0a0' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }
            }
        ],
        series: [
            {
                name: '价格'"""

new_minute_yaxis = """            {
                type: 'value',
                gridIndex: 1,
                axisLabel: { show: false },
                splitLine: { show: false }
            }
        ],
        series: [
            {
                name: '价格'"""

content = content.replace(old_minute_yaxis, new_minute_yaxis)

# 隐藏日K图的成交量Y轴标签
old_daily_yaxis = """            {
                type: 'value',
                gridIndex: 1,
                axisLabel: { color: '#a0a0a0' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } }
            }
        ],
        dataZoom:"""

new_daily_yaxis = """            {
                type: 'value',
                gridIndex: 1,
                axisLabel: { show: false },
                splitLine: { show: false }
            }
        ],
        dataZoom:"""

content = content.replace(old_daily_yaxis, new_daily_yaxis)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done!')
