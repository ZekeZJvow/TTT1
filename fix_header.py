with open("index.html", "r", encoding="utf-8") as f:
    html = f.read()

old = '<th class="col-code">代码</th>'
new = '<th class="col-code">代码</th>\n                        <th class="col-change">涨跌幅</th>'

html = html.replace(old, new)

with open("index.html", "w", encoding="utf-8") as f:
    f.write(html)

print("Done!")
