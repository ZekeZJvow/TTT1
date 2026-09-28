with open("app.js", "r", encoding="utf-8") as f:
    content = f.read()

# 找到renderDailyChart函数中setOption之前添加数据保存
# 找到特定的setOption位置 - 在dataZoom之后
old_str = """        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
            { 
                type: 'slider', 
                xAxisIndex: [0, 1], 
                start: 60, 
                end: 100, 
                top: '92%', 
                height: 20,
                borderColor: '#333',
                backgroundColor: 'rgba(255,255,255,0.05)',
                fillerColor: 'rgba(52, 152, 219, 0.2)',
                handleStyle: { color: '#3498db' }
            }
        ],
        series: [
            {
                name: 'K线',
                type: 'candlestick',
                data: ohlc,"""

new_str = """        dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1], start: 60, end: 100 },
            { 
                type: 'slider', 
                xAxisIndex: [0, 1], 
                start: 60, 
                end: 100, 
                top: '92%', 
                height: 20,
                borderColor: '#333',
                backgroundColor: 'rgba(255,255,255,0.05)',
                fillerColor: 'rgba(52, 152, 219, 0.2)',
                handleStyle: { color: '#3498db' }
            }
        ],
        series: [
            {
                name: 'K线',
                type: 'candlestick',
                data: ohlc,
                itemStyle: {
                    color: '#e74c3c',
                    color0: '#2ecc71',
                    borderColor: '#e74c3c',
                    borderColor0: '#2ecc71'
                }
            },
            {
                name: '成交量',
                type: 'bar',
                data: volumes,
                xAxisIndex: 1,
                yAxisIndex: 1,
                itemStyle: {
                    color: function(params) {
                        const item = ohlc[params.dataIndex];
                        return item[1] >= item[0] ? '#e74c3c' : '#2ecc71';
                    }
                }
            }
        ]
    };
    
    // 保存数据到全局变量供tooltip使用
    window.__dailyData = data;
    currentChart.setOption(option);
}

function renderMinuteChart"""

content = content.replace(old_str, new_str)

with open("app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Done!")
