import sys
sys.stdout.reconfigure(encoding='utf-8')
with open('server.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_code = "articles = data.get('result', {}).get('cmsArticleWebOld', {}).get('list', [])"
new_code = "articles = data.get('result', {}).get('cmsArticleWebOld', [])"

content = content.replace(old_code, new_code)

with open('server.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Done!')
