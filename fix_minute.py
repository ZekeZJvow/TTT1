with open("app.js", "r", encoding="utf-8") as f:
    content = f.read()

# 找到分时图的tooltip配置并替换
old_tooltip = """        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(26, 26, 46, 0.9)',
            borderColor: '#333',
            textStyle: { color: '#fff' },
            axisPointer: { type: 'cross' }
        },
        legend: {
            data: ['价格', '成交量'],"""

new_tooltip = """        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(26, 26, 46, 0.95)',
            borderColor: '#444',
            textStyle: { color: '#fff', fontSize: 13 },
            axisPointer: { 
                type: 'cross',
                crossStyle: { color: '#666' }
            },
            formatter: function(params) {
                const price = params.find(p => p.seriesName === '价格');
                const volume = params.find(p => p.seriesName === '成交量');
                if (price) {
                    const time = price.name;
                    const priceVal = price.data;
                    // 使用开盘价作为基准计算涨跌幅
                    const openPrice = prices[0];
                    const change = ((priceVal - openPrice) / openPrice * 100).toFixed(2);
                    const changeColor = priceVal >= openPrice ? '#e74c3c' : '#2ecc71';
                    let html = '<div style="font-weight:bold;margin-bottom:5px;">' + time + '</div>';
                    html += '<div>价格: <span style="color:' + changeColor + '">' + priceVal.toFixed(2) + '</span></div>';
                    html += '<div>涨跌: <span style="color:' + changeColor + '">' + (change >= 0 ? '+' : '') + change + '%</span></div>';
                    html += '<div>均价: <span style="color:#f39c12">' + (prices.slice(0, price.dataIndex + 1).reduce((a, b) => a + b, 0) / (price.dataIndex + 1)).toFixed(2) + '</span></div>';
                    if (volume) {
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

content = content.replace(old_tooltip, new_tooltip)

with open("app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Done!")
