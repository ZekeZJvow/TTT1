import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('app.js', 'r', encoding='utf-8') as f:
    content = f.read()

old = """setTimeout(async () => {
        await loadChart('minute');
    }, 100);"""

new = """setTimeout(async () => {
        await loadChart('minute');
        loadNews(code);
    }, 100);"""

content = content.replace(old, new)

with open('app.js', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done!')
