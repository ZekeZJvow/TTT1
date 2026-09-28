with open("app.js", "r", encoding="utf-8") as f:
    content = f.read()

# 找到并替换日K图的tooltip formatter
old_formatter = """            formatter: function(params) {
                const kline = params.find(p => p.seriesName === 'K线');
                const volume = params.find(p => p.seriesName === '成交量');
                if (kline) {
                    const data = kline.data;
                    const date = kline.name;
                    const change = ((data[2] - data[1]) / data[1] * 100).toFixed(2);
                    const changeColor = data[2] >= data[1] ? '#e74c3c' : '#2ecc71';
                    let html = '<div style="font-weight:bold;margin-bottom:5px;">' + date + '</div>';
                    html += '<div>开: <span style="color:#fff">' + data[1] + '</span></div>';
                    html += '<div>收: <span style="color:' + changeColor + '">' + data[2] + '</span></div>';
                    html += '<div>高: <span style="color:#fff">' + data[4] + '</span></div>';
                    html += '<div>低: <span style="color:#fff">' + data[3] + '</span></div>';
                    html += '<div>涨跌: <span style="color:' + changeColor + '">' + change + '%</span></div>';
                    if (volume) {
                        const vol = volume.data;
                        html += '<div>成交量: <span style="color:#fff">' + (vol / 10000).toFixed(0) + '万</span></div>';
                    }
                    return html;
                }
                return '';
            }"""

new_formatter = """            formatter: function(params) {
                const kline = params.find(p => p.seriesName === 'K线');
                const volume = params.find(p => p.seriesName === '成交量');
                if (kline) {
                    const data = kline.data;
                    const date = kline.name;
                    // 使用前一日收盘价计算涨跌幅
                    const klineIndex = params[0].dataIndex;
                    let prevClose = data[1]; // 默认用开盘价
                    if (klineIndex > 0 && window.__dailyData && window.__dailyData[klineIndex - 1]) {
                        prevClose = window.__dailyData[klineIndex - 1].close;
                    }
                    const change = ((data[2] - prevClose) / prevClose * 100).toFixed(2);
                    const changeColor = data[2] >= prevClose ? '#e74c3c' : '#2ecc71';
                    let html = '<div style="font-weight:bold;margin-bottom:5px;">' + date + '</div>';
                    html += '<div>开: <span style="color:#fff">' + data[1] + '</span></div>';
                    html += '<div>收: <span style="color:' + changeColor + '">' + data[2] + '</span></div>';
                    html += '<div>高: <span style="color:#fff">' + data[4] + '</span></div>';
                    html += '<div>低: <span style="color:#fff">' + data[3] + '</span></div>';
                    html += '<div>涨跌: <span style="color:' + changeColor + '">' + change + '%</span></div>';
                    if (volume) {
                        const vol = volume.data;
                        html += '<div>成交量: <span style="color:#fff">' + (vol / 10000).toFixed(0) + '万</span></div>';
                    }
                    return html;
                }
                return '';
            }"""

content = content.replace(old_formatter, new_formatter)

# 在renderDailyChart函数中，获取数据后保存到window.__dailyData
old_option_set = """    currentChart.setOption(option);
}"""

new_option_set = """    // 保存数据到全局变量供tooltip使用
    window.__dailyData = data;
    currentChart.setOption(option);
}"""

# 只替换renderDailyChart中的setOption
# 找到renderDailyChart函数的setOption位置
import re
# 在renderDailyChart函数结尾处添加
old_daily_end = """    currentChart.setOption(option);
}

function renderMinuteChart"""

new_daily_end = """    window.__dailyData = data;
    currentChart.setOption(option);
}

function renderMinuteChart"""

content = content.replace(old_daily_end, new_daily_end)

with open("app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Done!")
