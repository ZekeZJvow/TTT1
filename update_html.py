import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('index.html', 'r', encoding='utf-8') as f:
    html = f.read()

old = '<div id="chart-container" style="width: 100%; height: 400px;"></div>'
new = '''<div id="chart-container" style="width: 100%; height: 400px;"></div>
                <div class="news-section">
                    <h3 class="news-header">近期资讯</h3>
                    <div id="news-list" class="news-list"></div>
                </div>'''

html = html.replace(old, new)

with open('index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print('Done!')
