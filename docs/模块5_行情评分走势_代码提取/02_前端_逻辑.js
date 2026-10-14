// ==================== 模块5：行情评分走势 ====================
let mhChart = null;
let mhLoaded = false;

let mhStart = '';      // 日期范围（留空 = 不限）
let mhEnd = '';
let mhMonth = null;    // 当前选中的月份（1~12；null = 未选）
let mhLatest = '';     // 最新有数据的交易日（用于确定年份）
let mhHasMonths = {};   // 有数据的月份集合（默认全景视图下统计，兜底用）
let mhMonthsAvail = null;  // 服务端返回的「有数据的月份」（YYYY-MM）

function mhPad(v) { return (v < 10 ? '0' : '') + v; }

function mhYear() {
    // 用「最新有数据的交易日」所在年份
    return mhLatest ? Number(mhLatest.slice(0, 4)) : new Date().getFullYear();
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
}

function mhPickMonth(k) {
    mhBuildMonths();
    if (mhMonth === k) {            // 再点一次 = 取消，回到默认（近 45 天）
        mhMonth = null; mhStart = ''; mhEnd = '';
        mhSyncMonthUI();
        loadMarketHistory(true);
        return;
    }
    const y = mhYear();
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
        mhLatest = last;
        mhSyncMonthUI();
        loadMarketHistory(true);
    });
}

function mhResetRange() {
    mhStart = ''; mhEnd = ''; mhMonth = null;
    mhSyncMonthUI();
    loadMarketHistory(true);
}

async function loadMarketHistory(force) {
    if (mhLoaded && !force) return;
    mhBuildMonths();
    mhSyncMonthUI();
    const body = document.getElementById('mh-body');
    if (body) body.innerHTML = '<tr><td colspan="8" class="empty-cell">正在统计…</td></tr>';
    let r;
    try {
        let _u = '/api/market-history?days=45';
        if (mhStart) _u += '&start=' + encodeURIComponent(mhStart);
        if (mhEnd) _u += '&end=' + encodeURIComponent(mhEnd);
        r = await (await fetch(_u)).json();
    } catch (e) {
        if (body) body.innerHTML = '<tr><td colspan="8" class="empty-cell">加载失败：' + escHtml(e.message) + '</td></tr>';
        return;
    }
    if (!r || !r.success) {
        if (body) body.innerHTML = '<tr><td colspan="8" class="empty-cell">' + escHtml((r && r.error) || '暂无数据') + '</td></tr>';
        return;
    }
    mhLoaded = true;
    if (r.months && r.months.length) {
        mhMonthsAvail = {};
        for (let i = 0; i < r.months.length; i++) mhMonthsAvail[r.months[i]] = true;
    }
    renderMarketHistory(r.rows || []);
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
        if (body) body.innerHTML = '<tr><td colspan="8" class="empty-cell">该日期范围内暂无数据</td></tr>';
        if (sum) sum.innerHTML = '<span class="mh-item dim">该日期范围内暂无数据</span>';
        if (mhChart) mhChart.clear();
        return;
    }
    const last = rows[rows.length - 1];
    if (last && last.date) {
        mhLatest = last.date;
    }
    if (!mhStart && !mhEnd) {
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
            '<span class="mh-item dim">共 ' + rows.length + ' 个交易日' +
                (mhMonth ? '（' + mhYear() + '年' + mhMonth + '月）'
                         : (mhStart || mhEnd ? '（' + (mhStart || '最早') + ' ~ ' + (mhEnd || '最新') + '）' : '')) +
                '</span>';
    }
    if (body) {
        body.innerHTML = rows.slice().reverse().map(function (x) {
            const cls = (x.score == null) ? 'dim' : (x.score >= 70 ? 'up-strong' : (x.score >= 50 ? 'mid' : 'down'));
            const ratio = x.down ? (x.up / x.down).toFixed(2) : '—';
            return '<tr>' +
                '<td>' + escHtml(x.date) + '</td>' +
                '<td class="num ' + cls + '">' + (x.score == null ? '—' : x.score) + '</td>' +
                '<td class="num up">' + x.up + '</td>' +
                '<td class="num down">' + x.down + '</td>' +
                '<td class="num dim">' + x.flat + '</td>' +
                '<td class="num dim">' + ratio + '</td>' +
                '<td class="num up-strong">' + fmtMhAmount(x.amount) + '</td>' +
                '<td class="num ' + mhDiffCls(x.amount_diff) + '">' + fmtMhDiff(x.amount_diff) + '</td>' +
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

