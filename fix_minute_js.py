with open("app.js", "r", encoding="utf-8") as f:
    content = f.read()

# 修改loadChart函数，保存prev_close
old_load = """        if (data.success && data.data && data.data.length > 0) {
            if (type === 'minute') {
                renderMinuteChart(data.data);
            } else {
                renderDailyChart(data.data);
            }"""

new_load = """        if (data.success && data.data && data.data.length > 0) {
            if (type === 'minute') {
                window.__prevClose = data.prev_close || 0;
                renderMinuteChart(data.data);
            } else {
                renderDailyChart(data.data);
            }"""

content = content.replace(old_load, new_load)

# 修改分时图tooltip的涨跌幅计算
old_change = """                    const time = price.name;
                    const priceVal = price.data;
                    // 使用开盘价作为基准计算涨跌幅
                    const openPrice = prices[0];
                    const change = ((priceVal - openPrice) / openPrice * 100).toFixed(2);
                    const changeColor = priceVal >= openPrice ? '#e74c3c' : '#2ecc71';"""

new_change = """                    const time = price.name;
                    const priceVal = price.data;
                    // 使用前一日收盘价作为基准计算涨跌幅
                    const prevClose = window.__prevClose || prices[0];
                    const change = ((priceVal - prevClose) / prevClose * 100).toFixed(2);
                    const changeColor = priceVal >= prevClose ? '#e74c3c' : '#2ecc71';"""

content = content.replace(old_change, new_change)

# 修改均价计算说明
old_avg = """                    html += '<div>均价: <span style="color:#f39c12">' + (prices.slice(0, price.dataIndex + 1).reduce((a, b) => a + b, 0) / (price.dataIndex + 1)).toFixed(2) + '</span></div>';"""

new_avg = """                    html += '<div>均价: <span style="color:#f39c12">' + (prices.slice(0, price.dataIndex + 1).reduce((a, b) => a + b, 0) / (price.dataIndex + 1)).toFixed(2) + '</span></div>';
                    html += '<div>昨收: <span style="color:#a0a0a0">' + prevClose.toFixed(2) + '</span></div>';"""

content = content.replace(old_avg, new_avg)

with open("app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("app.js updated")
