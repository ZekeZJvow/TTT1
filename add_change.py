import re

# 1. 修改 server.py - 添加涨跌幅字段
with open("server.py", "r", encoding="utf-8") as f:
    server = f.read()

# 修改 process_ths_data 函数，添加 rise_and_fall 字段
old_ths = """        result.append({
            'rank': order,
            'name': name or clean_code,
            'code': code,
            'consecutive_boards': process_consecutive_boards(popularity_tag),
            'tier': get_tier(order),
            'concept_tag': concept_str,
            'anomaly_analysis': get_anomaly_analysis(item),
            'is_hot': bool(popularity_tag)
        })"""

new_ths = """        # 获取涨跌幅
        rise_and_fall = item.get('rise_and_fall', 0)
        
        result.append({
            'rank': order,
            'name': name or clean_code,
            'code': code,
            'rise_and_fall': rise_and_fall,
            'consecutive_boards': process_consecutive_boards(popularity_tag),
            'tier': get_tier(order),
            'concept_tag': concept_str,
            'anomaly_analysis': get_anomaly_analysis(item),
            'is_hot': bool(popularity_tag)
        })"""

server = server.replace(old_ths, new_ths)

# 修改 process_eastmoney_data 函数
old_em = """        result.append({
            'rank': i,
            'name': name,
            'code': code,
            'consecutive_boards': "无",
            'tier': get_tier(i),
            'concept_tag': "降级模式，无数据",
            'anomaly_analysis': "无",
            'is_hot': False
        })"""

new_em = """        result.append({
            'rank': i,
            'name': name,
            'code': code,
            'rise_and_fall': 0,
            'consecutive_boards': "无",
            'tier': get_tier(i),
            'concept_tag': "降级模式，无数据",
            'anomaly_analysis': "无",
            'is_hot': False
        })"""

server = server.replace(old_em, new_em)

with open("server.py", "w", encoding="utf-8") as f:
    f.write(server)

print("server.py updated")

# 2. 修改 index.html - 添加表头
with open("index.html", "r", encoding="utf-8") as f:
    html = f.read()

old_header = """<th class="col-code">代码</th>
                    <th class="col-boards">连板数</th>"""

new_header = """<th class="col-code">代码</th>
                    <th class="col-change">涨跌幅</th>
                    <th class="col-boards">连板数</th>"""

html = html.replace(old_header, new_header)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("index.html updated")

# 3. 修改 app.js - 渲染涨跌幅列
with open("app.js", "r", encoding="utf-8") as f:
    js = f.read()

old_code_td = """        // 代码
        const codeTd = document.createElement('td');
        codeTd.className = 'col-code';
        codeTd.textContent = item.code;
        codeTd.style.color = '#a0a0a0';
        tr.appendChild(codeTd);
        
        // 连板数"""

new_code_td = """        // 代码
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
        
        // 连板数"""

js = js.replace(old_code_td, new_code_td)

with open("app.js", "w", encoding="utf-8") as f:
    f.write(js)

print("app.js updated")

# 4. 修改 styles.css - 添加涨跌幅样式
with open("styles.css", "r", encoding="utf-8") as f:
    css = f.read()

old_col_code = ".col-code { width: 80px; }"
new_col_code = ".col-code { width: 80px; }\n.col-change { width: 80px; text-align: right; }"

css = css.replace(old_col_code, new_col_code)

with open("styles.css", "w", encoding="utf-8") as f:
    f.write(css)

print("styles.css updated")
print("All done!")
