// ==================== 全局变量 ====================
let allData = [];
let filteredData = [];
let currentChart = null;
let currentStockCode = '';
let currentStockName = '';
let currentTab = 'minute';

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    console.log('A股人气榜查询应用已加载');
});

// ==================== 数据获取 ====================
async function fetchData() {
    const btn = document.getElementById('query-btn');
    const btnText = btn.querySelector('.btn-text');
    const btnLoading = btn.querySelector('.btn-loading');
    
    btn.disabled = true;
    btnText.classList.add('hidden');
    btnLoading.classList.remove('hidden');
    
    hideAllResults();
    
    try {
        const response = await fetch('/api/hotlist');
        const result = await response.json();
        
        if (result.success) {
            displayData(result);
        } else {
            showError(result.error || '查询失败，请稍后重试');
        }
    } catch (error) {
        console.error('请求失败:', error);
        showError('网络请求失败，请检查后端服务是否启动');
    } finally {
        btn.disabled = false;
        btnText.classList.remove('hidden');
        btnLoading.classList.add('hidden');
    }
}

// ==================== 显示数据 ====================
function displayData(result) {
    allData = result.data;
    filteredData = [...allData];
    
    displayTradingDay(result.trading_day, result.message);
    
    if (result.degraded) {
        document.getElementById('degrade-notice').classList.remove('hidden');
    }
    
    populateConceptFilter(allData);
    document.getElementById('filter-section').classList.remove('hidden');
    renderTable(filteredData);
    displaySummary(result.summary);
    displayFooter(result.source, result.collection_time);
}

// ==================== 交易日显示 ====================
function displayTradingDay(tradingDay, message) {
    const container = document.getElementById('trading-day-info');
    document.getElementById('trading-day').textContent = tradingDay;
    
    const messageEl = document.getElementById('trading-day-message');
    if (message) {
        messageEl.textContent = '· ' + message;
        messageEl.style.display = 'inline';
    } else {
        messageEl.style.display = 'none';
    }
    
    container.classList.remove('hidden');
}

// ==================== 表格渲染 ====================
function renderTable(data) {
    const tbody = document.getElementById('stock-table-body');
    tbody.innerHTML = '';
    
    data.forEach(item => {
        const tr = document.createElement('tr');
        
        if (item.is_hot) {
            tr.classList.add('hot-row');
        }
        
        // 排名
        const rankClass = item.rank <= 3 ? 'rank-' + item.rank : 'rank-other';
        const rankTd = document.createElement('td');
        rankTd.className = 'col-rank';
        rankTd.innerHTML = '<span class="rank-badge ' + rankClass + '">' + item.rank + '</span>';
        tr.appendChild(rankTd);
        
        // 名称（可点击）
        const nameTd = document.createElement('td');
        nameTd.className = 'col-name';
        const nameLink = document.createElement('a');
        nameLink.className = 'stock-name-link';
        nameLink.textContent = item.name;
        nameLink.onclick = function() {
            openStockChart(item.code, item.name);
        };
        nameTd.appendChild(nameLink);
        tr.appendChild(nameTd);
        
        // 代码
        const codeTd = document.createElement('td');
        codeTd.className = 'col-code';
        codeTd.textContent = item.code;
        codeTd.style.color = '#a0a0a0';
        tr.appendChild(codeTd);
        
        // 涨跌幅
        const changeTd = document.createElement('td');
        changeTd.className = 'col-change';
        const changeVal = item.rise_and_fall || 0;
        const changeColor = changeVal >= 0 ? '#e74c3c' : '#2ecc71';
        const changeText = (changeVal >= 0 ? '+' : '') + changeVal.toFixed(2) + '%';
        changeTd.innerHTML = '<span style="color:' + changeColor + ';font-weight:bold;">' + changeText + '</span>';
        tr.appendChild(changeTd);
        
        // 连板数
        const boardsTd = document.createElement('td');
        boardsTd.className = 'col-boards';
        const boardsClass = item.consecutive_boards !== '无' ? 'has-boards' : 'no-boards';
        boardsTd.innerHTML = '<span class="boards-tag ' + boardsClass + '">' + item.consecutive_boards + '</span>';
        tr.appendChild(boardsTd);
        
        // 所属梯队
        const tierTd = document.createElement('td');
        tierTd.className = 'col-tier';
        let tierClass = 'tier-3';
        if (item.tier.includes('Top10')) tierClass = 'tier-1';
        else if (item.tier.includes('Top20')) tierClass = 'tier-2';
        tierTd.innerHTML = '<span class="tier-tag ' + tierClass + '">' + item.tier.split('·')[0] + '</span>';
        tr.appendChild(tierTd);
        
        // 概念标签
        const conceptTd = document.createElement('td');
        conceptTd.className = 'col-concept';
        conceptTd.textContent = item.concept_tag;
        tr.appendChild(conceptTd);
        
        // 异动解读
        const analysisTd = document.createElement('td');
        analysisTd.className = 'col-analysis';
        const analysisClass = item.anomaly_analysis === '无' ? 'analysis-text no-analysis' : 'analysis-text';
        analysisTd.innerHTML = '<span class="' + analysisClass + '">' + item.anomaly_analysis + '</span>';
        tr.appendChild(analysisTd);
        
        tbody.appendChild(tr);
    });
    
    document.getElementById('table-container').classList.remove('hidden');
}

// ==================== 筛选功能 ====================
function populateConceptFilter(data) {
    const select = document.getElementById('concept-filter');
    const allConcepts = new Set();
    
    data.forEach(item => {
        if (item.concept_tag && item.concept_tag !== '未获取' && item.concept_tag !== '降级模式，无数据') {
            item.concept_tag.split(',').forEach(tag => {
                allConcepts.add(tag.trim());
            });
        }
    });
    
    const sortedConcepts = [...allConcepts].sort();
    select.innerHTML = '<option value="">全部概念</option>';
    
    sortedConcepts.forEach(concept => {
        const option = document.createElement('option');
        option.value = concept;
        option.textContent = concept;
        select.appendChild(option);
    });
}

function filterData() {
    const searchText = document.getElementById('search-input').value.toLowerCase();
    const concept = document.getElementById('concept-filter').value;
    const hotOnly = document.getElementById('hot-only').checked;
    const top10Only = document.getElementById('top10-only').checked;
    
    filteredData = allData.filter(item => {
        if (searchText) {
            const matchName = item.name.toLowerCase().includes(searchText);
            const matchCode = item.code.toLowerCase().includes(searchText);
            if (!matchName && !matchCode) return false;
        }
        
        if (concept && item.concept_tag && !item.concept_tag.includes(concept)) {
            return false;
        }
        
        if (hotOnly && !item.is_hot) {
            return false;
        }
        
        if (top10Only && item.rank > 10) {
            return false;
        }
        
        return true;
    });
    
    renderTable(filteredData);
}

async function loadNews(code) {
    const newsList = document.getElementById('news-list');
    newsList.innerHTML = '<div style="color:#a0a0a0;text-align:center;padding:10px;">加载中...</div>';
    
    try {
        const response = await fetch('/api/stock/' + code + '/news');
        const data = await response.json();
        
        if (data.success && data.data && data.data.length > 0) {
            let html = '';
            data.data.forEach(item => {
                const date = item.date ? item.date.split(' ')[0] : '';
                html += '<div class="news-item">';
                html += '<div class="news-title">' + item.title + '</div>';
                html += '<div class="news-meta"><span class="news-date">' + date + '</span><span class="news-source">' + item.source + '</span></div>';
                html += '</div>';
            });
            newsList.innerHTML = html;
        } else {
            newsList.innerHTML = '<div style="color:#a0a0a0;text-align:center;padding:10px;">暂无相关新闻</div>';
        }
    } catch (error) {
        newsList.innerHTML = '<div style="color:#a0a0a0;text-align:center;padding:10px;">新闻加载失败</div>';
    }
}
// ==================== 图表功能 ====================
async function openStockChart(code, name) {
    console.log('打开图表:', code, name);
    currentStockCode = code;
    currentStockName = name;
    currentTab = 'minute';
    
    document.getElementById('modal-title').textContent = name + ' (' + code + ')';
    document.getElementById('stock-modal').classList.remove('hidden');
    
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelector('.tab-btn').classList.add('active');
    
    setTimeout(async () => {
        await loadChart('minute');
        loadNews(code);
    }, 100);
}

function closeModal() {
    document.getElementById('stock-modal').classList.add('hidden');
    if (currentChart) {
        currentChart.dispose();
        currentChart = null;
    }
}

async function switchTab(tab, event) {
    console.log('切换tab:', tab);
    currentTab = tab;
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    event.target.classList.add('active');
    await loadChart(tab);
}

async function loadChart(type) {
    console.log('加载图表:', type);
    const chartDom = document.getElementById('chart-container');
    
    if (chartDom.offsetWidth === 0 || chartDom.offsetHeight === 0) {
        chartDom.style.width = '100%';
        chartDom.style.height = '400px';
    }
    
    if (currentChart) {
        currentChart.dispose();
    }
    
    currentChart = echarts.init(chartDom);
    currentChart.showLoading({
        text: '加载中...',
        color: '#3498db',
        maskColor: 'rgba(26, 26, 46, 0.8)'
    });
    
    try {
        const response = await fetch('/api/stock/' + currentStockCode + '?type=' + type);
        const data = await response.json();
        
        currentChart.hideLoading();
        
        if (data.success && data.data && data.data.length > 0) {
            if (type === 'minute') {
                window.__prevClose = data.prev_close || 0;
                renderMinuteChart(data.data);
            } else {
                renderDailyChart(data.data);
            }
        } else {
            currentChart.setOption({
                title: {
                    text: '暂无数据',
                    left: 'center',
                    top: 'center',
                    textStyle: { color: '#a0a0a0', fontSize: 16 }
                }
            });
        }
    } catch (error) {
        currentChart.hideLoading();
        console.error('图表请求失败:', error);
        currentChart.setOption({
            title: {
                text: '数据加载失败',
                left: 'center',
                top: 'center',
                textStyle: { color: '#e74c3c', fontSize: 16 }
            }
        });
    }
}

function renderMinuteChart(data) {
    const times = data.map(item => item.time);
    const prices = data.map(item => item.price);
    const volumes = data.map(item => item.volume);
    
    const option = {
        backgroundColor: 'transparent',
        tooltip: {
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
                    // 使用前一日收盘价作为基准计算涨跌幅
                    const prevClose = window.__prevClose || prices[0];
                    const change = ((priceVal - prevClose) / prevClose * 100).toFixed(2);
                    const changeColor = priceVal >= prevClose ? '#e74c3c' : '#2ecc71';
                    let html = '<div style="font-weight:bold;margin-bottom:5px;">' + time + '</div>';
                    html += '<div>价格: <span style="color:' + changeColor + '">' + priceVal.toFixed(2) + '</span></div>';
                    html += '<div>涨跌: <span style="color:' + changeColor + '">' + (change >= 0 ? '+' : '') + change + '%</span></div>';
                    html += '<div>均价: <span style="color:#f39c12">' + (prices.slice(0, price.dataIndex + 1).reduce((a, b) => a + b, 0) / (price.dataIndex + 1)).toFixed(2) + '</span></div>';
                    html += '<div>昨收: <span style="color:#a0a0a0">' + prevClose.toFixed(2) + '</span></div>';
                    if (volume) {
                        const vol = volume.data;
                        html += '<div>成交金额: <span style="color:#fff">' + (vol / 100000000).toFixed(2) + '亿</span></div>';
                    }
                    return html;
                }
                return '';
            }
        },
        legend: {
            data: ['价格', '成交金额'],
            textStyle: { color: '#a0a0a0' },
            top: 10
        },
        grid: [
            { left: '10%', right: '10%', top: '15%', height: '55%' },
            { left: '10%', right: '10%', top: '75%', height: '20%' }
        ],
        axisPointer: {
            link: [{ xAxisIndex: [0, 1] }]
        },
        xAxis: [
            {
                type: 'category',
                data: times,
                gridIndex: 0,
                axisLabel: { color: '#a0a0a0', interval: Math.floor(times.length / 8) },
                axisLine: { lineStyle: { color: '#333' } },
                boundaryGap: false
            },
            {
                type: 'category',
                data: times,
                gridIndex: 1,
                axisLabel: { show: false },
                axisLine: { lineStyle: { color: '#333' } },
                boundaryGap: false
            }
        ],
        yAxis: [
            {
                type: 'value',
                gridIndex: 0,
                axisLabel: { color: '#a0a0a0' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
                scale: true
            },
            {
                type: 'value',
                gridIndex: 1,
                axisLabel: { show: false },
                splitLine: { show: false }
            }
        ],
        series: [
            {
                name: '价格',
                type: 'line',
                data: prices,
                xAxisIndex: 0,
                yAxisIndex: 0,
                smooth: true,
                lineStyle: { color: '#e74c3c', width: 2 },
                itemStyle: { color: '#e74c3c' },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: 'rgba(231, 76, 60, 0.4)' },
                        { offset: 1, color: 'rgba(231, 76, 60, 0.05)' }
                    ])
                },
                symbol: 'none'
            },
            {
                name: '成交金额',
                type: 'bar',
                data: volumes,
                xAxisIndex: 1,
                yAxisIndex: 1,
                itemStyle: {
                    color: function(params) {
                        const idx = params.dataIndex;
                        if (idx > 0 && prices[idx] >= prices[idx - 1]) {
                            return '#e74c3c';
                        }
                        return '#2ecc71';
                    }
                }
            }
        ]
    };
    
    currentChart.setOption(option);
}

function renderDailyChart(data) {
    const dates = data.map(item => item.date);
    const ohlc = data.map(item => [item.open, item.close, item.low, item.high]);
    const volumes = data.map(item => item.volume);
    
    const option = {
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(26, 26, 46, 0.95)',
            borderColor: '#444',
            textStyle: { color: '#fff', fontSize: 13 },
            axisPointer: { 
                type: 'cross',
                crossStyle: { color: '#666' }
            },
            formatter: function(params) {
                const kline = params.find(p => p.seriesName === 'K线');
                const volume = params.find(p => p.seriesName === '成交量');
                if (kline) {
                    const data = kline.data;
                    const date = kline.name;
                    const klineIndex = params[0].dataIndex;
                    let prevClose = data[1];
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
                        html += '<div>成交金额: <span style="color:#fff">' + (vol / 100000000).toFixed(2) + '亿</span></div>';
                    }
                    return html;
                }
                return '';
            }
        },
        legend: {
            data: ['K线', '成交量'],
            textStyle: { color: '#a0a0a0' },
            top: 10
        },
        grid: [
            { left: '10%', right: '10%', top: '15%', height: '55%' },
            { left: '10%', right: '10%', top: '75%', height: '20%' }
        ],
        axisPointer: {
            link: [{ xAxisIndex: [0, 1] }]
        },
        xAxis: [
            {
                type: 'category',
                data: dates,
                gridIndex: 0,
                axisLabel: { show: false },
                axisLine: { lineStyle: { color: '#333' } },
                axisTick: { show: false }
            },
            {
                type: 'category',
                data: dates,
                gridIndex: 1,
                axisLabel: { show: false },
                axisLine: { lineStyle: { color: '#333' } },
                axisTick: { show: false }
            }
        ],
        yAxis: [
            {
                type: 'value',
                gridIndex: 0,
                axisLabel: { color: '#a0a0a0' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.1)' } },
                scale: true
            },
            {
                type: 'value',
                gridIndex: 1,
                axisLabel: { show: false },
                splitLine: { show: false }
            }
        ],
        dataZoom: [
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
                xAxisIndex: 0,
                yAxisIndex: 0,
                itemStyle: {
                    color: '#e74c3c',
                    color0: '#2ecc71',
                    borderColor: '#e74c3c',
                    borderColor0: '#2ecc71'
                }
            },
            {
                name: '成交金额',
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
    
    window.__dailyData = data;
    currentChart.setOption(option);
}

// ==================== 总结显示 ====================
function displaySummary(summary) {
    document.getElementById('summary-main').textContent = summary.main_direction;
    document.getElementById('summary-hot').textContent = summary.hot_proportion;
    document.getElementById('summary-section').classList.remove('hidden');
}

// ==================== 底部信息 ====================
function displayFooter(source, collectionTime) {
    document.getElementById('data-source').textContent = source;
    document.getElementById('collection-time').textContent = collectionTime;
    document.getElementById('footer-info').classList.remove('hidden');
}

// ==================== 错误处理 ====================
function showError(message) {
    document.getElementById('error-text').textContent = message;
    document.getElementById('error-message').classList.remove('hidden');
}

// ==================== 隐藏所有结果 ====================
function hideAllResults() {
    document.getElementById('degrade-notice').classList.add('hidden');
    document.getElementById('trading-day-info').classList.add('hidden');
    document.getElementById('filter-section').classList.add('hidden');
    document.getElementById('error-message').classList.add('hidden');
    document.getElementById('table-container').classList.add('hidden');
    document.getElementById('summary-section').classList.add('hidden');
    document.getElementById('footer-info').classList.add('hidden');
}

// 点击模态框外部关闭
document.addEventListener('click', function(e) {
    if (e.target.id === 'stock-modal') {
        closeModal();
    }
});

// ESC键关闭模态框
document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
        closeModal();
    }
});

// 窗口大小改变时重绘图表
window.addEventListener('resize', function() {
    if (currentChart) {
        currentChart.resize();
    }
});

