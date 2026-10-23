// ==================== 全局变量 ====================
let allData = [];
let filteredData = [];
let currentChart = null;
let currentStockCode = '';
let currentStockName = '';
let currentTab = 'minute';

// ==================== 初始化 ====================
document.addEventListener('DOMContentLoaded', function() {
    console.log('A股人气雷达 已加载');
    // auto load on page open
    fetchData();
    loadMarketScore();          // 页头「今日行情评分」：只读已有结果，不触发扫描
});

// 页头今日行情评分（= 封板率）
function setMarketScore(score) {
    var el = document.getElementById('ms-score');
    if (!el) return;
    var sc = Number(score);
    if (score === null || score === undefined || score === '' || isNaN(sc)) {
        el.textContent = '--';
        el.className = '';
        return;
    }
    el.textContent = sc.toFixed(1);
    el.className = (sc >= 70 ? 'up-strong' : (sc >= 50 ? 'mid' : 'down'));
}

async function loadMarketScore(dateOpt) {
    try {
        var q = dateOpt ? ('?date=' + encodeURIComponent(dateOpt)) : '';
        var r = await (await fetch('/api/market-score' + q)).json();
        if (r && r.success) setMarketScore(r.score);
    } catch (e) { /* 忽略：显示 -- 即可 */ }
}

// ==================== 数据获取 ====================
async function fetchData(dateOpt) {
    const btn = document.getElementById('query-btn');
    const btnText = btn.querySelector('.btn-text');
    const btnLoading = btn.querySelector('.btn-loading');
    
    btn.disabled = true;
    btnText.classList.add('hidden');
    btnLoading.classList.remove('hidden');
    
    hideAllResults();
    const _eh = document.getElementById('empty-history');
    if (_eh) { _eh.classList.add('hidden'); _eh.innerHTML = ''; }

    const _d = (typeof dateOpt === 'string') ? dateOpt : hotlistSelectedDate;

    try {
        // 没选日期 -> 取「此刻实时」（并归档到本日，含周末/节假日）；选了日期 -> 读该日存档
        const response = await fetch('/api/hotlist' +
            (_d ? '?date=' + encodeURIComponent(_d) : '?live=1'));
        const result = await response.json();

        if (result.success) {
            if (!_d && result.trading_day) hotlistLatestDate = result.trading_day;
            if (result.empty) {
                showEmptyHistory(result);
            } else {
                displayData(result);
            }
            initHotlistRangeOnce();
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

// 连续上榜标签（人气榜 / 题材个股共用）
// 高亮规则：连续天数 > 1（即 2 天及以上）就高亮
function streakTagHtml(days) {
    const n = Number(days || 1);
    const tip = '连续 ' + n + ' 个交易日排进人气榜前30名（含当天）';
    return '<span class="streak-tag' + (n > 1 ? ' hot' : '') + '" title="' + tip + '">' + n + '天</span>';
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
    displayHotTopics(result.topics, result.live_rebuild);
}

// 「此刻热门话题」条（实时模式才有）
function displayHotTopics(topics, live) {
    const box = document.getElementById('hotlist-topics');
    if (!box) return;
    if (!topics || !topics.length) { box.classList.add('hidden'); box.innerHTML = ''; return; }
    box.innerHTML = '<span class="ht-label">⚡ 此刻热门话题</span>' +
        topics.map(function (t) {
            return '<span class="ht-item">' + escHtml(t.title) +
                   '<em>' + (Number(t.hot || 0) / 10000).toFixed(1) + '万</em></span>';
        }).join('');
    box.classList.remove('hidden');
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
        const _raw = item.rise_and_fall;
        const _has = (_raw !== null && _raw !== undefined && _raw !== '' && !isNaN(Number(_raw)));
        if (_has) {
            const changeVal = Number(_raw);
            const changeColor = changeVal >= 0 ? '#e74c3c' : '#2ecc71';
            changeTd.innerHTML = '<span style="color:' + changeColor + ';font-weight:bold;">' +
                (changeVal >= 0 ? '+' : '') + changeVal.toFixed(2) + '%</span>';
        } else {
            // 回补数据没有涨跌幅，显示 — 而不是假的 +0.00%
            changeTd.innerHTML = '<span style="color:#7a7a7a;">—</span>';
        }
        tr.appendChild(changeTd);
        
        // 连板数
        const boardsTd = document.createElement('td');
        boardsTd.className = 'col-boards';
        const boardsClass = item.consecutive_boards !== '无' ? 'has-boards' : 'no-boards';
        boardsTd.innerHTML = '<span class="boards-tag ' + boardsClass + '">' + item.consecutive_boards + '</span>';
        tr.appendChild(boardsTd);

        // 连续上榜（含当天，按交易日往前回推；每天都排进前30才算连续）
        const streakTd = document.createElement('td');
        streakTd.className = 'col-streak';
        streakTd.innerHTML = streakTagHtml(item.streak_days);
        tr.appendChild(streakTd);
        
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
                const volume = params.find(p => p.seriesName === '成交金额');
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
                        // 分时 volume 是「累计成交量（手）」-> 成交额 = 手 × 100 × 价格
                        const amt = volume.data * 100 * priceVal;
                        html += '<div>成交额: <span style="color:#fff">' + (amt / 100000000).toFixed(2) + '亿</span></div>';
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
                    const _dk = (window.__dailyData || [])[klineIndex] || {};
                    if (_dk.amount != null) {
                        html += '<div>成交额: <span style="color:#fff">' + (_dk.amount / 100000000).toFixed(2) +
                                '亿</span>' + (_dk.amount_src === 'est'
                                    ? '<span style="color:#8a8a8a;font-size:11px"> (估)</span>' : '') + '</div>';
                    }
                    return html;
                }
                return '';
            }
        },
        legend: {
            data: ['K线', '成交金额'],
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



// ==================================================================
//                        动态选股（新增模块）
// ==================================================================

let screenResult = null;
let screenTableKey = 'rows';
let screenDateTouched = false;
let screenSortKey = 'gainClose';   // 默认按涨跌幅排序
let screenSortDir = 1;             // 1 = 升序（默认）
let screenPollTimer = null;

// ---------- 工具 ----------
function ymdLocal(d) {
    const p = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}

function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
}

// ---------- 模式切换 ----------
function switchMode(mode, event) {
    document.querySelectorAll('.mode-btn').forEach(function (b) { b.classList.remove('active'); });
    if (event && event.target) event.target.classList.add('active');
    document.getElementById('panel-hotlist').classList.toggle('hidden', mode !== 'hotlist');
    document.getElementById('panel-screen').classList.toggle('hidden', mode !== 'screen');
    document.getElementById('panel-theme').classList.toggle('hidden', mode !== 'theme');
    document.getElementById('panel-db').classList.toggle('hidden', mode !== 'db');
    document.getElementById('panel-multi').classList.toggle('hidden', mode !== 'multi');
    document.getElementById('panel-market').classList.toggle('hidden', mode !== 'market');
    document.getElementById('panel-cond').classList.toggle('hidden', mode !== 'cond');
    if (mode === 'screen') ensureScreenDate();
    if (mode === 'theme') { loadHotThemes(false); loadThemeDates(); }
    if (mode === 'multi') { loadMulti(false); }
    if (mode === 'market') { loadMarketHistory(false); }
    if (mode === 'cond') { loadCond(false); }
    if (mode === 'db') { loadDbOverview(); loadDbJob(); loadIntegrity(); loadNotifyStatus(); loadExportInfo(); loadDbCoverage(); loadBackfillMissing(); }
}

async function ensureScreenDate() {
    const el = document.getElementById('screen-date');
    if (!el || el.value || screenDateTouched) return;

    // 兜底：昨天
    const d = new Date();
    d.setDate(d.getDate() - 1);
    el.value = ymdLocal(d);

    // 优先取「最近交易日」（自动跳过节假日）
    try {
        const r = await (await fetch('/api/trading-days?n=1')).json();
        if (r.success && r.days && r.days.length && !screenDateTouched) {
            el.value = r.days[0];
        }
    } catch (e) { /* 保留兜底值 */ }
}

// ---------- 进度与状态 ----------
function setProgress(done, total, msg) {
    let pct = total > 0 ? (done / total * 100) : 3;
    if (pct < 3) pct = 3;
    if (pct > 100) pct = 100;
    document.getElementById('progress-fill').style.width = pct.toFixed(1) + '%';
    document.getElementById('progress-text').textContent = msg || (done + ' / ' + total);
}

function finishScreenUI() {
    const btn = document.getElementById('screen-btn');
    btn.disabled = false;
    btn.querySelector('.btn-text').classList.remove('hidden');
    btn.querySelector('.btn-loading').classList.add('hidden');
    document.getElementById('screen-progress').classList.add('hidden');
}

function screenError(msg) {
    document.getElementById('screen-error-text').textContent = msg;
    document.getElementById('screen-error').classList.remove('hidden');
}

// ---------- 主流程 ----------
async function startScreen() {
    const date = document.getElementById('screen-date').value;
    if (!date) { screenError('请先选择目标日期'); return; }
    if (screenPollTimer) { clearTimeout(screenPollTimer); screenPollTimer = null; }

    const btn = document.getElementById('screen-btn');
    btn.disabled = true;
    btn.querySelector('.btn-text').classList.add('hidden');
    btn.querySelector('.btn-loading').classList.remove('hidden');

    document.getElementById('screen-error').classList.add('hidden');
    document.getElementById('screen-error-hint').textContent = '';
    document.getElementById('screen-result').classList.add('hidden');
    document.getElementById('screen-progress').classList.remove('hidden');
    setProgress(0, 0, '正在启动扫描...');

    try {
        const r = await (await fetch('/api/screen/start?date=' + encodeURIComponent(date))).json();
        if (!r.success) { finishScreenUI(); screenError(r.error || '启动失败'); return; }
        if (r.cached) { handleScreenResult(r.result); return; }
        pollScreen(r.jobId);
    } catch (e) {
        finishScreenUI();
        screenError('请求失败：' + e.message);
    }
}

async function pollScreen(jobId) {
    try {
        const s = await (await fetch('/api/screen/status?jobId=' + encodeURIComponent(jobId))).json();
        if (!s.success) { finishScreenUI(); screenError(s.error || '任务丢失'); return; }
        if (s.state === 'running') {
            setProgress(s.done, s.total, s.message);
            screenPollTimer = setTimeout(function () { pollScreen(jobId); }, 1200);
            return;
        }
        handleScreenResult(s.result);
    } catch (e) {
        finishScreenUI();
        screenError('轮询失败：' + e.message);
    }
}

function handleScreenResult(res) {
    finishScreenUI();
    if (!res || !res.success) {
        screenError((res && res.error) || '扫描失败');
        if (res && res.recentDays && res.recentDays.length) {
            const hint = document.getElementById('screen-error-hint');
            hint.textContent = '点击自动填入最近交易日：' + res.recentDays.slice(0, 5).join('、');
            hint.onclick = function () {
                document.getElementById('screen-date').value = res.recentDays[0];
                startScreen();
            };
        }
        return;
    }
    screenResult = res;
    screenTableKey = 'rows';
    screenSortKey = 'gainClose';   // 每次扫描后仍默认按涨跌幅升序
    screenSortDir = 1;
    document.querySelectorAll('.sub-btn').forEach(function (b, i) {
        b.classList.toggle('active', i === 0);
    });
    renderScreenResult(res);
}

function renderScreenResult(res) {
    document.getElementById('sc-target').textContent = res.target;
    document.getElementById('sc-prev').textContent = res.prevDay;
    document.getElementById('sc-universe').textContent = res.universe + ' 只主板股（扫描 ' + res.scanned + '，停牌跳过 ' + res.suspended + '）';
    document.getElementById('sc-elapsed').textContent = res.elapsed + ' 秒';

    renderFunnel(res);
    renderVerify(res);

    document.getElementById('cnt-rows').textContent = res.rows.length;
    document.getElementById('cnt-broken').textContent = res.brokenRows.length;
    document.getElementById('cnt-removed').textContent = res.removedRows.length;

    renderScreenTable();

    document.getElementById('screen-foot').innerHTML =
        '数据来源：' + escHtml(res.source) + '<br>采集时间：' + escHtml(res.collectedAt) +
        '<br>阈值：D 盘中最高涨幅 &gt; ' + (res.threshold * 100) + '%　|　口径：' +
        res.prevDay + ' 未涨停 且 ' + res.target + ' 冲高<br>' +
        '<span class="dim">风险提示：本页为条件逻辑与历史数据统计，不构成投资建议。</span>';

    document.getElementById('screen-result').classList.remove('hidden');
}

function renderFunnel(res) {
    const f = res.funnel;
    const rows = [
        ['全部沪深主板非ST', res.universe, 'base'],
        ['条件② 盘中最高涨幅 &gt; 9%', f.cond2, 'step'],
        ['+ 条件① 昨日未涨停（入选）', f.final, 'final'],
        ['　其中：封住涨停', f.sealed, 'sub'],
        ['　其中：冲高未封', f.broken, 'sub'],
        ['被条件①剔除（昨日涨停股）', f.removedByCond1, 'drop']
    ];
    const max = Math.max.apply(null, rows.map(function (r) { return r[1]; }).concat([1]));
    let html = '<div class="funnel-list">';
    rows.forEach(function (r) {
        const pct = (r[1] / max) * 100;
        html += '<div class="funnel-row ' + r[2] + '">' +
                '<div class="funnel-label">' + r[0] + '</div>' +
                '<div class="funnel-track"><div class="funnel-bar" style="width:' + pct.toFixed(1) + '%"></div></div>' +
                '<div class="funnel-val">' + r[1] + '</div></div>';
    });
    html += '</div>';
    html += '<div class="funnel-note">封板率 <b>' + res.sealedRate + '%</b>（' + f.sealed + ' / ' + f.final + '）</div>';

    // 今日行情评分 = 封板率（0~100 分），大字号展示在最上方
    (function () {
        var sc = Number(res.sealedRate);
        var el = document.getElementById('ms-score');
        if (!el) return;
        el.textContent = isNaN(sc) ? '--' : sc.toFixed(1);
        el.className = isNaN(sc) ? '' : (sc >= 70 ? 'up-strong' : (sc >= 50 ? 'mid' : 'down'));
        var box = document.getElementById('market-score-box'); if (box) box.classList.remove('hidden');
    })();
    document.getElementById('funnel-body').innerHTML = html;
}

function renderVerify(res) {
    const v = res.validation;
    const ok = v.mismatch.length === 0;
    let html = '<h3>🔍 语义交叉校验</h3>';
    html += '<div class="verify-line">D 涨停池 <b>' + v.poolZtCount + '</b> 只　·　D 炸板池 <b>' + v.poolZbCount +
            '</b> 只　·　D-1 涨停+炸板池 <b>' + v.prevPoolCount + '</b> 只</div>';
    html += '<div class="verify-line ' + (ok ? 'ok' : 'warn') + '">' +
            (ok ? '✅ 价格法（最高价 ≥ 涨停价）与涨停池法结果完全一致，冲突 0 处'
                : '⚠️ 价格法与涨停池法存在 ' + v.mismatch.length + ' 处冲突') + '</div>';
    if (!ok) {
        html += '<ul class="verify-mismatch">';
        v.mismatch.slice(0, 10).forEach(function (m) {
            html += '<li>' + escHtml(m.code) + ' ' + escHtml(m.name) +
                    '：价格法=' + m.byPrice + '，池法=' + m.byPool + '</li>';
        });
        html += '</ul>';
    }
    const box = document.getElementById('verify-box');
    box.innerHTML = html;
    box.classList.remove('hidden');
}

// ---------- 排序 ----------
function sortScreenTable(key, type, th) {
    if (screenSortKey === key) {
        screenSortDir = -screenSortDir;
    } else {
        screenSortKey = key;
        screenSortDir = (type === 'num') ? -1 : 1;   // 数字默认降序，文本默认升序
    }
    renderScreenTable();
}

function _screenSortVal(r, key) {
    if (key === 'state') return r.sealed ? 0 : (r.broke ? 1 : 2);
    return r[key];
}

function _isEmpty(v) {
    return v === null || v === undefined || v === '';
}

function applyScreenSort(rows) {
    if (!screenSortKey) return rows;
    const key = screenSortKey;
    const dir = screenSortDir;
    return rows.slice().sort(function (a, b) {
        const va = _screenSortVal(a, key);
        const vb = _screenSortVal(b, key);
        if (_isEmpty(va) && _isEmpty(vb)) return 0;
        if (_isEmpty(va)) return 1;      // 空值永远排最后
        if (_isEmpty(vb)) return -1;
        if (typeof va === 'string' || typeof vb === 'string') {
            return String(va).localeCompare(String(vb), 'zh-CN') * dir;
        }
        return (va - vb) * dir;
    });
}

function updateSortIndicators() {
    document.querySelectorAll('.screen-table th.sortable').forEach(function (th) {
        th.classList.remove('sort-asc', 'sort-desc');
        const ind = th.querySelector('.sort-ind');
        if (ind) ind.textContent = ' \u21c5';   // 未排序时提示可点击
    });
    if (!screenSortKey) return;
    const th = document.querySelector('.screen-table th[data-key="' + screenSortKey + '"]');
    if (!th) return;
    th.classList.add(screenSortDir === 1 ? 'sort-asc' : 'sort-desc');
    const ind = th.querySelector('.sort-ind');
    if (ind) ind.textContent = screenSortDir === 1 ? ' \u25b2' : ' \u25bc';
}

function renderScreenTable() {
    const src = (screenResult && screenResult[screenTableKey]) || [];
    const rows = applyScreenSort(src);
    updateSortIndicators();
    const tbody = document.getElementById('screen-table-body');
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty-cell">该分组下暂无股票</td></tr>';
        return;
    }
    let html = '';
    rows.forEach(function (r) {
        const stateText = r.sealed ? '封板' : (r.broke ? '炸板' : '未封板');
        const stateCls = r.sealed ? 'st-sealed' : (r.broke ? 'st-broke' : 'st-none');
        const gcls = r.gainHigh >= 9.9 ? 'up-strong' : 'up';
        html += '<tr>' +
            '<td class="mono">' + escHtml(r.code) + '</td>' +
            '<td class="name-cell"><a class="stock-name-link" onclick="openStockChart(\'' + r.code + '\',\'' + escHtml(r.name) + '\')">' + escHtml(r.name) + '</a></td>' +
            '<td class="num ' + (r.gainClose >= 0 ? 'up' : 'down') + '">' + (r.gainClose >= 0 ? '+' : '') + r.gainClose.toFixed(2) + '%</td>' +
            '<td class="num">' + r.high.toFixed(2) + '</td>' +
            '<td class="num">' + r.close.toFixed(2) + '</td>' +
            '<td class="num ' + gcls + '">+' + r.gainHigh.toFixed(2) + '%</td>' +
            '<td class="mono">' + (r.firstSeal || '无') + '</td>' +
            '<td class="num">' + (r.boards != null ? r.boards : '无') + '</td>' +
            '<td class="dim">' + escHtml(r.sector || '无') + '</td>' +
            '<td><span class="st-tag ' + stateCls + '">' + stateText + '</span></td>' +
            '</tr>';
    });
    tbody.innerHTML = html;
}

function switchScreenTable(key, event) {
    screenTableKey = key;
    document.querySelectorAll('.sub-btn').forEach(function (b) { b.classList.remove('active'); });
    if (event && event.target) {
        const btn = event.target.closest ? (event.target.closest('.sub-btn') || event.target) : event.target;
        btn.classList.add('active');
    }
    renderScreenTable();
}

// ---------- 导出报告 ----------
function exportScreenReport() {
    if (!screenResult) { alert('请先完成一次扫描'); return; }
    window.open('/api/screen/report?date=' + encodeURIComponent(screenResult.target), '_blank');
}

// ---------- 初始化（选股面板） ----------
document.addEventListener('DOMContentLoaded', function () {
    const el = document.getElementById('screen-date');
    if (el) {
        el.addEventListener('change', function () { screenDateTouched = true; });
    }
    ensureScreenDate();
});


// ==================================================================
//                    当前题材热度（第3个功能模块）
// ==================================================================

let themeHeatResult = null;
let themeFetchController = null;

function fmtThemeMoney(v) {
    var n = Number(v || 0);
    if (!n) return '—';
    var sign = n > 0 ? '+' : '';
    if (Math.abs(n) >= 1e8) return sign + (n / 1e8).toFixed(2) + '亿';
    if (Math.abs(n) >= 1e4) return sign + (n / 1e4).toFixed(1) + '万';
    return sign + n.toFixed(0);
}

function fmtThemeRank(v) {
    return (v === null || v === undefined || v === '') ? '未上榜' : '第' + v;
}

function themeStateClass(state) {
    var s = String(state || '');
    if (s.indexOf('核心') >= 0 || s.indexOf('回升') >= 0 || s.indexOf('升温') >= 0 || s.indexOf('回温') >= 0) return 'st-sealed';
    if (s.indexOf('降温') >= 0 || s.indexOf('退潮') >= 0) return 'st-broke';
    return 'st-none';
}

function setThemeLoading(loading) {
    var btn = document.getElementById('theme-btn');
    if (!btn) return;
    btn.disabled = loading;
    btn.querySelector('.btn-text').classList.toggle('hidden', loading);
    btn.querySelector('.btn-loading').classList.toggle('hidden', !loading);
}

function showThemeError(msg) {
    document.getElementById('theme-error-text').textContent = msg;
    document.getElementById('theme-error').classList.remove('hidden');
}

// ---------- 自动发现热门题材 ----------
let hotThemesLoaded = false;
let themeAutoRan = false;

async function loadHotThemes(force, liveNow) {
    if (hotThemesLoaded && !force) return;
    const box = document.getElementById('hot-themes');
    const note = document.getElementById('hot-themes-note');
    if (!box) return;
    box.innerHTML = '<span class="hot-themes-loading">正在采集当日事件并识别题材…（首次约 40 秒）</span>';
    if (note) note.textContent = '';
    const tipEl = document.getElementById('theme-auto-tip');
    if (tipEl) tipEl.classList.add('hidden');

    let r = null;
    let _turl = '/api/event-themes?limit=6&stocks=20';
    if (themeSelectedDate) _turl += '&date=' + encodeURIComponent(themeSelectedDate);
    else if (liveNow) _turl += '&live=1';        // 「看最新 / 重新扫描」= 此刻实时，不走本地存档
    try {
        r = await (await fetch(_turl)).json();
    } catch (e) {
        box.innerHTML = '<span class="hot-themes-loading">加载失败：' + escHtml(e.message) + '</span>';
        return;
    }

    if (!r || !r.success) {
        // 指定日期但库里没有 -> 明确告知，不回退到实时数据
        if (r && r.error === 'NO_DATA') {
            box.innerHTML = '<div class="theme-caveat">' +
                '<b>该交易日没有已保存的题材数据</b><br>' +
                escHtml(r.message || '') +
                '<br><span class="dim">原因通常是：那天是非交易日（数据归到上一个交易日），' +
                '或者程序当天没有运行。</span></div>';
            return;
        }
        // 缺少数据组件：给出明确说明，不回退（回退也依赖同一组件）
        if (r && r.error === 'CLI_MISSING') {
            box.innerHTML = '<div class="theme-caveat">' +
                '<b>⚠️ 题材热度功能不可用</b><br>' +
                escHtml(r.message || '需要本机安装 hithink-finance 数据组件') +
                '<br><span class="dim">你仍可使用：📊 人气榜查询 · 🎯 动态选股（含个股分时/K线/公告）</span>' +
                '</div>';
            return;
        }
        // 非交易日 / 无事件数据时，回退到板块动量榜
        box.innerHTML = '<span class="hot-themes-loading">' +
            escHtml((r && r.error) || '当日无事件数据') + '，已回退到板块动量榜…</span>';
        return fallbackMomentum(note);
    }

    hotThemesLoaded = true;
    topThemeFilter = '';
    box.innerHTML = (r.rows || []).map(function (t, i) {
        const cls = t.netScore >= 0 ? 'up' : 'down';
        const th = (t.topicHeat && t.topicHeat > 0) ? ('话题' + t.topicHeat.toFixed(1) + '万') : '无话题';
        var _ttl = ((t.topics || []).map(function (x) { return x.title; }).join('\n') || '无关联话题');
        if (t.forced) { _ttl = '⚡ 保底入选：' + (t.forced_by || '') + '\n' + _ttl; }
        return '<button class="theme-chip" onclick="filterTopByTheme(\'' + t.name.replace(/'/g, "\\'") + '\',this)" title="' +
               _ttl + '">' +
               '<span class="chip-name">' + (i + 1) + '. ' + escHtml(t.name) + '</span>' +
               '<span class="chip-d1 ' + cls + '">' + (t.verdict || '利好') + ' ' +
                   (t.netScore >= 0 ? '+' : '') + t.netScore + '</span>' +
               '<span class="chip-d5">' + th + ' · ' + t.stockCount + '只人气股</span></button>';
    }).join('');

    renderTopStocks(r);
    renderThemeReasons(r);

    if (note) {
        const _dlab = (r.from_db && r.trade_date)
            ? ('回看交易日 ' + r.trade_date + '（本地存档）')
            : ((r.live_rebuild ? '⚡ 实时（此刻 ' : '数据 ') + (r.as_of || '') + ')');
        note.textContent = _dlab +
            '　|　事件源：热门话题 ' + ((r.sources && r.sources.topics) || 0) + ' 条 + 人气榜 ' +
            r.sources.hotlist + ' 只 + 异动 ' + r.sources.anomaly + ' 只' +
            '　|　识别题材 ' + r.themeCount + ' 个（利好 ' + r.bullCount + ' / 利空 ' + r.bearCount + '）' +
            '　|　热度 = 话题热度(万) + Σ(31−人气榜排名)　|　' + (r.caveat || '');
    }
    if (!themeAutoRan && !force && r.rows && r.rows.length) {
        themeAutoRan = true;
        const t0 = r.rows[0];
        autoRunTopTheme(t0.name, '热度' + t0.heatScore +
            (t0.topicHeat ? '（话题' + t0.topicHeat.toFixed(1) + '万' : '（') +
            ' + 人气' + (t0.popHeat || 0) + '）　利好 +' + t0.netScore);
    }
}

function renderThemeReasons(r) {
    const box = document.getElementById('theme-reasons');
    const body = document.getElementById('theme-reasons-body');
    if (!box || !body) return;
    const list = r.rows || [];
    if (!list.length) { box.classList.add('hidden'); return; }

    body.innerHTML = list.map(function (t, i) {
        // 触发事件（热门话题）
        let ev = (t.topics || []).map(function (x) {
            return '<div class="reason-topic">' +
                '<span class="reason-tag">事件</span>' +
                '<b>' + escHtml(x.title) + '</b>' +
                '<span class="reason-hot">' + (x.hot / 10000).toFixed(1) + '万</span>' +
                (x.desc ? '<div class="reason-desc">' + escHtml(x.desc) + '</div>' : '') +
                '</div>';
        }).join('');
        if (!ev) {
            ev = '<div class="reason-topic"><span class="reason-tag">事件</span>' +
                 '<span class="reason-desc dim">无关联热门话题，仅由人气股异动解读判定</span></div>';
        }
        // 人气股解读
        const sr = (t.stockReasons || []).map(function (s) {
            const rk = s.rank ? ('人气榜第' + s.rank + '名') : '';
            return '<div class="reason-stock"><span class="reason-tag alt">个股</span>' +
                   '<b>' + escHtml(s.name) + '</b>' +
                   (rk ? '<span class="reason-hot">' + rk + '</span>' : '') +
                   '<span class="reason-desc">' + escHtml(s.reason) + '</span></div>';
        }).join('');
        // 利好依据词
        const bw = (t.bullWords || []).map(function (w) {
            return '<span class="bull-word">' + escHtml(w) + '</span>';
        }).join('');

        return '<div class="reason-card">' +
            '<div class="reason-head">' +
              '<span class="reason-name">' + (i + 1) + '. ' + escHtml(t.name) + '</span>' +
              '<span class="reason-verdict">' + (t.verdict || '利好') + ' ' +
                (t.netScore >= 0 ? '+' : '') + t.netScore + '</span>' +
              '<span class="reason-heat">热度 ' + t.heatScore + '</span>' +
            '</div>' +
            '<div class="reason-body">' + ev + sr + '</div>' +
            (bw ? '<div class="reason-words"><span class="reason-tag wide">依据</span>命中利好词：' + bw + '</div>'
                : '<div class="reason-words"><span class="reason-tag wide">依据</span><span class="dim">无命中利好词，由涨停/涨跌方向判定</span></div>') +
            '</div>';
    }).join('');
    box.classList.remove('hidden');
}

let topStocksAll = [];
let topThemeFilter = '';

function renderTopStocks(r) {
    topStocksAll = r.topStocks || [];
    topStockMeta = { rows: (r.rows || []).length, total: r.stockTotal || 0, ranked: r.stockRanked || 0 };
    renderTopStocksTable();
}

function renderTopStocksTable() {
    const tbody = document.getElementById('top-stocks-body');
    const note = document.getElementById('top-stocks-note');
    const bar = document.getElementById('top-filter-bar');
    const lbl = document.getElementById('top-filter-label');
    if (!tbody) return;

    const list = topThemeFilter
        ? topStocksAll.filter(function (s) {
            return (s.themes || []).indexOf(topThemeFilter) >= 0;
          })
        : topStocksAll;

    // 筛选栏
    if (bar && lbl) {
        if (topThemeFilter) {
            lbl.innerHTML = '已筛选：<b>' + escHtml(topThemeFilter) + '</b>　显示 ' + list.length +
                            ' 只（Top50 中属于该题材的股票）';
            bar.classList.remove('hidden');
        } else {
            bar.classList.add('hidden');
        }
    }

    if (!list.length) {
        tbody.innerHTML = '<tr><td colspan="10" class="empty-cell">该题材在 Top50 中没有股票</td></tr>';
    } else {
        tbody.innerHTML = list.map(function (s, i) {
            let hk, cls;
            if (s.hotRank) { hk = '人气榜第 ' + s.hotRank + ' 名'; cls = 'up-strong'; }
            else if (s.trendRank) { hk = '热度第 ' + s.trendRank + ' 名'; cls = 'up'; }
            else { hk = '未上榜'; cls = 'dim'; }
            const badge = s.hotRank ? '<span class="rank-badge rank-hot">' + (i + 1) + '</span>' : (i + 1);
            let chgText = '无', chgCls = 'dim';
            if (s.change !== null && s.change !== undefined && s.change !== '') {
                const cv = Number(s.change);
                if (!isNaN(cv)) {
                    chgCls = cv >= 0 ? 'up' : 'down';
                    chgText = (cv >= 0 ? '+' : '') + cv.toFixed(2) + '%';
                }
            }
            return '<tr>' +
                '<td class="num">' + badge + '</td>' +
                '<td class="mono">' + escHtml(s.ticker) + '</td>' +
                '<td class="name-cell"><a class="stock-name-link" onclick="openStockChart(\'' + s.ticker + '\',\'' + escHtml(s.name) + '\')">' + escHtml(s.name) + '</a></td>' +
                '<td class="num ' + chgCls + '">' + chgText + '</td>' +
                (function () {
                    var mt = (s.market_tags && s.market_tags.length) ? s.market_tags : null;
                    var src = (s.themes || []).join('、');
                    var show = mt ? mt.join('、') : src;
                    var tip = mt ? ('市场标签（同花顺）：' + mt.join('、') + '　|　来源题材：' + src) : ('来源题材：' + src);
                    return '<td class="dim" title="' + escAttr(tip) + '">' + escHtml(show) + '</td>';
                })() +
                '<td class="' + cls + '">' + hk + '</td>' +
                '<td class="num">' + streakTagHtml(s.streak_days) + '</td>' +
                '<td class="num dim">' + (s.themeHeat || 0).toFixed(1) + '</td>' +
                '</tr>';
        }).join('');
    }

    if (note) {
        const meta = topStockMeta || {};
        note.textContent = '合并 ' + (meta.rows || 0) + ' 个利好题材的成分股（每题材取人气靠前的 20 只），去重后 ' +
            (meta.total || 0) + ' 只 → 按人气排名取前 ' + topStocksAll.length + ' 只（其中 ' +
            (meta.ranked || 0) + ' 只有明确人气排名）。点击题材标签可筛选，点击名称可看 K 线。';
    }
}

let topStockMeta = {};

function filterTopByTheme(name, el) {
    topThemeFilter = (topThemeFilter === name) ? '' : name;
    document.querySelectorAll('.theme-chip').forEach(function (c) { c.classList.remove('chip-active'); });
    if (topThemeFilter && el) el.classList.add('chip-active');
    renderTopStocksTable();
    const box = document.querySelector('.top-stocks-box');
    if (box && topThemeFilter) box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function clearTopFilter() {
    topThemeFilter = '';
    document.querySelectorAll('.theme-chip').forEach(function (c) { c.classList.remove('chip-active'); });
    renderTopStocksTable();
}

function runDeepAnalysis() {
    if (topThemeFilter) pickTheme(topThemeFilter);
}

async function fallbackMomentum(note) {
    try {
        const r = await (await fetch('/api/theme-hot?limit=12&lookback=5')).json();
        const box = document.getElementById('hot-themes');
        if (!r.success) { box.innerHTML = '<span class="hot-themes-loading">题材发现失败</span>'; return; }
        hotThemesLoaded = true;
        box.innerHTML = (r.rows || []).map(function (t, i) {
            const d1 = (t.d1 >= 0 ? '+' : '') + t.d1.toFixed(2) + '%';
            const d5 = (t.d5 === null || t.d5 === undefined) ? '—' : ((t.d5 >= 0 ? '+' : '') + t.d5.toFixed(2) + '%');
            return '<button class="theme-chip" onclick="pickTheme(\'' + t.name.replace(/'/g, "\\'") + '\')">' +
                   '<span class="chip-name">' + (i + 1) + '. ' + escHtml(t.name) + '</span>' +
                   '<span class="chip-d1 ' + (t.d1 >= 0 ? 'up' : 'down') + '">' + d1 + '</span>' +
                   '<span class="chip-d5">5日 ' + d5 + '</span></button>';
        }).join('');
        if (note) note.textContent = '数据日期 ' + (r.as_of || '') + '　|　板块动量榜（回退模式）　|　' + (r.note || '');
        if (!themeAutoRan && r.rows && r.rows.length) {
            themeAutoRan = true;
            autoRunTopTheme(r.rows[0].name, '当日 +' + r.rows[0].d1.toFixed(2) + '%');
        }
    } catch (e) { /* ignore */ }
}

function autoRunTopTheme(name, labelText) {
    const el = document.getElementById('theme-input');
    if (el) el.value = name;
    const tip = document.getElementById('theme-auto-tip');
    if (tip) {
        tip.innerHTML = '⚡ 已自动分析当前最热题材「<b>' + escHtml(name) + '</b>」' +
            (labelText ? '（' + escHtml(labelText) + '）' : '') +
            '，也可点击其他标签切换。';
        tip.classList.remove('hidden');
    }
    fetchThemeHeat();
}

function pickTheme(name) {
    const el = document.getElementById('theme-input');
    if (!el) return;
    el.value = name;
    fetchThemeHeat();
    const res = document.getElementById('theme-result');
    if (res) res.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function fetchThemeHeat() {
    var theme = (document.getElementById('theme-input').value || '').trim();
    if (!theme) {
        showThemeError('请输入题材关键词，例如：房贷贴息、房地产、人形机器人');
        return;
    }
    if (themeFetchController) {
        themeFetchController.abort();
    }
    var controller = new AbortController();
    themeFetchController = controller;
    document.getElementById('theme-error').classList.add('hidden');
    document.getElementById('theme-result').classList.add('hidden');
    setThemeLoading(true);
    try {
        var url = '/api/theme-heat?theme=' + encodeURIComponent(theme) + '&limit=20';
        var resp = await fetch(url, { signal: controller.signal });
        var data = await resp.json();
        if (!data.success) throw new Error(data.error || '查询失败');
        themeHeatResult = data;
        renderThemeHeat(data);
    } catch (e) {
        if (e && e.name === 'AbortError') return;
        showThemeError('查询失败：' + e.message);
    } finally {
        if (themeFetchController === controller) {
            themeFetchController = null;
            setThemeLoading(false);
        }
    }
}

function renderThemeHeat(data) {
    document.getElementById('th-theme').textContent = data.theme || '';
    document.getElementById('th-date').textContent = data.as_of || '';
    document.getElementById('th-universe').textContent = (data.universe_count || 0) + ' 只候选，展示 ' + (data.rows || []).length + ' 只';
    document.getElementById('th-elapsed').textContent = (data.elapsed != null ? data.elapsed + ' 秒' : '');
    var tags = (data.matched_indices || []).map(function (x) { return x.name + '(' + x.thscode + ')'; });
    document.getElementById('theme-tags').innerHTML = tags.map(function (t) {
        return '<span class="theme-tag">' + escHtml(t) + '</span>';
    }).join('');

    var tbody = document.getElementById('theme-table-body');
    var rows = data.rows || [];
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="9" class="empty-cell">没有找到可排名股票</td></tr>';
    } else {
        var html = '';
        rows.forEach(function (r) {
            var ch = r.rank_change;
            var chText = (ch === null || ch === undefined) ? '—' : (ch > 0 ? '↑' + ch : (ch < 0 ? '↓' + Math.abs(ch) : '0'));
            var chClass = (ch > 0) ? 'up' : (ch < 0 ? 'down' : 'dim');
            html += '<tr>' +
                '<td class="num"><b>' + (r.display_rank || '') + '</b></td>' +
                '<td class="name-cell"><a class="stock-name-link" onclick="openStockChart(\'' + r.thscode + '\',\'' + escHtml(r.name) + '\')">' + escHtml(r.name) + '</a></td>' +
                '<td class="mono">' + escHtml(r.thscode) + '</td>' +
                '<td class="dim">' + escHtml(r.themes || '') + '</td>' +
                '<td class="num">' + fmtThemeRank(r.current_rank) + '</td>' +
                '<td class="num ' + chClass + '">' + chText + '</td>' +
                '<td class="num ' + (r.lhb_net > 0 ? 'up' : (r.lhb_net < 0 ? 'down' : 'dim')) + '">' + fmtThemeMoney(r.lhb_net) + '</td>' +
                '<td class="num ' + (r.lhb_org > 0 ? 'up' : (r.lhb_org < 0 ? 'down' : 'dim')) + '">' + fmtThemeMoney(r.lhb_org) + '</td>' +
                '<td><span class="st-tag ' + themeStateClass(r.state) + '">' + escHtml(r.state) + '</span></td>' +
                '</tr>';
        });
        tbody.innerHTML = html;
    }

    var foot = document.getElementById('theme-foot');
    foot.innerHTML = '数据来源：同花顺 hithink-finance<br>' +
        '生成时间：' + escHtml(data.generated_at || '') + '<br>' +
        '口径：' + escHtml(data.method || '') + '<br>' +
        '<span class="dim">' + escHtml(data.warning || '') + '</span>';
    document.getElementById('theme-result').classList.remove('hidden');
}


// ===========================================================================
//  数据管理页
// ===========================================================================
function dbMsg(text, kind) {
    const el = document.getElementById('db-message');
    if (!el) return;
    el.className = 'db-message' + (kind ? ' ' + kind : '');
    el.textContent = text;
    el.classList.remove('hidden');
    clearTimeout(dbMsg._t);
    dbMsg._t = setTimeout(function () { el.classList.add('hidden'); }, 8000);
}

async function loadDbOverview() {
    // 「数据表一览」已从页面移除，tb 可能为 null，不能因此中断卡片刷新
    const tb = document.getElementById('db-table-body');
    if (tb) tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#8a8a8a;">加载中…</td></tr>';
    try {
        const r = await (await fetch('/api/db/overview')).json();
        if (!r.success) throw new Error(r.error || '加载失败');
        const o = r.overview || {};
        document.getElementById('db-path').textContent = o.db_path || '-';
        document.getElementById('db-size').textContent = (o.size_mb != null ? o.size_mb + ' MB' : '-');
        let total = 0;
        (o.tables || []).forEach(function (t) { total += (t.rows || 0); });
        document.getElementById('db-rows').textContent = total.toLocaleString();
        document.getElementById('db-days').textContent = (o.kline_days != null ? o.kline_days : '-');
        const job = o.auto_fetch || {};
        document.getElementById('db-job').textContent = job.enabled ? job.time_text : '已关闭';
        const ed = document.getElementById('db-export-date');
        if (ed && !ed.value) {
            // 优先用"交易日"字段，避免取到资讯日期之类的非交易日
            const PREF = ['hotlist_snapshot', 'daily_kline', 'screening_result',
                          'limit_up_pool', 'theme_heat_snapshot'];
            const byTable = {};
            (o.tables || []).forEach(function (t) { byTable[t.table] = t; });
            let latest = null;
            for (let i = 0; i < PREF.length; i++) {
                const t = byTable[PREF[i]];
                if (t && t.date_end) { latest = t.date_end; break; }
            }
            if (!latest) {
                (o.tables || []).forEach(function (t) {
                    if (t.date_end && (!latest || t.date_end > latest)) latest = t.date_end;
                });
            }
            if (latest) { ed.value = latest; loadExportInfo(); }
        }

        if (tb) {
            let html = '';
            (o.tables || []).forEach(function (t) {
                const range = (t.date_start ? (t.date_start + ' ~ ' + t.date_end) : '—');
                const btn = (t.rows > 0)
                    ? '<a class="db-link" onclick="cleanupTable(\'' + t.table + '\')">清空</a>'
                    : '<span class="dim">—</span>';
                html += '<tr>'
                    + '<td><code>' + t.table + '</code></td>'
                    + '<td>' + escHtml(t.label || '') + '</td>'
                    + '<td class="num">' + (t.rows || 0).toLocaleString() + '</td>'
                    + '<td class="db-range">' + range + '</td>'
                    + '<td>' + btn + '</td>'
                    + '</tr>';
            });
            tb.innerHTML = html || '<tr><td colspan="5" style="text-align:center;color:#8a8a8a;">暂无数据</td></tr>';
        }
    } catch (e) {
        if (tb) tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#ff6b6b;">' + escHtml(e.message) + '</td></tr>';
    }
}

const _JOB_LABEL = { 'morning': '早盘', 'close': '收盘' };

async function loadDbJob() {
    const box = document.getElementById('db-job-info');
    if (!box) return;
    try {
        const r = await (await fetch('/api/db/job-status')).json();
        if (!r.success) throw new Error(r.error || '加载失败');
        const j = r.job || {};
        let html = '';
        html += '<div class="db-job-line">状态：' + (j.enabled ? '已启用' : '已关闭') + '</div>';
        const sched = j.schedules || [];
        if (sched.length) {
            html += '<div class="db-job-line">时段：' + sched.map(function (s) {
                return '<span class="db-chip">' + (_JOB_LABEL[s.name] || s.name) + ' ' + s.time_text
                    + ' · ' + (s.mode === 'light' ? '轻量' : '全量') + '</span>';
            }).join('') + '</div>';
        } else {
            html += '<div class="db-job-line">时段：每天 ' + (j.time_text || '-') + '</div>';
        }
        html += '<div class="db-job-line">后台线程：' + (j.thread_alive ? '运行中' : '未运行')
             + (j.manual_running ? '　<b class="warn-text">正在执行 ' + escHtml(j.running_job || '') + '…</b>' : '')
             + '</div>';
        const p = j.pool || {};
        if (p.enabled) {
            html += '<div class="db-job-line dim">连接池：上限 ' + p.size + '，已建 ' + p.created
                 + '，空闲 ' + p.idle + '，使用中 ' + p.in_use + '，复用 ' + p.reused + ' 次</div>';
        } else {
            html += '<div class="db-job-line dim">连接池：' + escHtml(p.note || '未启用（SQLite 模式）') + '</div>';
        }
        const hist = (j.history || []).map(function (h) {
            const jn = (h.task_type || '').replace('job:', '');
            const tag = _JOB_LABEL[jn] || (jn === 'daily_job' ? '收盘' : jn);
            return '<div class="db-job-line">· <b>' + escHtml(tag) + '</b> '
                + escHtml(h.trade_date || '-') + ' <b>' + escHtml(h.status || '') + '</b> '
                + escHtml((h.detail || '').slice(0, 90))
                + ' <span class="dim">' + escHtml(h.finished_at || '') + '</span></div>';
        }).join('');
        html += hist ? '<div class="db-job-line db-job-hist-title">最近执行记录：</div>' + hist
                     : '<div class="db-job-line dim">暂无执行记录</div>';
        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}

async function runDailyJob() {
    const sel = document.getElementById('db-job-select');
    const job = sel ? sel.value : 'close';
    const tip = job === 'morning'
        ? '立即执行一次「早盘·轻量」任务？（只抓人气榜，约 10 秒）'
        : '立即执行一次「收盘·全量」任务？（日历+人气榜+全市场扫描+题材+校验+推送，约 1~3 分钟）';
    if (!confirm(tip + '\n期间可继续使用其他页签。')) return;
    try {
        const r = await (await fetch('/api/db/run-job', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ job: job })
        })).json();
        if (!r.success) throw new Error(r.error || '启动失败');
        dbMsg('已启动「' + (_JOB_LABEL[r.job] || r.job) + '」任务，稍后点「刷新」查看结果', 'ok');
        setTimeout(loadDbJob, 3000);
        setTimeout(function () { loadDbJob(); loadDbOverview(); }, 30000);
    } catch (e) {
        dbMsg('启动失败：' + e.message, 'err');
    }
}

function cleanupTable(table) {
    if (!confirm('确定清空表 ' + table + ' 吗？该操作不可恢复。')) return;
    doCleanup({ scope: 'table', table: table });
}

function cleanupDb(scope) {
    const body = { scope: scope };
    if (scope === 'minute') {
        body.keep_days = parseInt(document.getElementById('db-keep-days').value, 10);
    } else if (scope === 'before') {
        const d = document.getElementById('db-before-date').value;
        if (!d) { dbMsg('请先选择日期', 'warn'); return; }
        body.before_date = d;
    }
    const tip = (scope === 'all')
        ? '确定清空全部业务数据吗？该操作不可恢复！'
        : '确定执行清理吗？';
    if (!confirm(tip)) return;
    doCleanup(body);
}

async function doCleanup(body) {
    try {
        const r = await (await fetch('/api/db/cleanup', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        })).json();
        if (!r.success) throw new Error(r.error || '清理失败');
        dbMsg('已清理 ' + (r.deleted || 0) + ' 条 —— ' + (r.detail || ''), 'ok');
        await loadDbOverview();
        loadDbCoverage();
    } catch (e) {
        dbMsg('清理失败：' + e.message, 'err');
    }
}


// ---- 数据完整性校验 ----
async function loadIntegrity() {
    const box = document.getElementById('db-integrity');
    if (!box) return;
    box.innerHTML = '<span class="dim">校验中…</span>';
    try {
        const r = await (await fetch('/api/db/integrity')).json();
        if (!r.success) throw new Error(r.error || '校验失败');
        const ic = r.integrity || {};
        let html = '<div class="db-ic-head">交易日 <b>' + escHtml(ic.trade_date || '-') + '</b> — ' +
            (ic.ok ? '<span class="ic-ok">✔ 数据齐全</span>' : '<span class="ic-bad">✘ 存在缺失</span>') + '</div>';
        html += '<table class="stock-table db-table"><thead><tr>' +
            '<th>校验项</th><th class="num">期望</th><th class="num">实际</th><th>结果</th>' +
            '</tr></thead><tbody>';
        (ic.items || []).forEach(function (it) {
            const sign = it.mode === 'exact' ? '=' : '≥';
            html += '<tr><td>' + escHtml(it.label) + '</td><td class="num">' + sign + it.expected +
                '</td><td class="num">' + it.actual + '</td><td>' +
                (it.ok ? '<span class="ic-ok">通过</span>' : '<span class="ic-bad">缺失</span>') + '</td></tr>';
        });
        html += '</tbody></table>';
        if (ic.issues && ic.issues.length) {
            html += '<div class="db-ic-issues">⚠ 缺失项：' + ic.issues.map(escHtml).join('；') + '</div>';
        }
        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}

// ---- 通知推送 ----
const _NOTIFY_NAMES = { email: '邮件', wecom: '企业微信', dingtalk: '钉钉',
                        serverchan: 'Server酱(微信)', webhook: '通用Webhook' };

async function loadNotifyStatus() {
    const box = document.getElementById('db-notify');
    if (!box) return;
    try {
        const r = await (await fetch('/api/notify/status')).json();
        if (!r.success) throw new Error(r.error || '加载失败');
        const n = r.notify || {};
        const chips = (n.channels || []).map(function (c) {
            return '<span class="db-chip">' + (_NOTIFY_NAMES[c] || c) + '</span>';
        }).join('');
        let html = '';
        html += '<div class="db-job-line">状态：' + (n.enabled ? '已启用' : '已关闭') +
                '　发送策略：' + (n.notify_on === 'issues_only' ? '仅校验不通过时' : '每次都发') + '</div>';
        html += '<div class="db-job-line">已配置通道：' + (chips || '<span class="dim">无</span>') + '</div>';
        html += '<div class="db-job-line dim">配置文件：' + escHtml(n.config_path || '') +
                (n.config_exists ? '（已找到）' : '（未创建）') + '</div>';
        if (n.email_host) {
            html += '<div class="db-job-line dim">邮件：' + escHtml(n.email_host) + ' → ' +
                    (n.email_to || []).map(escHtml).join(', ') + '</div>';
        }
        if (!(n.channels || []).length) {
            html += '<div class="db-ic-issues">尚未配置通知通道。在 exe 同目录创建 notify.json 即可开启，' +
                    '模板见「使用说明.txt」。</div>';
        }
        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}

async function sendTestNotify() {
    const box = document.getElementById('db-notify');
    if (box) box.innerHTML = '<span class="dim">发送中…</span>';
    try {
        const r = await (await fetch('/api/notify/test', { method: 'POST' })).json();
        if (!r.success) throw new Error(r.error || '发送失败');
        const res = r.results || [];
        const txt = res.map(function (x) {
            return (x.name || x.channel) + '：' + (x.ok ? '成功' : ('失败 ' + (x.error || '')));
        }).join('　');
        const allOk = res.length > 0 && res.every(function (x) { return x.ok; });
        dbMsg('测试通知 —— ' + txt, allOk ? 'ok' : 'err');
        loadNotifyStatus();
    } catch (e) {
        dbMsg('发送失败：' + e.message, 'err');
        if (box) box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}


// ---- 数据导出 ----
async function loadExportInfo() {
    const d = document.getElementById('db-export-date');
    const box = document.getElementById('db-export-info');
    if (!d || !box || !d.value) return;
    box.innerHTML = '<span class="dim">查询中…</span>';
    try {
        const r = await (await fetch('/api/db/export-info?date=' + encodeURIComponent(d.value))).json();
        if (!r.success) throw new Error(r.error || '查询失败');
        const list = (r.tables || []).filter(function (t) { return t.rows > 0; });
        if (!list.length) { box.innerHTML = '<span class="dim">该日期暂无可导出数据</span>'; return; }
        box.innerHTML = '该日期可导出：' + list.map(function (t) {
            return '<span class="db-chip">' + escHtml(t.label) + ' ' + t.rows + '</span>';
        }).join('');
    } catch (e) {
        box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}

function exportDb(fmt) {
    const d = document.getElementById('db-export-date');
    const t = document.getElementById('db-export-table');
    const date = d ? d.value : '';
    if (!date) { dbMsg('请先选择要导出的日期', 'warn'); return; }
    const table = t ? t.value : '';
    if (fmt === 'csv' && !table) {
        dbMsg('CSV 一次只能导出一张表：请在上方选一个表；导出全部请用「导出 Excel」', 'warn');
        return;
    }
    const url = '/api/db/export?date=' + encodeURIComponent(date) + '&format=' + fmt
              + (table ? '&table=' + encodeURIComponent(table) : '');
    window.location.href = url;
    dbMsg('已开始下载…', 'ok');
}


// ---- 数据覆盖日历 ----
function escAttr(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/"/g, '&quot;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '；');
}

async function loadDbCoverage() {
    const box = document.getElementById('db-coverage');
    if (!box) return;
    const tSel = document.getElementById('db-cov-table');
    const table = tSel ? tSel.value : '';
    const nSel = document.getElementById('db-coverage-n');
    const n = nSel ? nSel.value : 30;
    box.innerHTML = '<span class="dim">加载中…</span>';
    try {
        let days = [], head = '';
        if (!table) {
            // ① 全部数据：按交易日历，标出 完整 / 部分 / 无
            const r = await (await fetch('/api/db/coverage?n=' + n)).json();
            if (!r.success) throw new Error(r.error || '加载失败');
            const cov = r.coverage || {};
            days = cov.days || [];
            if (!days.length) { box.innerHTML = '<span class="dim">暂无交易日历，请先执行一次抓取</span>'; return; }
            const full = days.filter(function (d) { return d.level === 'full'; }).length;
            const partial = days.filter(function (d) { return d.level === 'partial'; }).length;
            const L = cov.levels || {};
            head = '<div class="db-cov-note">共 ' + days.length + ' 个交易日（'
                + escHtml(cov.from || '') + ' ~ ' + escHtml(cov.to || '') + '）　·　'
                + '<span class="db-cov-legend lv-full">完整 ' + full + ' 天</span>'
                + '<span class="db-cov-legend lv-partial">部分 ' + partial + ' 天</span>'
                + '<span class="db-cov-legend lv-none">无/极少 ' + (days.length - full - partial) + ' 天</span><br>'
                + '<span class="db-cov-legend lv-full">绿</span>' + escHtml(L.full || '')
                + '　<span class="db-cov-legend lv-partial">黄</span>' + escHtml(L.partial || '')
                + '　<span class="db-cov-legend lv-none">灰</span>' + escHtml(L.none || '') + '<br>'
                + '点任意日期 → 回看当天的人气榜</div>';
        } else {
            // ② 单张表：看该表实际存了哪些日期
            const r = await (await fetch('/api/db/dates?table=' + encodeURIComponent(table) +
                                         '&limit=' + n)).json();
            if (!r.success) throw new Error(r.error || '加载失败');
            const label = (tSel && tSel.selectedIndex >= 0)
                ? tSel.options[tSel.selectedIndex].textContent.trim() : table;
            days = (r.dates || []).map(function (x) {
                return { trade_date: x.date, count: x.rows, level: 'full', tables: {} };
            });
            if (!days.length) {
                box.innerHTML = '<span class="dim">「' + escHtml(label) + '」还没有数据</span>';
                return;
            }
            head = '<div class="db-cov-note">「<b>' + escHtml(label) + '</b>」共 '
                + days.length + ' 个有数据的日期　·　点任意日期 → 回看当天的人气榜</div>';
        }

        let html = head + '<div class="db-cov-grid">';
        days.forEach(function (d) {
            const inner = Object.keys(d.tables || {}).map(function (k) {
                return k + ': ' + d.tables[k];
            }).join('  ');
            const tipTxt = '点击回看 ' + d.trade_date
                + (inner ? '　|　' + inner : (d.count ? '　|　共 ' + d.count + ' 条' : ''));
            html += '<span class="db-cov-day ' + d.level + '" style="cursor:pointer" '
                + 'title="' + escAttr(tipTxt) + '" '
                + 'onclick="gotoHistory(\'' + d.trade_date + '\')">'
                + escHtml(d.trade_date) + '</span>';
        });
        html += '</div>';
        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}


// ==================== 历史回看 ====================
function showEmptyHistory(result) {
    const info = document.getElementById('trading-day-info');
    if (info) info.classList.remove('hidden');
    const dayEl = document.getElementById('trading-day');
    if (dayEl) dayEl.textContent = result.trading_day || '';
    const msgEl = document.getElementById('trading-day-message');
    if (msgEl) msgEl.textContent = result.message || '';

    const box = document.getElementById('empty-history');
    if (!box) return;
    box.innerHTML =
        '<b>该交易日没有已保存的人气榜数据</b><br>' +
        escHtml(result.message || '') +
        '<br><span class="dim">常见原因：① 那天是周末/节假日（数据会归到上一个交易日）；' +
        '② 程序当天没有运行（人气榜只有实时数据，错过就补不回来）。</span>';
    box.classList.remove('hidden');
}

let hotlistSelectedDate = '';
let hotlistLatestDate = '';

function clearHotlistDate() {
    hotlistSelectedDate = '';
    const box = document.getElementById('hotlist-day-chips');
    if (box) box.classList.add('hidden');
    const sum = document.getElementById('hotlist-range-summary');
    if (sum) sum.classList.add('hidden');
    fetchData('');
}

function quickRange(n) {
    const end = hotlistLatestDate || ymdLocal(new Date());
    const d = new Date(end + 'T00:00:00');
    d.setDate(d.getDate() - (n - 1));
    const start = ymdLocal(d);
    const s = document.getElementById('hotlist-date-start');
    const e = document.getElementById('hotlist-date-end');
    if (s) s.value = start;
    if (e) e.value = end;
    loadHotlistRange(start, end);
}

async function onHotlistRangeChange() {
    const s = document.getElementById('hotlist-date-start');
    const e = document.getElementById('hotlist-date-end');
    if (!s || !e) return;
    let a = s.value, b = e.value;
    if (a && b && a > b) { const t = a; a = b; b = t; s.value = a; e.value = b; }
    if (!a || !b) return;
    await loadHotlistRange(a, b);
}

let _rangeSeq = 0;

async function loadHotlistRange(start, end) {
    const box = document.getElementById('hotlist-day-chips');
    const sum = document.getElementById('hotlist-range-summary');
    // 防竞态：连续改范围时，只有最后一次请求的结果允许渲染
    const seq = ++_rangeSeq;
    if (box) { box.classList.remove('hidden'); box.innerHTML = '<span class="dim">加载中…</span>'; }
    try {
        const r = await (await fetch('/api/hotlist/range?start=' + encodeURIComponent(start) +
                                     '&end=' + encodeURIComponent(end))).json();
        if (seq !== _rangeSeq) return;          // 已被更新的请求取代，丢弃本次结果
        if (!r.success) throw new Error(r.error || '加载失败');
        const y = r.summary || {};
        if (sum) {
            sum.classList.remove('hidden');
            sum.innerHTML = escHtml(r.start) + ' ~ ' + escHtml(r.end) +
                '　共 <b>' + y.total + '</b> 个交易日　·　' +
                '有数据 <b class="ic-ok">' + y.with_data + '</b>' +
                '（其中仅回补 ' + y.backfill_only + '）　·　' +
                '无数据 <b class="ic-bad">' + y.missing + '</b>' +
                '　<span class="dim">点下方日期查看当天榜单</span>';
        }
        if (!r.days.length) { box.innerHTML = '<span class="dim">该区间内没有交易日</span>'; return; }
        box.innerHTML = r.days.map(function (d) {
            const cls = d.has ? (d.backfill ? 'has bf' : 'has') : 'none';
            const sel = (d.date === hotlistSelectedDate) ? ' sel' : '';
            const tip = d.date + '　' + (d.has ? (d.source || '有数据') : '无数据');
            return '<span class="day-chip ' + cls + sel + '" title="' + escAttr(tip) +
                   '" onclick="pickHotlistDay(\'' + d.date + '\')">' +
                   escHtml(d.date.slice(5)) + '</span>';
        }).join('');
    } catch (err) {
        if (seq !== _rangeSeq) return;
        if (box) box.innerHTML = '<span class="dim">' + escHtml(err.message) + '</span>';
    }
}

function pickHotlistDay(date) {
    hotlistSelectedDate = date;
    document.querySelectorAll('#hotlist-day-chips .day-chip').forEach(function (c) {
        c.classList.toggle('sel', c.textContent === date.slice(5));
    });
    fetchData(date);
}

// 首次加载后，自动填一个"最近 30 天"的范围
function initHotlistRangeOnce() {
    const s = document.getElementById('hotlist-date-start');
    const e = document.getElementById('hotlist-date-end');
    if (!s || !e || s.value || e.value || !hotlistLatestDate) return;
    const d = new Date(hotlistLatestDate + 'T00:00:00');
    d.setDate(d.getDate() - 29);
    s.value = ymdLocal(d);
    e.value = hotlistLatestDate;
    loadHotlistRange(s.value, e.value);
}

let themeSelectedDate = '';

function clearThemeDate() {
    themeSelectedDate = '';
    hotThemesLoaded = false;
    loadHotThemes(true, true);      // 「看最新」= 此刻实时（不走存档）
    loadThemeDates();
}

function pickThemeDate(date) {
    themeSelectedDate = date || '';
    hotThemesLoaded = false;
    loadHotThemes(true);
    loadThemeDates();
}

async function loadThemeDates() {
    const box = document.getElementById('theme-date-chips');
    if (!box) return;
    try {
        const r = await (await fetch('/api/themes/dates?limit=60')).json();
        if (!r.success) throw new Error(r.error || '加载失败');
        const ds = r.dates || [];
        if (!ds.length) { box.innerHTML = '<span class="dim">（暂无已保存的题材数据）</span>'; return; }
        box.innerHTML = ds.map(function (d) {
            const sel = (d === themeSelectedDate) ? ' sel' : '';
            return '<span class="day-chip has' + sel + '" style="cursor:pointer" ' +
                   'title="点击查看 ' + escAttr(d) + ' 的题材数据" ' +
                   'onclick="pickThemeDate(\'' + d + '\')">' + escHtml(d) + '</span>';
        }).join('');
    } catch (e) {
        box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}

// 从「数据管理」的日期块跳到该交易日的回看
function gotoHistory(date) {
    document.querySelectorAll('.mode-btn').forEach(function (b) { b.classList.remove('active'); });
    const mb = document.getElementById('mode-hotlist');
    if (mb) mb.classList.add('active');
    ['hotlist', 'screen', 'theme', 'db'].forEach(function (m) {
        const el = document.getElementById('panel-' + m);
        if (el) el.classList.toggle('hidden', m !== 'hotlist');
    });
    hotlistSelectedDate = date || '';
    const s = document.getElementById('hotlist-date-start');
    const e = document.getElementById('hotlist-date-end');
    if (date && s && e) {
        const d = new Date(date + 'T00:00:00');
        const d0 = new Date(d); d0.setDate(d0.getDate() - 29);
        s.value = ymdLocal(d0);
        e.value = ymdLocal(d);
        loadHotlistRange(s.value, e.value);
    }
    fetchData(date || '');
    try { window.scrollTo({ top: 0, behavior: 'smooth' }); } catch (e) { window.scrollTo(0, 0); }
}


// ==================== 历史回补（东方财富） ====================
async function loadBackfillMissing() {
    const box = document.getElementById('bf-info');
    if (!box) return;
    const sel = document.getElementById('bf-days');
    const days = sel ? sel.value : 20;
    box.innerHTML = '<span class="dim">检查中…</span>';
    try {
        const r = await (await fetch('/api/backfill/missing?days=' + days)).json();
        if (!r.success) throw new Error(r.error || '检查失败');
        window._bfMissing = r.dates || [];
        const chips = function (arr) {
            return arr.map(function (d) { return '<span class="db-chip">' + escHtml(d) + '</span>'; }).join('');
        };
        let head = '<div>最近 ' + days + ' 个交易日：' +
            '<span class="db-cov-legend lv-full">实时抓取 ' + (r.live || []).length + '</span>' +
            '<span class="db-cov-legend lv-partial">仅回补 ' + (r.backfilled || []).length + '</span>' +
            '<span class="db-cov-legend lv-none">可回补 ' + (r.missing || []).length + '</span>' +
            '<span class="db-cov-legend lv-none">超出范围 ' + (r.out_of_range || []).length + '</span></div>';
        if (r.api_from) {
            head += '<div class="dim" style="margin-top:4px">接口可回溯范围：' +
                escHtml(r.api_from) + ' ~ ' + escHtml(r.api_to) + '</div>';
        }
        if ((r.backfilled || []).length) {
            head += '<div class="dim" style="margin-top:6px">已回补（来源：东方财富）：' + chips(r.backfilled) + '</div>';
        }
        if ((r.out_of_range || []).length) {
            head += '<div class="dim" style="margin-top:6px">超出接口范围（补不了）：' + chips(r.out_of_range) + '</div>';
        }
        if (!r.dates.length) {
            box.innerHTML = head + '<div class="ic-ok" style="margin-top:6px">✔ 没有"可以回补但还没补"的交易日了</div>';
            return;
        }
        box.innerHTML = head +
            '<div style="margin-top:6px">可以回补 <b class="ic-bad">' + r.dates.length + '</b> 天：' +
            chips(r.dates) + '</div>' +
            '<div class="dim" style="margin-top:6px">点「开始回补」用<b>东方财富</b>的历史接口把它们补回来' +
            '（扫描全市场约 1 分钟，一次扫描可覆盖全部日期）</div>' +
            '<div class="dim">⚠ 回补数据来自东方财富人气榜，与同花顺算法不同，<b>排名会有差异</b>；' +
            '页面会标明来源，且<b>不会覆盖</b>当天真实抓取的数据。</div>';
    } catch (e) {
        box.innerHTML = '<span class="dim">' + escHtml(e.message) + '</span>';
    }
}

async function runBackfill() {
    if (!confirm('开始回补历史人气榜？\n\n· 会扫描全市场约 5200 只股票（约 1 分钟）\n' +
                 '· 数据来自东方财富人气榜，与同花顺排名会有差异\n' +
                 '· 不会覆盖已有的实时数据\n\n确定继续？')) return;
    const sel = document.getElementById('bf-days');
    const days = sel ? Number(sel.value) : 20;
    const box = document.getElementById('bf-info');
    try {
        const r = await (await fetch('/api/backfill/run', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ days: days })
        })).json();
        if (!r.success) throw new Error(r.error || '启动失败');
        box.innerHTML = '<span class="warn-text">已启动，正在扫描全市场…</span>';
        pollBackfill();
    } catch (e) {
        box.innerHTML = '<span class="ic-bad">' + escHtml(e.message) + '</span>';
    }
}

async function pollBackfill() {
    const box = document.getElementById('bf-info');
    for (let i = 0; i < 120; i++) {
        await new Promise(function (res) { setTimeout(res, 3000); });
        let st = null;
        try { st = (await (await fetch('/api/backfill/status')).json()).state; } catch (e) { continue; }
        if (!st) continue;
        if (st.running) {
            box.innerHTML = '<span class="warn-text">回补中… ' + escHtml(st.progress || '') + '</span>';
            continue;
        }
        const res = st.result || {};
        if (res.error) { box.innerHTML = '<span class="ic-bad">回补失败：' + escHtml(res.error) + '</span>'; return; }
        const rr = res.result || {};
        const keys = Object.keys(rr).sort();
        if (!keys.length) {
            box.innerHTML = '<span class="dim">' + escHtml(res.note || '没有需要回补的日期') + '</span>';
            return;
        }
        box.innerHTML = '<div class="ic-ok">✔ 回补完成' +
            (res.elapsed ? '（用时 ' + res.elapsed + ' 秒）' : '') + '</div>' +
            keys.map(function (d) { return '<span class="db-chip">' + escHtml(d) + ' → ' + rr[d] + ' 条</span>'; }).join('') +
            '<div class="dim" style="margin-top:6px">现在可以在「人气榜查询」页选这些日期回看了</div>';
        loadDbCoverage(); loadDbOverview();
        return;
    }
    box.innerHTML = '<span class="dim">回补还在进行，稍后点「检查缺失」查看结果</span>';
}

// ==================== 模块5：题材股多日对照 ====================
let multiDates = [];          // 当前选中的日期（降序）
let multiAvailable = [];      // 可选的日期
let multiData = null;
let multiLoaded = false;
let multiView = 'date';      // 'date' = 按日期并列（默认）; 'stock' = 按股票对照
const MULTI_MAX = 6;          // 最多同时对照几个日期

async function loadMulti(force) {
    const note = document.getElementById('multi-note');
    if (multiLoaded && !force && multiDates.length) return;
    const q = multiDates.length ? ('?dates=' + encodeURIComponent(multiDates.join(','))) : '';
    if (note) note.textContent = '正在读取各交易日的题材数据…';
    let r;
    try {
        r = await (await fetch('/api/themes/multi' + q)).json();
    } catch (e) {
        if (note) note.textContent = '加载失败：' + e.message;
        return;
    }
    if (!r || !r.success) {
        document.getElementById('multi-thead').innerHTML = '';
        document.getElementById('multi-body').innerHTML =
            '<tr><td class="empty-cell">' + escHtml((r && (r.message || r.error)) || '暂无数据') + '</td></tr>';
        document.getElementById('multi-date-chips').innerHTML = '';
        if (note) note.textContent = '';
        return;
    }
    multiData = r;
    multiAvailable = r.available || [];
    multiDates = r.dates || [];
    multiLoaded = true;
    renderMulti();
}

function toggleMultiDate(d) {
    const i = multiDates.indexOf(d);
    if (i >= 0) {
        if (multiDates.length <= 1) { alert('至少保留一个日期'); return; }
        multiDates.splice(i, 1);
    } else {
        if (multiDates.length >= MULTI_MAX) { alert('最多同时对照 ' + MULTI_MAX + ' 个日期'); return; }
        multiDates.push(d);
        multiDates.sort(function (x, y) { return x < y ? 1 : -1; });   // 日期新的在前
    }
    loadMulti(true);
}

function renderMultiByStock() {
    if (!multiData) return;
    const dates = multiData.dates || [];
    const rows = multiData.rows || [];
    const thead = document.getElementById('multi-thead');
    const tbody = document.getElementById('multi-body');
    const note = document.getElementById('multi-note');

    let h1 = '<tr><th class="grp" colspan="2">股票</th>';
    let h2 = '<tr><th>代码</th><th>名称</th>';
    dates.forEach(function (d) {
        h1 += '<th class="grp" colspan="2">' + escHtml(d) + '</th>';
        h2 += '<th class="num">排名</th><th class="num">涨跌幅</th>';
    });
    h1 += '</tr>'; h2 += '</tr>';
    thead.innerHTML = h1 + h2;

    const cols = 2 + dates.length * 2;
    if (!rows.length) {
        tbody.innerHTML = '<tr><td colspan="' + cols + '" class="empty-cell">暂无数据</td></tr>';
    } else {
        tbody.innerHTML = rows.map(function (r) {
            let tds = '<td class="mono">' + escHtml(r.ticker) + '</td>' +
                '<td class="name-cell"><a class="stock-name-link" onclick="openStockChart(\'' +
                r.ticker + '\',\'' + escHtml(r.name) + '\')">' + escHtml(r.name) + '</a></td>';
            dates.forEach(function (d) {
                const it = (r.by_date || {})[d];
                if (!it || !it.rank) {
                    tds += '<td class="num miss">—</td><td class="num miss">—</td>';
                    return;
                }
                const rk = it.rank <= 10 ? 'up-strong' : '';
                let txt = '—', cls = 'miss';
                const chg = it.change;
                if (chg !== null && chg !== undefined && chg !== '') {
                    const v = Number(chg);
                    if (!isNaN(v)) {
                        cls = v >= 0 ? 'up' : 'down';
                        txt = (v >= 0 ? '+' : '') + v.toFixed(2) + '%';
                    }
                }
                tds += '<td class="num ' + rk + '">' + it.rank + '</td>' +
                       '<td class="num ' + cls + '">' + txt + '</td>';
            });
            return '<tr>' + tds + '</tr>';
        }).join('');
    }
}

// ---- 视图切换 + 公共渲染（日期块 / 股票对照）----
function switchMultiView(v, ev) {
    multiView = v || 'date';
    document.querySelectorAll('#multi-view-tabs .sub-btn').forEach(function (b) { b.classList.remove('active'); });
    if (ev && ev.target) {
        const btn = ev.target.closest ? (ev.target.closest('.sub-btn') || ev.target) : ev.target;
        btn.classList.add('active');
    }
    renderMulti();
}

function renderMulti() {
    if (!multiData) return;
    const tbl = document.querySelector('.multi-table');
    if (tbl) tbl.className = 'stock-table multi-table' + (multiView === 'stock' ? '' : ' by-date');
    if (multiView === 'stock') renderMultiByStock();
    else renderMultiByDate();
    renderMultiChips();
    renderMultiNote();
}

function renderMultiChips() {
    const box = document.getElementById('multi-date-chips');
    if (!box) return;
    const dates = multiData.dates || [];
    box.innerHTML = (multiAvailable || []).map(function (d) {
        const on = dates.indexOf(d) >= 0 ? ' sel' : '';
        return '<span class="day-chip has' + on + '" style="cursor:pointer" title="点击' +
               (on ? '取消' : '加入') + '对照" onclick="toggleMultiDate(\'' + d + '\')">' +
               escHtml(d) + '</span>';
    }).join('');
}

function renderMultiNote() {
    const note = document.getElementById('multi-note');
    if (!note) return;
    const dates = multiData.dates || [];
    const pd = multiData.per_date || {};
    const cnt = dates.map(function (d) {
        return d + '（' + ((pd[d] || {}).count || 0) + ' 只）';
    }).join('　|　');
    const lim = multiData.limit || 20;
    const tail = (multiView === 'stock')
        ? '同一只股票一行，每列是该日的名次与涨跌幅　|　「—」= 该日不在前 ' + lim + ' 名'
        : '每个日期各自一块「排名 | 代码 | 名称 | 涨跌幅」（各取前 ' + lim +
          ' 名），横向并排　|　「—」= 该日不足 ' + lim + ' 只';
    note.textContent = '对照 ' + dates.length + ' 个交易日：' + cnt + '　|　' + tail +
        '（个别股票若本地没有当日行情，涨跌幅显示「—」）';
}

// 按日期并列：每个日期一块独立的「排名 | 代码 | 名称 | 涨跌幅」
function renderMultiByDate() {
    const dates = multiData.dates || [];
    const lists = multiData.by_date_list || {};
    const thead = document.getElementById('multi-thead');
    const tbody = document.getElementById('multi-body');

    let h1 = '<tr>', h2 = '<tr>';
    dates.forEach(function (d, i) {
        const sep = i > 0 ? ' sep' : '';
        h1 += '<th class="grp' + sep + '" colspan="4">' + escHtml(d) + '</th>';
        h2 += '<th class="num' + sep + '">排名</th><th>代码</th><th>名称</th><th class="num">涨跌幅</th>';
    });
    thead.innerHTML = h1 + '</tr>' + h2 + '</tr>';

    let maxN = 0;
    dates.forEach(function (d) { maxN = Math.max(maxN, (lists[d] || []).length); });
    if (!maxN) {
        tbody.innerHTML = '<tr><td colspan="' + (dates.length * 4) + '" class="empty-cell">暂无数据</td></tr>';
        return;
    }
    let html = '';
    for (let r = 0; r < maxN; r++) {
        html += '<tr>';
        dates.forEach(function (d, i) {
            const sep = i > 0 ? ' sep' : '';
            const it = (lists[d] || [])[r];
            if (!it) {
                html += '<td class="num miss' + sep + '">—</td>' +
                        '<td class="miss"></td><td class="miss"></td><td class="num miss"></td>';
                return;
            }
            const rk = it.rank <= 10 ? 'up-strong' : '';
            let txt = '—', cls = 'miss';
            const chg = it.change;
            if (chg !== null && chg !== undefined && chg !== '') {
                const v = Number(chg);
                if (!isNaN(v)) { cls = v >= 0 ? 'up' : 'down'; txt = (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
            }
            html += '<td class="num ' + rk + sep + '">' + it.rank + '</td>' +
                    '<td class="mono">' + escHtml(it.ticker) + '</td>' +
                    '<td class="name-cell"><a class="stock-name-link" onclick="openStockChart(\'' +
                    it.ticker + '\',\'' + escHtml(it.name) + '\')">' + escHtml(it.name) + '</a></td>' +
                    '<td class="num ' + cls + '">' + txt + '</td>';
        });
        html += '</tr>';
    }
    tbody.innerHTML = html;
}

// ==================== 模块5：行情评分走势 ====================
let mhChart = null;
let mhLoaded = false;

let mhStart = '';      // 日期范围（留空 = 不限）
let mhEnd = '';
let mhMonth = null;    // 当前选中的月份（1~12；null = 未选）
let mhYearSel = '';    // 当前选中的年份（'' = 不限）
let mhInitDone = false; // 是否已应用「默认年份 = 当前年份」
let mhScoreOp = '';    // 评分筛选：比较符（'' / >= / > / <= / < / =）
let mhScoreVal = '';   // 评分筛选：阈值
let mhRawRows = [];    // 最近一次拉取的原始行（未过滤）
let mhLatest = '';     // 最新有数据的交易日（用于确定年份）
let mhHasMonths = {};   // 有数据的月份集合（默认全景视图下统计，兜底用）
let mhMonthsAvail = null;  // 服务端返回的「有数据的月份」（YYYY-MM）

function mhPad(v) { return (v < 10 ? '0' : '') + v; }

function mhYear() {
    // 月份按钮作用在哪个年份：优先用户选的年份，否则用最新有数据的年份
    if (mhYearSel) return Number(mhYearSel);
    return mhLatest ? Number(mhLatest.slice(0, 4)) : new Date().getFullYear();
}

function mhDefaultYear() {
    // 默认看「当前年份」；当前年份没有数据就退回到最近有数据的年份
    const nowY = String(new Date().getFullYear());
    const ys = mhYears();
    if (ys.indexOf(nowY) >= 0) return nowY;
    return ys.length ? ys[0] : '';
}

function mhYears() {
    // 本地有数据的年份（从接口返回的月份列表推导），倒序
    const ys = {};
    if (mhMonthsAvail) {
        Object.keys(mhMonthsAvail).forEach(function (m) { ys[String(m).slice(0, 4)] = true; });
    }
    if (mhLatest) ys[String(mhLatest).slice(0, 4)] = true;
    return Object.keys(ys).sort().reverse();
}

function mhBuildYears() {
    const sel = document.getElementById('mh-year');
    if (!sel) return;
    const years = mhYears();
    sel.innerHTML = '<option value="">不限</option>' +
        years.map(function (y) { return '<option value="' + escHtml(y) + '">' + escHtml(y) + '年</option>'; }).join('');
    sel.value = (mhYearSel && years.indexOf(mhYearSel) >= 0) ? mhYearSel : '';
}

function mhPickYear(y) {
    // 选年份 = 看那一整年；选「不限」= 回到默认（最近 45 天）
    mhYearSel = (y || '').trim();
    mhMonth = null;
    if (mhYearSel) {
        mhStart = mhYearSel + '-01-01';
        mhEnd = mhYearSel + '-12-31';
    } else {
        mhStart = ''; mhEnd = '';
    }
    mhBuildYears();
    mhSyncMonthUI();
    loadMarketHistory(true);
}

function mhLastDay(y, m) {
    // m: 1~12 -> 该月最后一天
    return new Date(y, m, 0).getDate();
}

function mhBuildMonths() {
    const box = document.getElementById('mh-months');
    if (!box || box.childElementCount) return;
    let html = '';
    for (let k = 1; k <= 12; k++) {
        html += '<button class="mini-btn mh-month-btn" id="mh-m' + k + '"' +
            ' onclick="mhPickMonth(' + k + ')">' + k + '月</button>';
    }
    box.innerHTML = html;
}

function mhSyncMonthUI() {
    const y = mhYear();
    for (let k = 1; k <= 12; k++) {
        const el = document.getElementById('mh-m' + k);
        if (!el) continue;
        const ym = y + '-' + mhPad(k);
        const has = mhMonthsAvail ? !!mhMonthsAvail[ym] : !!mhHasMonths[k];
        el.classList.toggle('active', mhMonth === k);
        el.disabled = !has;
        el.classList.toggle('mh-month-empty', !has);
        el.title = has ? (y + '年' + k + '月') : (y + '年' + k + '月（本地暂无数据，可跑历史补齐）');
    }
    const sel = document.getElementById('mh-year');
    if (sel && sel.value !== (mhYearSel || '')) sel.value = mhYearSel || '';
}

function mhPickMonth(k) {
    mhBuildMonths();
    if (mhMonth === k) {            // 再点一次 = 取消，回到该年份整年
        mhMonth = null;
        if (mhYearSel) {
            mhStart = mhYearSel + '-01-01';
            mhEnd = mhYearSel + '-12-31';
        } else {
            mhStart = ''; mhEnd = '';
        }
        mhSyncMonthUI();
        loadMarketHistory(true);
        return;
    }
    const y = mhYear();
    mhYearSel = String(y);          // 月份按钮隐含了年份 -> 同步下拉框
    mhMonth = k;
    mhStart = y + '-' + mhPad(k) + '-01';
    mhEnd = y + '-' + mhPad(k) + '-' + mhPad(mhLastDay(y, k));
    mhSyncMonthUI();
    loadMarketHistory(true);
}

function mhQuickRange(n) {
    // 以「最新有数据的交易日」为终点，往前推 n 个自然日
    fetch('/api/market-history?days=1').then(function (x) { return x.json(); }).then(function (r) {
        const last = (r && r.success && r.rows && r.rows.length) ? r.rows[r.rows.length - 1].date : null;
        if (!last) return;
        const d = new Date(last + 'T00:00:00');
        d.setDate(d.getDate() - n);
        mhStart = d.getFullYear() + '-' + mhPad(d.getMonth() + 1) + '-' + mhPad(d.getDate());
        mhEnd = last;
        mhMonth = null;
        mhYearSel = '';
        mhLatest = last;
        mhBuildYears();
        mhSyncMonthUI();
        loadMarketHistory(true);
    });
}

function mhResetRange() {
    mhStart = ''; mhEnd = ''; mhMonth = null; mhYearSel = '';
    mhBuildYears();
    mhSyncMonthUI();
    loadMarketHistory(true);
}

function mhScoreActive() {
    return mhScoreOp !== '' && mhScoreVal !== '' && mhScoreVal !== null;
}

function mhScoreOpText() {
    return ({ '>=': '≥', '>': '>', '<=': '≤', '<': '<', '=': '=' })[mhScoreOp] || mhScoreOp;
}

function mhApplyScoreFilter(rows) {
    if (!mhScoreActive()) return rows;
    const v = Number(mhScoreVal);
    if (!isFinite(v)) return rows;
    return rows.filter(function (r) {
        if (r.score == null) return false;
        switch (mhScoreOp) {
            case '>=': return r.score >= v;
            case '>': return r.score > v;
            case '<=': return r.score <= v;
            case '<': return r.score < v;
            case '=': return r.score === v;
            default: return true;
        }
    });
}

function mhApplyScore() {
    const op = document.getElementById('mh-score-op');
    const val = document.getElementById('mh-score-val');
    mhScoreOp = (op && op.value) || '';
    mhScoreVal = (val && val.value !== '' && val.value !== null) ? val.value : '';
    const btn = document.getElementById('mh-score-clear');
    if (btn) btn.style.display = mhScoreActive() ? '' : 'none';
    renderMarketHistory(mhApplyScoreFilter(mhRawRows));
}

function mhClearScore() {
    mhScoreOp = ''; mhScoreVal = '';
    const op = document.getElementById('mh-score-op'); if (op) op.value = '';
    const val = document.getElementById('mh-score-val'); if (val) val.value = '';
    const btn = document.getElementById('mh-score-clear'); if (btn) btn.style.display = 'none';
    renderMarketHistory(mhRawRows);
}

function mhDateFmt(dt) {
    return dt.getFullYear() + '-' + mhPad(dt.getMonth() + 1) + '-' + mhPad(dt.getDate());
}

function mhBuildDateDefaults() {
    // 日期范围默认值：开始 = 今天减 3 个月，结束 = 今天（只在未填写时设置，不覆盖用户输入）
    const s = document.getElementById('mh-date-start');
    const e = document.getElementById('mh-date-end');
    const now = new Date();
    if (s && !s.value) {
        const d = new Date(now);
        d.setMonth(d.getMonth() - 3);
        s.value = mhDateFmt(d);
    }
    if (e && !e.value) {
        e.value = mhDateFmt(now);
    }
}

function mhQueryDate() {
    // 按「开始 ~ 结束」查询（都空则忽略；只填一个就只按那一个端点查）
    const s = document.getElementById('mh-date-start');
    const e = document.getElementById('mh-date-end');
    const st = (s && s.value) || '';
    const en = (e && e.value) || '';
    if (!st && !en) return;
    mhStart = st; mhEnd = en;
    mhMonth = null; mhYearSel = '';
    mhBuildYears();
    mhSyncMonthUI();
    loadMarketHistory(true);
}

function fetchIntraday() {
    // 盘中实时：抓一次全市场快照（家数 + 成交额 + 盘中封板率）
    const sum = document.getElementById('mh-summary');
    if (sum) sum.innerHTML = '<span class="mh-item dim">正在抓取盘中实时数据…（约 3~5 秒）</span>';
    fetch('/api/market-intraday').then(function (r) { return r.json(); }).then(function (r) {
        if (!r || !r.success) {
            if (sum) sum.innerHTML = '<span class="mh-item dim">抓取失败：' + escHtml((r && r.error) || '未知错误') + '</span>';
            return;
        }
        if (r.stale) {
            if (sum) sum.innerHTML = '<span class="mh-item dim">' + escHtml(r.message || '非交易时段') +
                '（涨' + r.up + ' 跌' + r.down + '，来自 ' + escHtml(r.date || '') + '）</span>';
            return;
        }
        setTimeout(function () { loadMarketHistory(true); }, 600);
    }).catch(function () {
        if (sum) sum.innerHTML = '<span class="mh-item dim">抓取请求失败，请稍后再试</span>';
    });
}

async function loadMarketHistory(force) {
    if (mhLoaded && !force) return;
    mhBuildMonths();
    mhBuildYears();
    mhBuildDateDefaults();
    mhSyncMonthUI();
    const body = document.getElementById('mh-body');
    if (body) body.innerHTML = '<tr><td colspan="10" class="empty-cell">正在统计…</td></tr>';
    let r;
    try {
        let _u = '/api/market-history?days=45';
        if (mhStart) _u += '&start=' + encodeURIComponent(mhStart);
        if (mhEnd) _u += '&end=' + encodeURIComponent(mhEnd);
        r = await (await fetch(_u)).json();
    } catch (e) {
        if (body) body.innerHTML = '<tr><td colspan="10" class="empty-cell">加载失败：' + escHtml(e.message) + '</td></tr>';
        return;
    }
    if (!r || !r.success) {
        if (body) body.innerHTML = '<tr><td colspan="10" class="empty-cell">' + escHtml((r && r.error) || '暂无数据') + '</td></tr>';
        return;
    }
    mhLoaded = true;
    if (r.months && r.months.length) {
        mhMonthsAvail = {};
        for (let i = 0; i < r.months.length; i++) mhMonthsAvail[r.months[i]] = true;
        mhBuildYears();
    }
    if (!mhInitDone) {
        // 第一次加载：默认选中「当前年份」，并按该年份整年重新拉一次
        mhInitDone = true;
        const dy = mhDefaultYear();
        if (dy && String(dy) !== (mhYearSel || '')) {
            mhYearSel = String(dy);
            mhMonth = null;
            mhStart = mhYearSel + '-01-01';
            mhEnd = mhYearSel + '-12-31';
            mhBuildYears();
            mhSyncMonthUI();
            return loadMarketHistory(true);
        }
    }
    mhRawRows = r.rows || [];
    renderMarketHistory(mhApplyScoreFilter(mhRawRows));
}

function fmtMhAmount(v) {
    // 成交额（亿元）-> 1.68万亿 / 8966亿
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    if (!isFinite(n)) return '—';
    return Math.abs(n) >= 10000 ? (n / 10000).toFixed(2) + '万亿' : Math.round(n) + '亿';
}

function fmtMhDiff(v) {
    // 较上一日 -> 增量 +1382亿 / 缩量 -1382亿
    if (v === null || v === undefined || v === '') return '—';
    const n = Number(v);
    if (!isFinite(n)) return '—';
    const a = Math.abs(n);
    const txt = a >= 10000 ? (a / 10000).toFixed(2) + '万亿' : Math.round(a) + '亿';
    return (n >= 0 ? '增量 +' : '缩量 -') + txt;
}

function mhDiffCls(v) {
    if (v === null || v === undefined || v === '') return 'dim';
    const n = Number(v);
    if (!isFinite(n) || n === 0) return 'dim';
    return n > 0 ? 'up' : 'down';
}

function renderMarketHistory(rows) {
    const body = document.getElementById('mh-body');
    const sum = document.getElementById('mh-summary');
    if (!rows.length) {
        const emptyMsg = mhScoreActive() ? '没有符合评分筛选条件的交易日' : '该日期范围内暂无数据';
        if (body) body.innerHTML = '<tr><td colspan="10" class="empty-cell">' + emptyMsg + '</td></tr>';
        if (sum) sum.innerHTML = '<span class="mh-item dim">' + emptyMsg + '</span>';
        if (mhChart) mhChart.clear();
        return;
    }
    const last = rows[rows.length - 1];
    if (last && last.date) {
        mhLatest = last.date;
    }
    if (!mhStart && !mhEnd && !mhScoreActive()) {
        // 默认全景视图 -> 记下哪些月份有数据（没数据的月份按钮置灰）
        const has = {};
        for (let i = 0; i < rows.length; i++) {
            const m = Number(String(rows[i].date).slice(5, 7));
            if (m) has[m] = true;
        }
        mhHasMonths = has;
    }
    if (last && last.date) {
        mhBuildMonths();
        mhSyncMonthUI();
    }
    if (sum) {
        sum.innerHTML =
            '<span class="mh-item">最新交易日 <b>' + escHtml(last.date) + '</b></span>' +
            '<span class="mh-item">行情评分 <b class="' + (last.score == null ? '' : (last.score >= 70 ? 'up-strong' : (last.score >= 50 ? 'mid' : 'down'))) + '">' +
                (last.score == null ? '--' : last.score) + '</b></span>' +
            '<span class="mh-item">上涨 <b class="up">' + last.up + '</b></span>' +
            '<span class="mh-item">下跌 <b class="down">' + last.down + '</b></span>' +
            '<span class="mh-item">成交额 <b class="up-strong">' + fmtMhAmount(last.amount) + '</b></span>' +
            '<span class="mh-item">较上一日 <b class="' + mhDiffCls(last.amount_diff) + '">' +
                fmtMhDiff(last.amount_diff) + '</b></span>' +
            (last.src === 'intraday'
                ? '<span class="mh-item live-note">⏳ 盘中实时（未收盘）· 数值会随行情变动，收盘后自动替换为正式数据</span>'
                : '') +
            (mhScoreActive()
                ? '<span class="mh-item dim">评分 ' + mhScoreOpText() + ' ' + mhScoreVal +
                    ' · 筛选出 <b>' + rows.length + '</b> / 共 ' + mhRawRows.length + ' 个交易日</span>'
                : '<span class="mh-item dim">共 ' + rows.length + ' 个交易日' +
                    (mhMonth ? '（' + mhYear() + '年' + mhMonth + '月）'
                             : (mhYearSel ? '（' + mhYearSel + '年）'
                                          : ((mhStart || mhEnd)
                                              ? (mhStart === mhEnd ? '（' + mhStart + '）'
                                                                   : '（' + (mhStart || '最早') + ' ~ ' + (mhEnd || '最新') + '）')
                                              : ''))) + '</span>');
    }
    if (body) {
        body.innerHTML = rows.slice().reverse().map(function (x) {
            const cls = (x.score == null) ? 'dim' : (x.score >= 70 ? 'up-strong' : (x.score >= 50 ? 'mid' : 'down'));
            const ratio = x.down ? (x.up / x.down).toFixed(2) : '—';
            return '<tr>' +
                '<td>' + escHtml(x.date) +
                    (x.src === 'intraday' ? ' <span class="mh-live">盘中</span>' : '') + '</td>' +
                '<td class="num ' + cls + '">' + (x.score == null ? '—' : x.score) + '</td>' +
                '<td class="num up">' + x.up + '</td>' +
                '<td class="num down">' + x.down + '</td>' +
                '<td class="num dim">' + x.flat + '</td>' +
                '<td class="num dim">' + ratio + '</td>' +
                '<td class="num up-strong">' + fmtMhAmount(x.amount) + '</td>' +
                '<td class="num ' + mhDiffCls(x.amount_diff) + '">' + fmtMhDiff(x.amount_diff) + '</td>' +
                '<td class="num">' + fmtMhAmount(x.rz_ye) + '</td>' +
                '<td class="num">' + fmtMhAmount(x.rq_ye) + '</td>' +
                '</tr>';
        }).join('');
    }
    const box = document.getElementById('mh-chart');
    if (!box) return;
    if (!mhChart) mhChart = echarts.init(box);
    mhChart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(26,26,46,0.95)', borderColor: '#444',
            textStyle: { color: '#fff', fontSize: 13 },
            // 让提示框以「竖向虚线」为中心：水平居中于鼠标，并夹紧在图表内
            position: function (pt, params, dom, rect, size) {
                const w = (size && size.contentSize && size.contentSize[0]) || 0;
                const vw = (size && size.viewSize && size.viewSize[0]) || 0;
                let left = pt[0] - w / 2;
                const maxL = vw - w - 4;
                if (left < 4) left = 4;
                if (left > maxL) left = maxL;
                return [left, 8];
            },
            formatter: function (ps) {
                if (!ps || !ps.length) return '';
                const x = rows[ps[0].dataIndex] || {};
                return '<b>' + escHtml(x.date || '') + '</b>' +
                    '<br>行情评分：' + (x.score == null ? '—' : x.score) +
                    '<br>上涨家数：' + x.up +
                    '<br>下跌家数：' + x.down +
                    '<br>成交额总计：' + fmtMhAmount(x.amount) +
                    '<br>较上一日：' + fmtMhDiff(x.amount_diff);
            }
        },
        legend: { data: ['行情评分', '上涨家数', '下跌家数'], textStyle: { color: '#a0a0a0' }, top: 4 },
        grid: { left: 56, right: 64, top: 46, bottom: 58 },
        xAxis: {
            type: 'category', data: rows.map(function (x) { return x.date.slice(5); }),
            // z 调高：把竖向虚线画在柱子上层，否则会被柱子压住、看着像"没对准"
            axisPointer: {
                z: 120, snap: true,
                lineStyle: { color: 'rgba(255,255,255,0.8)', width: 1.2, type: 'dashed' }
            },
            axisLabel: { color: '#9aa0a6', fontSize: 11 }, axisLine: { lineStyle: { color: '#444' } }
        },
        yAxis: [
            { type: 'value', name: '评分', min: 0, max: 100, nameTextStyle: { color: '#9aa0a6' },
              axisLabel: { color: '#9aa0a6' }, splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } } },
            { type: 'value', name: '家数', nameTextStyle: { color: '#9aa0a6' },
              axisLabel: { color: '#9aa0a6' }, splitLine: { show: false } }
        ],
        series: [
            { name: '行情评分', type: 'line', yAxisIndex: 0, data: rows.map(function (x) { return x.score; }),
              smooth: true, symbolSize: 6, connectNulls: true,
              itemStyle: { color: '#f39c12' }, lineStyle: { width: 3 } },
            { name: '上涨家数', type: 'bar', yAxisIndex: 1, data: rows.map(function (x) { return x.up; }),
              itemStyle: { color: 'rgba(231,76,60,.62)' } },
            { name: '下跌家数', type: 'bar', yAxisIndex: 1, data: rows.map(function (x) { return x.down; }),
              itemStyle: { color: 'rgba(46,204,113,.62)' } }
        ]
    });
}
window.addEventListener('resize', function () { if (mhChart) mhChart.resize(); });


// ==================== 模块：条件概率（次日） ====================
let condRows = [];
let condLoaded = false;
let condChart = null;
let condScanRows = [];

// ① 当日条件：档位按钮（可多选 -> 合并成一个左闭右开区间）
const COND_SCORE_CHOICES = [30, 40, 50, 60, 70];
const COND_UP_CHOICES = [500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000];
let condScoreSel = [50];     // 评分：可多选档位（区间合并）
let condUpMax = 2000;        // 家数：单选「≤ 该值」；null = 不限
let condMonths = 12;         // 样本范围（月）：12/24/36/48/60

function condNum(id) {
    const el = document.getElementById(id);
    if (!el || el.value === '' || el.value === null) return null;
    const n = Number(el.value);
    return isFinite(n) ? n : null;
}

function condVal(id) {
    const el = document.getElementById(id);
    return el ? el.value : '';
}

function condPass(v, op, x) {
    if (v === null || v === undefined) return false;
    switch (op) {
        case '>=': return v >= x;
        case '>': return v > x;
        case '<=': return v <= x;
        case '<': return v < x;
        default: return true;
    }
}

/* 档位 -> 区间：选中一个档位，就是 [该档, 下一档)；多选则取最小档 ~ 最大档的下一档 */
function condNextOf(choices, v) {
    const i = choices.indexOf(Number(v));
    return (i >= 0 && i + 1 < choices.length) ? choices[i + 1] : null;
}

function condRangeOf(choices, sel) {
    if (!sel || !sel.length) return null;
    const sorted = sel.slice().sort(function (a, b) { return a - b; });
    return { lo: sorted[0], hi: condNextOf(choices, sorted[sorted.length - 1]) };
}

function condInRangeNum(v, r) {
    if (!r) return true;
    if (v === null || v === undefined) return false;
    if (v < r.lo) return false;
    if (r.hi !== null && v >= r.hi) return false;
    return true;
}

function condRangeTxt(r, unit) {
    if (!r) return '不限';
    if (r.hi === null) return '≥ ' + r.lo + unit;
    return r.lo + ' ~ ' + r.hi + unit;
}

function condYm(dt) {
    return dt.getFullYear() + '-' + mhPad(dt.getMonth() + 1);
}

function condRangeBounds() {
    const now = new Date();
    const st = new Date(now.getFullYear(), now.getMonth() - condMonths, 1);
    return { start: condYm(st), end: condYm(now) };
}

function condSyncRangeUI() {
    const b = condRangeBounds();
    const el = document.getElementById('cond-range-label');
    if (el) el.textContent = '当前样本：' + b.start + ' ~ ' + b.end;
    Array.prototype.forEach.call(document.querySelectorAll('.cond-yr'), function (btn) {
        btn.classList.toggle('active', Number(btn.getAttribute('data-m')) === Number(condMonths));
    });
}

function condRange(months) {
    condMonths = months || 12;
    condSyncRangeUI();
    runCond();
}

function condInRange(dateStr) {
    const b = condRangeBounds();
    const ym = String(dateStr || '').slice(0, 7);
    return ym >= b.start && ym <= b.end;
}

function condSyncAmt() {
    const op = document.getElementById('cond-amt-op');
    const val = document.getElementById('cond-amt-val');
    if (!op || !val) return;
    const off = !op.value;
    val.disabled = off;
    if (off) val.value = '';
    val.style.opacity = off ? '0.4' : '1';
}

function condBuildChips() {
    const sc = document.getElementById('cond-score-chips');
    if (sc && !sc.childElementCount) {
        sc.innerHTML = COND_SCORE_CHOICES.map(function (v) {
            return '<button class="chip-btn" data-v="' + v + '" onclick="condPickVal(\'score\',' + v + ')">' + v + '分</button>';
        }).join('');
    }
    const uc = document.getElementById('cond-up-chips');
    if (uc && !uc.childElementCount) {
        uc.innerHTML = COND_UP_CHOICES.map(function (v) {
            return '<button class="chip-btn" data-v="' + v + '" onclick="condPickVal(\'up\',' + v + ')">≤' + v + '</button>';
        }).join('');
    }
    condSyncChips();
}

function condSyncChips() {
    const sc = document.getElementById('cond-score-chips');
    if (sc) {
        Array.prototype.forEach.call(sc.children, function (b) {
            b.classList.toggle('active', condScoreSel.indexOf(Number(b.getAttribute('data-v'))) >= 0);
        });
    }
    const uc = document.getElementById('cond-up-chips');
    if (uc) {
        Array.prototype.forEach.call(uc.children, function (b) {
            b.classList.toggle('active', condUpMax !== null && Number(b.getAttribute('data-v')) === Number(condUpMax));
        });
    }
}

function condPickVal(kind, v) {
    if (kind === 'score') {
        const i = condScoreSel.indexOf(v);
        if (i >= 0) condScoreSel.splice(i, 1); else condScoreSel.push(v);
    } else {
        condUpMax = (condUpMax !== null && Number(condUpMax) === Number(v)) ? null : v;
    }
    condSyncChips();
    runCond();
}

/* Wilson 95% 置信区间 */
function condWilson(k, n) {
    if (!n) return null;
    const z = 1.96, p = k / n;
    const d = 1 + z * z / n;
    const c = (p + z * z / (2 * n)) / d;
    const h = z * Math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d;
    return [Math.max(0, (c - h) * 100), Math.min(100, (c + h) * 100)];
}

/* 两比例 z 检验 */
function condZ(k1, n1, k2, n2) {
    if (!n1 || !n2) return null;
    const p = (k1 + k2) / (n1 + n2);
    const se = Math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2));
    if (!se) return null;
    return (k1 / n1 - k2 / n2) / se;
}

function condSig(z) {
    if (z === null || z === undefined) return { txt: '—', cls: 'dim' };
    if (Math.abs(z) >= 2.58) return { txt: (z > 0 ? '显著↑' : '显著↓') + ' p<1%', cls: z > 0 ? 'up' : 'down' };
    if (Math.abs(z) >= 1.96) return { txt: (z > 0 ? '显著↑' : '显著↓') + ' p<5%', cls: z > 0 ? 'up' : 'down' };
    return { txt: '无显著差异', cls: 'dim' };
}

function condMetrics(pairs, nScoreOp, nScoreVal, nUpOp, nUpVal) {
    const n = pairs.length;
    const out = { n: n, hitsS: 0, hitsU: 0, hitsUD: 0,
                  pScore: null, pUp: null, pUpDown: null,
                  meanScore: null, medianScore: null, buckets: [0, 0, 0, 0, 0] };
    if (!n) return out;
    const scores = [];
    for (let i = 0; i < pairs.length; i++) {
        const nx = pairs[i].next;
        const s = nx.score;
        if (s !== null && s !== undefined) {
            scores.push(s);
            if (nScoreVal !== null && condPass(s, nScoreOp, nScoreVal)) out.hitsS++;
            if (s < 40) out.buckets[0]++;
            else if (s < 50) out.buckets[1]++;
            else if (s < 60) out.buckets[2]++;
            else if (s < 70) out.buckets[3]++;
            else out.buckets[4]++;
        }
        if (nUpVal !== null && condPass(nx.up, nUpOp, nUpVal)) out.hitsU++;
        if ((nx.up || 0) > (nx.down || 0)) out.hitsUD++;
    }
    out.pScore = nScoreVal !== null ? out.hitsS / n * 100 : null;
    out.pUp = nUpVal !== null ? out.hitsU / n * 100 : null;
    out.pUpDown = out.hitsUD / n * 100;
    if (scores.length) {
        out.meanScore = scores.reduce(function (a, b) { return a + b; }, 0) / scores.length;
        const sorted = scores.slice().sort(function (a, b) { return a - b; });
        out.medianScore = sorted[Math.floor(sorted.length / 2)];
    }
    return out;
}

function condPct(v) { return v === null || v === undefined ? '—' : v.toFixed(0) + '%'; }

function condCiTxt(k, n) {
    const ci = condWilson(k, n);
    return ci ? '95%CI ' + ci[0].toFixed(0) + '~' + ci[1].toFixed(0) + '%' : '';
}

function condDiffTxt(cur, base) {
    if (cur === null || base === null || cur === undefined || base === undefined) return '—';
    const d = cur - base;
    return (d >= 0 ? '+' : '') + d.toFixed(0) + 'pp';
}

function renderLadderChart(elId, rows, title) {
    const el = document.getElementById(elId);
    if (!el || !rows || !rows.length) return;
    let ch = echarts.getInstanceByDom(el);
    if (!ch) ch = echarts.init(el);
    ch.setOption({
        backgroundColor: 'transparent',
        title: { text: title, left: 0, top: 0, textStyle: { color: '#d8dde3', fontSize: 12, fontWeight: 600 } },
        tooltip: { trigger: 'axis', valueFormatter: function (v) { return v + '%'; } },
        legend: { data: ['条件组', '基准'], right: 0, top: 0, textStyle: { color: '#a0a0a0', fontSize: 11 } },
        grid: { left: 44, right: 14, top: 40, bottom: 26 },
        xAxis: { type: 'category', data: rows.map(function (r) { return '≥' + r.t; }),
                 axisLabel: { color: '#9aa0a6', fontSize: 10 }, axisLine: { lineStyle: { color: '#444' } } },
        yAxis: { type: 'value', min: 0, max: 100,
                 axisLabel: { color: '#9aa0a6', fontSize: 10, formatter: '{value}%' },
                 splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } } },
        series: [
            { name: '条件组', type: 'line', smooth: true, symbolSize: 5,
              data: rows.map(function (r) { return +(r.p || 0).toFixed(1); }),
              itemStyle: { color: '#f39c12' }, lineStyle: { width: 2.5 },
              label: { show: true, position: 'top', fontSize: 9, color: '#f5b041',
                       formatter: function (pp) { return Math.round(pp.value) + '%'; } } },
            { name: '基准', type: 'line', smooth: true, symbolSize: 4,
              data: rows.map(function (r) { return +(r.pb || 0).toFixed(1); }),
              itemStyle: { color: '#5dade2' }, lineStyle: { width: 1.5, type: 'dashed' } }
        ]
    }, true);
    ch.resize();
}

function runCond() {
    const note = document.getElementById('cond-note');
    const verdict = document.getElementById('cond-verdict');
    const label = document.getElementById('cond-count-label');
    if (!condRows.length) { if (note) note.textContent = '暂无历史数据'; return; }

    const cScoreR = condRangeOf(COND_SCORE_CHOICES, condScoreSel);

    const ok = function (r) {
        if (!condInRangeNum(r.score, cScoreR)) return false;
        if (condUpMax !== null && (r.up || 0) > condUpMax) return false;
        return true;
    };

    const allPairs = [];
    for (let i = 0; i < condRows.length - 1; i++) {
        allPairs.push({ cur: condRows[i], next: condRows[i + 1] });
    }
    const ranged = allPairs.filter(function (p) { return condInRange(p.cur.date); });
    const pairs = ranged.filter(function (p) { return ok(p.cur); });
    const base = condMetrics(ranged, '>=', null, '>=', null);
    const cur = condMetrics(pairs, '>=', null, '>=', null);
    const n = cur.n;

    const parts = [];
    if (cScoreR) parts.push('评分 ' + condRangeTxt(cScoreR, '分'));
    if (condUpMax !== null) parts.push('上涨家数 ≤ ' + condUpMax + '只');
    const condTxt = parts.length ? parts.join(' 且 ') : '不限条件（全样本）';

    const _b = condRangeBounds();
    const _rangeTxt = _b.start + ' ~ ' + _b.end;
    const _rl = document.getElementById('cond-range-label');
    if (_rl) _rl.textContent = '当前样本：' + _rangeTxt;

    if (note) {
        note.innerHTML = '条件：<b>' + escHtml(condTxt) + '</b> ｜ 样本范围 <b>' + escHtml(_rangeTxt) + '</b> ｜ 匹配 <b>' + n + '</b> 天 / 区间内 ' + base.n +
            ' 天（占 ' + (base.n ? (n / base.n * 100).toFixed(0) : 0) + '%）' +
            (n < 30 ? ' <span class="warn-text">⚠ 样本偏少（' + n + ' 天），置信区间较宽</span>' : '');
    }
    if (label) label.textContent = '共 ' + n + ' 条';

    // ③④ 阶梯：把每个档位的概率都算出来
    const ladder = function (thrs, get) {
        return thrs.map(function (t) {
            const k = pairs.reduce(function (a, p) { return a + (get(p) >= t ? 1 : 0); }, 0);
            const kb = ranged.reduce(function (a, p) { return a + (get(p) >= t ? 1 : 0); }, 0);
            const pv = n ? k / n * 100 : 0;
            const pbv = base.n ? kb / base.n * 100 : 0;
            const z = condZ(k, n, kb, base.n);
            return { t: t, k: k, p: pv, pb: pbv, z: z, sig: condSig(z), ci: condWilson(k, n) };
        });
    };
    const upRows = ladder([500, 1000, 1500, 2000, 2500, 3000, 3500, 4000, 4500, 5000],
        function (p) { return p.next.up || 0; });
    const scRows = ladder([30, 40, 50, 60, 70],
        function (p) {
            const v = p.next.score;
            return (v === null || v === undefined) ? -1 : v;
        });

    const fillLadder = function (tbodyId, rows, unit) {
        const tb = document.getElementById(tbodyId);
        if (!tb) return;
        tb.innerHTML = rows.map(function (r) {
            const d = r.p - r.pb;
            const dcls = (d > 0.5) ? 'up' : ((d < -0.5) ? 'down' : 'dim');
            return '<tr>' +
                '<td>≥ ' + r.t + ' ' + unit + '</td>' +
                '<td class="num up-strong">' + (n ? r.p.toFixed(0) + '%' : '—') + '</td>' +
                '<td class="num dim">' + (r.ci ? r.ci[0].toFixed(0) + '~' + r.ci[1].toFixed(0) + '%' : '—') + '</td>' +
                '<td class="num dim">' + r.pb.toFixed(0) + '%</td>' +
                '<td class="num ' + dcls + '">' + (d >= 0 ? '+' : '') + d.toFixed(0) + 'pp</td>' +
                '<td class="' + r.sig.cls + '">' + r.sig.txt + '</td></tr>';
        }).join('');
    };
    fillLadder('cond-ladder-up', upRows, '只');
    fillLadder('cond-ladder-score', scRows, '分');

    const sigUD = condSig(condZ(cur.hitsUD, n, base.hitsUD, base.n));
    const sn = document.getElementById('cond-stat-n');
    if (sn) sn.textContent = n + ' 天' + (base.n ? '（占 ' + (n / base.n * 100).toFixed(0) + '%）' : '');
    const su = document.getElementById('cond-stat-ud');
    if (su) {
        su.textContent = condPct(cur.pUpDown);
        su.className = (sigUD.cls === 'dim') ? '' : sigUD.cls;
        su.title = '基准 ' + condPct(base.pUpDown) + ' · ' + condDiffTxt(cur.pUpDown, base.pUpDown) + ' ' + sigUD.txt;
    }
    const sm = document.getElementById('cond-stat-mean');
    if (sm) sm.textContent = (cur.meanScore === null ? '—' : cur.meanScore.toFixed(1)) +
        '（基准 ' + (base.meanScore === null ? '—' : base.meanScore.toFixed(1)) + '）';

    renderLadderChart('cond-ladder-chart-up', upRows, '次日上涨家数 ≥ 阈值');
    renderLadderChart('cond-ladder-chart-score', scRows, '次日行情评分 ≥ 阈值');

    if (verdict) {
        const all = upRows.map(function (r) { return { kind: 'up', r: r }; })
            .concat(scRows.map(function (r) { return { kind: 'sc', r: r }; }));
        const sigs = all.filter(function (x) { return x.r.sig.cls !== 'dim'; });
        let txt;
        if (!n) {
            txt = '没有符合条件的交易日，换个条件试试。';
        } else if (sigs.length) {
            const names = sigs.map(function (x) {
                const name = (x.kind === 'up') ? ('次日上涨≥' + x.r.t + '只') : ('次日评分≥' + x.r.t + '分');
                return name + ' ' + x.r.p.toFixed(0) + '%（' + x.r.sig.txt + '）';
            });
            txt = '⚠ 有 ' + sigs.length + ' 个档位与基准存在显著差异（p<5%）：' + names.join('；') +
                '。' + (n < 30 ? '样本仅 ' + n + ' 天，仍需谨慎。' : '');
        } else {
            txt = '所有档位与区间内基准均无显著差异 —— 说明该条件<b>对次日没有预测力</b>' +
                (n < 30 ? '；且样本仅 ' + n + ' 天。' : '。');
        }
        verdict.innerHTML = txt;
    }

    const box = document.getElementById('cond-chart');
    if (!box) return;
    if (!condChart) condChart = echarts.init(box);
    const dd = document.getElementById('cond-dist-details');
    if (dd && !dd.getAttribute('data-bound')) {
        dd.setAttribute('data-bound', '1');
        dd.addEventListener('toggle', function () {
            if (dd.open && condChart) setTimeout(function () { condChart.resize(); }, 60);
        });
    }
    const labels = ['<40', '40~50', '50~60', '60~70', '≥70'];
    const pc = cur.buckets.map(function (v) { return n ? +(v / n * 100).toFixed(1) : 0; });
    const pb = base.buckets.map(function (v) { return base.n ? +(v / base.n * 100).toFixed(1) : 0; });
    condChart.setOption({
        backgroundColor: 'transparent',
        tooltip: { trigger: 'axis', valueFormatter: function (v) { return v + '%'; } },
        legend: { data: ['条件组', '全样本'], textStyle: { color: '#a0a0a0' }, top: 4 },
        grid: { left: 48, right: 24, top: 44, bottom: 40 },
        xAxis: { type: 'category', data: labels, axisLabel: { color: '#9aa0a6' },
                 axisLine: { lineStyle: { color: '#444' } } },
        yAxis: { type: 'value', name: '占比 %', nameTextStyle: { color: '#9aa0a6' },
                 axisLabel: { color: '#9aa0a6', formatter: '{value}%' },
                 splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } } },
        series: [
            { name: '条件组', type: 'bar', data: pc, itemStyle: { color: '#f39c12' },
              label: { show: true, position: 'top', color: '#f5b041', fontSize: 11, formatter: '{c}%' } },
            { name: '全样本', type: 'bar', data: pb, itemStyle: { color: 'rgba(52,152,219,.55)' },
              label: { show: true, position: 'top', color: '#5dade2', fontSize: 11, formatter: '{c}%' } }
        ]
    }, true);
}

/* ---------------- 自动扫描：按档位区间试条件，找显著提升次日上涨概率的 ---------------- */
function condAutoScan() {
    const box = document.getElementById('cond-scan');
    if (!box) return;
    if (!condRows.length) { box.innerHTML = '<div class="cond-scan-hint">暂无数据</div>'; return; }

    const allPairs = [];
    for (let i = 0; i < condRows.length - 1; i++) allPairs.push({ cur: condRows[i], next: condRows[i + 1] });
    const ranged = allPairs.filter(function (p) { return condInRange(p.cur.date); });
    const TARGET_UP = 2000;
    const base = condMetrics(ranged, '>=', TARGET_UP, '>=', TARGET_UP);

    const cands = [];
    const add = function (label, selS, upMax) {
        cands.push({ label: label, selScore: selS || [], upMax: (upMax === undefined ? null : upMax) });
    };
    const SN = COND_SCORE_CHOICES, UN = COND_UP_CHOICES;
    SN.forEach(function (v, i) {
        add('评分 ' + v + '~' + ((SN[i + 1] !== undefined) ? SN[i + 1] : '以上') + '分', [v], null);
        if (i > 0) add('评分 ≤ ' + v + '分', SN.slice(0, i), null);
        if (i < SN.length - 1) add('评分 ≥ ' + v + '分', SN.slice(i), null);
    });
    UN.forEach(function (v) {
        add('上涨 ≤ ' + v + '只', [], v);
    });
    add('评分 ≥ 60 且 上涨 ≤ 1500', [60, 70], 1500);
    add('评分 ≤ 40 且 上涨 ≤ 1500', [30, 40], 1500);
    add('评分 40~60 且 上涨 ≤ 2000', [40, 50], 2000);

    const out = [];
    cands.forEach(function (c) {
        const rs = condRangeOf(SN, c.selScore);
        const ps = ranged.filter(function (p) {
            if (!condInRangeNum(p.cur.score, rs)) return false;
            if (c.upMax !== null && (p.cur.up || 0) > c.upMax) return false;
            return true;
        });
        if (ps.length < 25) return;
        const m = condMetrics(ps, '>=', TARGET_UP, '>=', TARGET_UP);
        const z = condZ(m.hitsU, m.n, base.hitsU, base.n);
        if (z === null || Math.abs(z) < 1.96) return;
        out.push({ label: c.label, n: m.n, p: m.pUp, lift: m.pUp - base.pUp, z: z,
                   selScore: c.selScore, upMax: c.upMax });
    });
    out.sort(function (a, b) { return Math.abs(b.lift) - Math.abs(a.lift); });
    condScanRows = out.slice(0, 8);

    if (!out.length) {
        box.innerHTML = '<div class="cond-scan-hint">扫描了 ' + cands.length + ' 个档位条件，' +
            '没有发现「与基准有显著差异（p<5%）且样本≥25天」的条件。</div>';
        return;
    }
    let html = '<div class="cond-scan-title">🔍 扫描 ' + cands.length + ' 个档位条件，以下 ' + condScanRows.length +
        ' 个对「次日上涨家数 ≥ ' + TARGET_UP + '」有显著提升 / 降低（基准 ' + condPct(base.pUp) + '，样本≥25天）：</div>' +
        '<div class="table-container"><table class="stock-table cond-table"><thead><tr>' +
        '<th>条件</th><th class="num">样本</th><th class="num">次日上涨≥' + TARGET_UP + '</th>' +
        '<th class="num">较基准</th><th class="num">显著性</th><th></th></tr></thead><tbody>';
    condScanRows.forEach(function (r, i) {
        const sig = condSig(r.z);
        html += '<tr><td>' + escHtml(r.label) + '</td>' +
            '<td class="num">' + r.n + '</td>' +
            '<td class="num ' + (r.p >= base.pUp ? 'up' : 'down') + '">' + condPct(r.p) + '</td>' +
            '<td class="num ' + (r.lift >= 0 ? 'up' : 'down') + '">' + (r.lift >= 0 ? '+' : '') + r.lift.toFixed(0) + 'pp</td>' +
            '<td class="dim">' + sig.txt + '</td>' +
            '<td><button class="mini-btn" onclick="condApplyScan(' + i + ')">套用</button></td></tr>';
    });
    html += '</tbody></table></div>';
    box.innerHTML = html;
}

function condApplyScan(i) {
    const r = condScanRows[i];
    if (!r) return;
    condScoreSel = (r.selScore || []).slice();
    condUpMax = (r.upMax === undefined ? null : r.upMax);
    const set = function (id, v) { const el = document.getElementById(id); if (el) el.value = v; };
    set('cond-amt-op', ''); set('cond-amt-val', '');
    condSyncAmt();
    condSyncChips();
    runCond();
    const el = document.getElementById('cond-note');
    if (el && el.scrollIntoView) el.scrollIntoView({ block: 'center' });
}

function condReset() {
    const set = function (id, v) { const el = document.getElementById(id); if (el) el.value = v; };
    condScoreSel = [50];
    condUpMax = 2000;
    condMonths = 12;
    condSyncRangeUI();
    condSyncChips();
    set('cond-amt-op', ''); set('cond-amt-val', '');
    condSyncRangeUI();
    const scan = document.getElementById('cond-scan');
    if (scan) scan.innerHTML = '';
    runCond();
}

async function loadCond(force) {
    if (condLoaded && !force) return;
    try {
        const r = await (await fetch('/api/market-history?start=2000-01-01&end=2099-12-31')).json();
        if (!r || !r.success) throw new Error((r && r.error) || '暂无数据');
        condRows = r.rows || [];
        condLoaded = true;
        condBuildChips();
        condSyncRangeUI();
        runCond();
    } catch (e) {
        const note = document.getElementById('cond-note');
        if (note) note.textContent = '加载失败：' + e.message;
    }
}
window.addEventListener('resize', function () {
    if (condChart) condChart.resize();
    ['cond-ladder-chart-up', 'cond-ladder-chart-score'].forEach(function (id) {
        const el = document.getElementById(id);
        const ch = el ? echarts.getInstanceByDom(el) : null;
        if (ch) ch.resize();
    });
});
