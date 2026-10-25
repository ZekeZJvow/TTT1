// 情绪评分模块（主站与独立页共用）
// ================= 第7模块：情绪评分 · 历史回测 =================
const SC_FACTORS = [
    { k: 'breadth', name: '市场广度', w: 30, color: '#5dade2', cls: 'w30' },
    { k: 'limit',   name: '涨停跌停情绪', w: 25, color: '#e74c3c', cls: 'w25' },
    { k: 'broken',  name: '炸板质量', w: 15, color: '#af7ac5', cls: 'w15' },
    { k: 'hot',     name: '人气股表现', w: 15, color: '#2ecc71', cls: 'w15' },
    { k: 'index',   name: '指数与成交确认', w: 15, color: '#1abc9c', cls: 'w15' }
];
const SC_HORIZONS = ['1', '3', '5'];

let scState = {
    loaded: false, today: null, rows: [], range: '1m',
    vis: { total: true, breadth: false, limit: false, broken: false, hot: false, index: false },
    chart: null, backtest: null, btKey: ''
};

function scColor(t) {
    if (t === null || t === undefined) return '#666';
    if (t >= 80) return '#ff5252';
    if (t >= 65) return '#f39c12';
    if (t >= 45) return '#f5d76e';
    if (t >= 30) return '#5dade2';
    return '#2ecc71';
}
function scLabelCls(t) {
    if (t === null || t === undefined) return '';
    if (t >= 80) return 'lv-strong';
    if (t >= 65) return 'lv-good';
    if (t >= 45) return 'lv-mid';
    if (t >= 30) return 'lv-weak';
    return 'lv-bad';
}
function scFmt(v, digits, suffix) {
    if (v === null || v === undefined || v === '' || isNaN(Number(v))) return '—';
    return Number(v).toFixed(digits === undefined ? 2 : digits) + (suffix || '');
}

async function loadScoreModule(force) {
    if (scState.loaded && !force) return;
    if (force || !scState.today) await loadScoreToday();
    await loadScoreHistory(true);
    await loadScoreBacktest(true);
    await loadScoreQuality();
    scState.loaded = true;
}

async function loadScoreToday() {
    const box = document.getElementById('sc-factors');
    try {
        const r = await (await fetch('/api/score/today')).json();
        if (!r || !r.success || !r.data) {
            if (box) box.innerHTML = '<div class="sc-empty">暂无评分数据。请先补齐日K，再点右上角「重算评分」。</div>';
            const al = document.getElementById('sc-alerts');
            if (al) { al.className = 'sc-alerts warn'; al.textContent = '暂无评分数据（score_daily 为空）'; }
            return;
        }
        scState.today = r.data;
        renderScoreToday(r.data);
    } catch (e) {
        if (box) box.innerHTML = '<div class="sc-empty">加载失败：' + escHtml(e.message) + '</div>';
    }
}

function renderScoreToday(d) {
    const total = d.total;
    const prov = !!d.provisional;
    const qt = d.quote_time ? String(d.quote_time).slice(0, 5) : '';

    // 页头右上角：今日情绪评分
    const hLive = document.getElementById('hs-live');
    if (hLive) hLive.classList.toggle('hidden', !prov);
    const hScore = document.getElementById('hs-score');
    if (hScore) {
        hScore.textContent = total == null ? '--' : Number(total).toFixed(1);
        hScore.style.color = total == null ? '#fff' : scColor(total);
    }
    const hLabel = document.getElementById('hs-label');
    if (hLabel) {
        hLabel.textContent = d.label || '—';
        hLabel.className = 'ms-tag ' + scLabelCls(total);
    }
    const hDate = document.getElementById('hs-date');
    if (hDate) hDate.textContent = (d.date || '—') + (prov && qt ? ' ' + qt : '');
    const hBox = document.getElementById('market-score-box');
    if (hBox) hBox.title = '情绪评分 ' + (total == null ? '--' : total) + ' 分（' + (d.label || '—') + '）· ' + (d.date || '') +
        (prov ? ' ' + qt + '（盘中估算，未收盘）' : '') +
        ' · 五因子加权，只反映当日市场情绪，不构成买卖建议';

    const dEl = document.getElementById('sc-date');
    if (dEl) dEl.textContent = (d.date || '—') + (prov && qt ? ' ' + qt + ' 盘中' : '');
    const cEl = document.getElementById('sc-comp');
    if (cEl) {
        const comp = d.completeness == null ? null : Number(d.completeness);
        cEl.className = 'sc-comp' + (comp != null && comp < 0.9 ? ' warn' : '');
        const ts = d.computed_at ? String(d.computed_at) : '';
        cEl.textContent = (prov ? '盘中估算 · ' : '') +
            '完整度 ' + (comp == null ? '—' : Math.round(comp * 100) + '%') +
            ' · ' + (d.model_version || '—') +
            (ts ? ' · ' + ts.slice(5, 16) + ' 计算' : '') +
            (comp != null && comp < 0.9 ? '（降级评分）' : '');
        cEl.title = '模型 ' + (d.model_version || '—') + (ts ? '，计算时间 ' + ts : '');
    }

    const box = document.getElementById('sc-factors');
    if (box) {
        box.innerHTML = SC_FACTORS.map(function (f) {
            const v = d[f.k];
            const has = (v !== null && v !== undefined && !isNaN(Number(v)));
            const pct = has ? Math.max(0, Math.min(100, Number(v))) : 0;
            return '<div class="sc-factor">' +
                '<span class="sc-f-name">' + f.name + '<em>权重 ' + f.w + '</em></span>' +
                '<span class="sc-f-bar"><i class="' + f.cls + '" style="width:' + pct.toFixed(1) + '%"></i></span>' +
                '<b class="sc-f-val' + (has ? '' : ' na') + '">' + (has ? pct.toFixed(1) : '缺失') + '</b>' +
                '</div>';
        }).join('');
    }

    const al = document.getElementById('sc-alerts');
    if (al) {
        const items = String(d.alerts || '').split('；').filter(function (x) { return x.trim(); });
        const parts = [];
        if (prov) parts.push('⏳ 盘中估算（未收盘）：' + (qt ? '行情时间 ' + qt + '，' : '') +
            '收盘后会以正式评分覆盖，仅供参考');
        if (items.length) parts.push('<b>⚠ 风险提示：</b>' + items.map(escHtml).join(' ｜ '));
        if (parts.length) {
            al.className = 'sc-alerts';
            al.innerHTML = parts.join('<br>');
        } else {
            al.className = 'sc-alerts none';
            al.innerHTML = '✓ 暂无触发风险警报' +
                (d.missing ? '（注意：缺失因子 ' + escHtml(d.missing) + '）' : '');
        }
    }
}

async function loadScoreHistory(force) {
    if (scState.rows.length && !force) { renderScoreHistory(); return; }
    try {
        const r = await (await fetch('/api/score/history')).json();
        if (!r || !r.success) throw new Error((r && r.error) || '暂无数据');
        scState.rows = r.rows || [];
        renderScoreHistory();
    } catch (e) {
        const el = document.getElementById('sc-chart-hint');
        if (el) el.textContent = '历史评分加载失败：' + e.message;
    }
}

function scSliceRows() {
    const rows = scState.rows || [];
    const n = { '1m': 22, '3m': 66, '1y': 250, '3y': 750, 'all': rows.length }[scState.range] || 250;
    return rows.slice(Math.max(0, rows.length - n));
}

function scoreRange(r) {
    scState.range = r;
    document.querySelectorAll('#sc-range-chips .mini-btn').forEach(function (b) {
        b.classList.toggle('active', b.getAttribute('data-r') === r);
    });
    renderScoreHistory();
}

function scBuildLegend() {
    const el = document.getElementById('sc-legend');
    if (!el || el.getAttribute('data-built') === '1') return;
    const items = [{ k: 'total', name: '总分', color: '#f39c12' }].concat(
        SC_FACTORS.map(function (f) { return { k: f.k, name: f.name, color: f.color }; }));
    el.innerHTML = items.map(function (it) {
        const on = scState.vis[it.k] ? ' on' : '';
        return '<span class="sc-leg' + on + '" data-k="' + it.k + '" onclick="scToggleSeries(\'' + it.k + '\')">' +
            '<i style="background:' + it.color + '"></i>' + it.name + '</span>';
    }).join('');
    el.setAttribute('data-built', '1');
}

function scToggleSeries(k) {
    scState.vis[k] = !scState.vis[k];
    document.querySelectorAll('#sc-legend .sc-leg').forEach(function (b) {
        b.classList.toggle('on', !!scState.vis[b.getAttribute('data-k')]);
    });
    renderScoreHistory();
}

function renderScoreHistory() {
    scBuildLegend();
    const rows = scSliceRows();
    const box = document.getElementById('sc-chart');
    const hint = document.getElementById('sc-chart-hint');
    if (!box) return;
    if (!rows.length) {
        if (hint) hint.textContent = '该范围内暂无评分数据。';
        return;
    }
    if (!scState.chart) scState.chart = echarts.init(box);
    const dates = rows.map(function (r) { return r.date; });
    const series = [];
    if (scState.vis.total) series.push({
        name: '总分', type: 'line', data: rows.map(function (r) { return r.total; }),
        showSymbol: false, connectNulls: false, smooth: false,
        lineStyle: { width: 2.4, color: '#f39c12' },
        itemStyle: { color: '#f39c12' },
        areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: 'rgba(243,156,18,0.28)' }, { offset: 1, color: 'rgba(243,156,18,0.02)' }]) },
        markLine: {
            silent: true, symbol: 'none',
            label: { show: false },
            data: [
                { yAxis: 80, name: '强势80', lineStyle: { color: 'rgba(255,82,82,.5)', type: 'dashed' } },
                { yAxis: 65, name: '偏强65', lineStyle: { color: 'rgba(243,156,18,.45)', type: 'dashed' } },
                { yAxis: 45, name: '震荡45', lineStyle: { color: 'rgba(255,255,255,.22)', type: 'dashed' } },
                { yAxis: 30, name: '偏弱30', lineStyle: { color: 'rgba(93,173,226,.45)', type: 'dashed' } }
            ]
        }
    });
    SC_FACTORS.forEach(function (f) {
        if (!scState.vis[f.k]) return;
        series.push({
            name: f.name, type: 'line', data: rows.map(function (r) { return r[f.k]; }),
            showSymbol: false, connectNulls: false, smooth: false,
            lineStyle: { width: 1.3, color: f.color, opacity: .9 },
            itemStyle: { color: f.color }
        });
    });
    scState.chart.setOption({
        backgroundColor: 'transparent',
        animation: false,
        grid: { left: 46, right: 18, top: 18, bottom: 42 },
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(26,26,46,0.96)', borderColor: '#444',
            textStyle: { color: '#fff', fontSize: 12 },
            formatter: function (ps) {
                if (!ps || !ps.length) return '';
                const i = ps[0].dataIndex;
                const r = rows[i] || {};
                let s = '<b>' + dates[i] + '</b>' + (r.label ? '（' + r.label + '）' : '') + '<br/>';
                s += '总分：<b>' + (r.total == null ? '—' : Number(r.total).toFixed(1)) + '</b><br/>';
                SC_FACTORS.forEach(function (f) {
                    const v = r[f.k];
                    if (v !== null && v !== undefined) s += f.name + '：' + Number(v).toFixed(1) + '<br/>';
                });
                if (r.completeness != null && Number(r.completeness) < 0.9) {
                    s += '<span style="color:#f5b041">降级评分：缺 ' + (r.missing || '—') + '</span>';
                }
                return s;
            }
        },
        xAxis: {
            type: 'category', data: dates, boundaryGap: false,
            axisLine: { lineStyle: { color: '#444' } },
            axisLabel: { color: '#8a8a8a', fontSize: 10, formatter: function (v) { return String(v).slice(5); } }
        },
        yAxis: {
            type: 'value', min: 0, max: 100,
            axisLine: { show: false }, axisTick: { show: false },
            splitLine: { lineStyle: { color: 'rgba(255,255,255,.06)' } },
            axisLabel: { color: '#8a8a8a', fontSize: 10 }
        },
        series: series
    }, true);
    if (hint) {
        hint.textContent = '共 ' + rows.length + ' 个交易日（' + dates[0] + ' ~ ' + dates[dates.length - 1] +
            '）。点上方图例可叠加五个因子分；虚线为 30 / 45 / 65 / 80 分档。';
    }
}

function scBtRangeStart() {
    const sel = document.getElementById('sc-bt-range');
    const v = sel ? sel.value : 'all';
    if (v === 'all') return null;
    const base = scState.today && scState.today.date ? new Date(scState.today.date + 'T00:00:00') : new Date();
    const years = v === '1y' ? 1 : 3;
    base.setFullYear(base.getFullYear() - years);
    return ymdLocal(base);
}

async function loadScoreBacktest(force) {
    const idxEl = document.getElementById('sc-index');
    const key = (idxEl ? idxEl.value : '000300') + '|' + scBtRangeStart();
    if (scState.backtest && !force && scState.btKey === key) return;
    const body = document.getElementById('sc-bt-body');
    if (body) body.innerHTML = '<div class="sc-empty">正在回测（本地统计，约 1~3 秒）…</div>';
    let url = '/api/score/backtest?index=' + encodeURIComponent(idxEl ? idxEl.value : '000300');
    const st = scBtRangeStart();
    if (st) url += '&start=' + encodeURIComponent(st);
    try {
        const r = await (await fetch(url)).json();
        if (!r || !r.ok) throw new Error((r && r.error) || '回测失败');
        scState.backtest = r;
        scState.btKey = key;
        renderScoreBacktest(r);
    } catch (e) {
        if (body) body.innerHTML = '<div class="sc-empty">回测失败：' + escHtml(e.message) + '</div>';
    }
}

function scHorizonCard(h, st) {
    if (!st || !st.n) {
        return '<div class="sc-kpi"><div class="k">未来 ' + h + ' 日</div><div class="v">—</div><div class="s">样本不足</div></div>';
    }
    const mean = st.mean;
    const cls = mean > 0 ? 'up' : (mean < 0 ? 'down' : '');
    return '<div class="sc-kpi">' +
        '<div class="k">未来 ' + h + ' 个交易日</div>' +
        '<div class="v ' + cls + '">' + scFmt(st.mean, 2, '%') + '</div>' +
        '<div class="s">平均收益 · 上涨概率 <b style="color:#fff">' + scFmt(st.up_prob, 1, '%') + '</b></div>' +
        '<div class="s">中位 ' + scFmt(st.median, 2, '%') + ' · 极端亏损 ' + scFmt(st.extreme_prob, 1, '%') +
            ' · 最大不利 ' + scFmt(st.mean_adverse, 2, '%') + '</div>' +
        '<div class="s">样本 ' + st.n + ' 天 · 95%CI [' + scFmt(st.ci_low, 2) + ', ' + scFmt(st.ci_high, 2) + ']</div>' +
        '</div>';
}

function renderScoreBacktest(r) {
    const body = document.getElementById('sc-bt-body');
    if (!body) return;
    const o = r.overall || {};
    let html = '<div class="sc-kpi-row">' + SC_HORIZONS.map(function (h) { return scHorizonCard(h, o[h]); }).join('') + '</div>';

    // 结论（如实：相关系数、单调性）
    let maxAbs = 0;
    SC_HORIZONS.forEach(function (h) {
        const c = (r.corr || {})[h] || {};
        if (c.spearman != null) maxAbs = Math.max(maxAbs, Math.abs(c.spearman));
    });
    let verdict, cls = 'warn';
    if (maxAbs < 0.05) {
        verdict = '评分与未来收益<b>几乎不相关</b>（|Spearman ρ| &lt; 0.05）。这说明当前 v1.0 评分<b>没有可用的预测力</b>，只能当作「当日情绪温度计」，不能据此判断次日涨跌。';
    } else if (maxAbs < 0.15) {
        verdict = '评分与未来收益<b>仅弱相关</b>（|ρ| 0.05~0.15），方向性参考价值有限，需结合其他信号。';
    } else {
        verdict = '评分与未来收益存在<b>一定相关性</b>（|ρ| ≥ 0.15），但仍需样本外稳定、并扣除成本后再评估。';
    }
    const mono = r.monotonic || {};
    const monoAll = SC_HORIZONS.every(function (h) { return mono[h]; });
    if (!monoAll) verdict += ' 分组收益<b>不单调</b>（分数越高收益未必越高），进一步说明不能线性解读分数。';
    html += '<div class="sc-verdict ' + cls + '">' + verdict + '</div>';

    // 分组表
    html += '<div class="sc-sect-title">评分分组统计</div><div class="table-container"><table class="stock-table sc-table"><thead><tr>' +
        '<th>评分区间</th><th class="num">样本</th>' +
        '<th class="num">1日均值</th><th class="num">1日胜率</th>' +
        '<th class="num">3日均值</th><th class="num">3日胜率</th>' +
        '<th class="num">5日均值</th><th class="num">5日胜率</th></tr></thead><tbody>';
    (r.buckets || []).forEach(function (b) {
        html += '<tr><td class="bucket-name">' + escHtml(b.bucket) + ' 分</td><td class="num">' + b.n + '</td>';
        SC_HORIZONS.forEach(function (h) {
            const st = (b.horizons || {})[h] || {};
            const cls2 = st.mean == null ? 'dim' : (st.mean > 0 ? 'up' : (st.mean < 0 ? 'down' : 'dim'));
            html += '<td class="num ' + cls2 + '">' + scFmt(st.mean, 2, '%') + '</td>' +
                '<td class="num dim">' + scFmt(st.up_prob, 1, '%') + '</td>';
        });
        html += '</tr>';
    });
    html += '</tbody></table></div>';
    const small = (r.buckets || []).filter(function (b) { return b.n < 20; }).map(function (b) { return b.bucket; });
    if (small.length) {
        html += '<div class="sc-note">⚠ ' + small.join('、') + ' 分组的样本少于 20 天，该组概率/收益的参考性弱，不要单独下结论。</div>';
    }

    // 样本外
    const sp = r.split || {};
    html += '<div class="sc-sect-title">样本外验证（前 ' + Math.round((sp.ratio || .7) * 100) + '% 开发 / 后 ' +
        Math.round(100 - (sp.ratio || .7) * 100) + '% 样本外，按日期切分，未打乱）</div>' +
        '<div class="table-container"><table class="stock-table sc-table"><thead><tr>' +
        '<th>数据集</th><th>日期范围</th><th class="num">样本</th>' +
        '<th class="num">1日均值</th><th class="num">1日胜率</th>' +
        '<th class="num">3日均值</th><th class="num">3日胜率</th>' +
        '<th class="num">5日均值</th><th class="num">5日胜率</th></tr></thead><tbody>';
    const dev = sp.dev || {}, oos = sp.oos || {};
    const rangeTxt = function (obj) {
        const rg = obj && obj.range;
        return (rg && rg.length === 2) ? (rg[0] + ' ~ ' + rg[1]) : '—';
    };
    const mk = function (name, obj) {
        let tr = '<tr><td class="bucket-name">' + name + '</td><td class="dim">' + escHtml(rangeTxt(obj)) + '</td><td class="num">' + (obj.n || 0) + '</td>';
        SC_HORIZONS.forEach(function (h) {
            const st = (obj.horizons || {})[h] || {};
            const cls2 = st.mean == null ? 'dim' : (st.mean > 0 ? 'up' : (st.mean < 0 ? 'down' : 'dim'));
            tr += '<td class="num ' + cls2 + '">' + scFmt(st.mean, 2, '%') + '</td><td class="num dim">' + scFmt(st.up_prob, 1, '%') + '</td>';
        });
        return tr + '</tr>';
    };
    html += mk('开发集', dev) + mk('样本外', oos) + '</tbody></table></div>';

    // 相关性 + 口径
    html += '<details class="cond-details" style="margin-top:14px"><summary>🔬 相关性与回测口径（研究细节）</summary>';
    html += '<div class="table-container" style="margin-top:10px"><table class="stock-table sc-table"><thead><tr>' +
        '<th>未来窗口</th><th class="num">样本</th><th class="num">Pearson</th><th class="num">Spearman ρ</th><th class="num">分组单调</th></tr></thead><tbody>';
    SC_HORIZONS.forEach(function (h) {
        const c = (r.corr || {})[h] || {};
        html += '<tr><td>' + h + ' 个交易日</td><td class="num">' + (c.n || 0) + '</td>' +
            '<td class="num">' + (c.pearson == null ? '—' : c.pearson) + '</td>' +
            '<td class="num">' + (c.spearman == null ? '—' : c.spearman) + '</td>' +
            '<td class="num">' + (mono[h] ? '<span class="sc-deg ok">单调</span>' : '<span class="sc-deg bad">不单调</span>') + '</td></tr>';
    });
    html += '</tbody></table></div>';
    html += '<div class="sc-note">' +
        '回测区间：<b>' + escHtml((r.range || []).join(' ~ ')) + '</b>，有效评分 ' + (r.n_days || 0) + ' 天，可计算收益 ' + (r.n_scored || 0) + ' 天；' +
        '样本外切分点 ' + escHtml(sp.split_date || '—') + '。<br/>' +
        (r.notes || []).map(escHtml).join('<br/>') +
        '<br/>以上均为历史统计结果，<b>不构成投资建议，不承诺收益</b>。</div>';
    html += '</details>';

    body.innerHTML = html;
}

async function loadScoreQuality() {
    const box = document.getElementById('sc-quality');
    if (!box) return;
    try {
        const r = await (await fetch('/api/score/quality?days=30')).json();
        if (!r || !r.success) throw new Error((r && r.error) || '暂无数据');
        const rows = r.rows || [];
        if (!rows.length) { box.innerHTML = '<div class="sc-empty">暂无数据</div>'; return; }
        const full = rows.filter(function (x) { return (x.completeness || 0) >= 0.9; }).length;
        const avg = rows.reduce(function (a, x) { return a + (x.completeness || 0); }, 0) / rows.length;
        let html = '<div class="sc-quality-sum">' +
            '<span>最近 <b>' + rows.length + '</b> 天</span>' +
            '<span>平均完整度 <b class="' + (avg < 0.9 ? 'warn' : '') + '">' + Math.round(avg * 100) + '%</b></span>' +
            '<span>完整度 ≥90%：<b>' + full + '</b> / ' + rows.length + '</span>' +
            '<span>降级评分：<b class="' + (rows.length - full ? 'warn' : '') + '">' + (rows.length - full) + '</b> 天</span>' +
            '</div>';
        html += '<div class="sc-q-wrap"><table class="stock-table sc-table"><thead><tr>' +
            '<th>交易日</th><th class="num">完整度</th><th>缺失因子</th><th>警报</th></tr></thead><tbody>';
        rows.forEach(function (x) {
            const c = x.completeness == null ? null : Number(x.completeness);
            const cls = c == null ? 'dim' : (c >= 0.9 ? 'up' : 'down');
            html += '<tr><td>' + escHtml(x.date) + '</td>' +
                '<td class="num ' + cls + '">' + (c == null ? '—' : Math.round(c * 100) + '%') + '</td>' +
                '<td class="dim">' + escHtml(x.missing || '—') + '</td>' +
                '<td class="dim">' + escHtml(x.alerts || '—') + '</td></tr>';
        });
        html += '</tbody></table></div>';
        html += '<div class="sc-note">完整度 = 当日可用因子权重 / 总权重。人气股因子需要当日人气榜快照，历史早期没有快照，因此完整度会低于 100% —— 这类日期按可用因子归一，属于「降级评分」，不会伪造数据。</div>';
        box.innerHTML = html;
    } catch (e) {
        box.innerHTML = '<div class="sc-empty">加载失败：' + escHtml(e.message) + '</div>';
    }
}

function scIsTradingWindow() {
    const now = new Date();
    const wd = now.getDay();
    if (wd === 0 || wd === 6) return false;
    const mins = now.getHours() * 60 + now.getMinutes();
    return mins >= 9 * 60 + 30 && mins <= 15 * 60 + 5;
}

async function maybeLoadIntradayScore() {
    // 交易时段打开页面：自动抓一次盘中估算（约 5~12 秒），失败就保持正式评分
    if (!scIsTradingWindow()) return;
    const today = ymdLocal(new Date());
    if (scState.today && scState.today.date === today && !scState.today.provisional) return;
    try {
        const r = await (await fetch('/api/score/intraday', { cache: 'no-store' })).json();
        if (r && r.ok) {
            scState.today = r;
            renderScoreToday(r);
        }
    } catch (e) { /* 静默：保留本地正式评分 */ }
}

async function scoreIntraday() {
    const btn = document.getElementById('sc-intraday-btn');
    if (btn) { btn.disabled = true; btn.textContent = '抓取中…'; }
    try {
        const r = await (await fetch('/api/score/intraday', { cache: 'no-store' })).json();
        if (!r || !r.ok) {
            if (r && r.stale) {
                alert(r.message || '当前非交易时段，无法计算盘中评分');
            } else {
                alert('盘中估算失败：' + ((r && r.error) || '未知错误'));
            }
            return;
        }
        scState.today = r;
        renderScoreToday(r);
    } catch (e) {
        alert('盘中估算失败：' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '⚡ 盘中估算'; }
    }
}

async function scoreRebuild() {
    const btn = document.getElementById('sc-rebuild-btn');
    if (btn) { btn.disabled = true; btn.textContent = '重算中…'; }
    try {
        const r = await (await fetch('/api/score/rebuild', { method: 'POST' })).json();
        if (!r || !r.success) throw new Error((r && r.error) || '重算失败');
        scState.loaded = false;
        await loadScoreModule(true);
    } catch (e) {
        alert('重算失败：' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '↻ 重算评分'; }
    }
}

function scoreExportCsv() {
    const rows = scState.rows || [];
    if (!rows.length) { alert('暂无评分数据可导出'); return; }
    const lines = [];
    lines.push('情绪评分历史（模型 v1.0，导出于 ' + ymdLocal(new Date()) + '）');
    lines.push('交易日,总分,标签,市场广度30,涨停跌停25,炸板质量15,人气股表现15,指数确认15,完整度,缺失因子,警报');
    rows.forEach(function (r) {
        const cell = function (v) { return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"'; };
        lines.push([r.date, r.total, r.label, r.breadth, r.limit, r.broken, r.hot, r.index,
            r.completeness, r.missing, r.alerts].map(cell).join(','));
    });
    const bt = scState.backtest;
    if (bt && bt.ok) {
        lines.push('');
        lines.push('回测汇总（' + (bt.index_code || '') + '，' + (bt.range || []).join(' ~ ') + '）');
        lines.push('窗口,样本,平均收益%,中位数%,上涨概率%,极端亏损概率%,平均最大不利%');
        SC_HORIZONS.forEach(function (h) {
            const st = (bt.overall || {})[h] || {};
            lines.push([h + '日', st.n, st.mean, st.median, st.up_prob, st.extreme_prob, st.mean_adverse].join(','));
        });
        lines.push('');
        lines.push('评分区间,样本,1日均值%,1日胜率%,3日均值%,3日胜率%,5日均值%,5日胜率%');
        (bt.buckets || []).forEach(function (b) {
            const row = [b.bucket, b.n];
            SC_HORIZONS.forEach(function (h) {
                const st = (b.horizons || {})[h] || {};
                row.push(st.mean == null ? '' : st.mean, st.up_prob == null ? '' : st.up_prob);
            });
            lines.push(row.join(','));
        });
        lines.push('');
        lines.push('说明：最大不利波动为窗口内最低收盘价近似；相邻交易日窗口重叠；历史统计不构成投资建议。');
    }
    const blob = new Blob(['\ufeff' + lines.join('\r\n')], { type: 'text/csv;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = '情绪评分_' + ymdLocal(new Date()) + '.csv';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

window.addEventListener('resize', function () {
    if (scState.chart) scState.chart.resize();
});
