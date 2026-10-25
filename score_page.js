// 独立页启动：只加载情绪评分模块
function escHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
}
function ymdLocal(d) {
    const p = n => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
}
document.addEventListener('DOMContentLoaded', function () {
    loadScoreModule(true).then(maybeLoadIntradayScore);
});
