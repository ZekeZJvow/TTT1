import re

with open("app.js", "r", encoding="utf-8") as f:
    content = f.read()

# 日K图 - 在grid后面添加axisPointer配置
old_daily = """        grid: [
            { left: '10%', right: '10%', top: '15%', height: '55%' },
            { left: '10%', right: '10%', top: '75%', height: '20%' }
        ],
        xAxis: [
            {
                type: 'category',
                data: dates,"""

new_daily = """        grid: [
            { left: '10%', right: '10%', top: '15%', height: '55%' },
            { left: '10%', right: '10%', top: '75%', height: '20%' }
        ],
        axisPointer: {
            link: [{ xAxisIndex: [0, 1] }]
        },
        xAxis: [
            {
                type: 'category',
                data: dates,"""

content = content.replace(old_daily, new_daily)

# 分时图 - 同样添加axisPointer配置
old_minute = """        grid: [
            { left: '10%', right: '10%', top: '15%', height: '55%' },
            { left: '10%', right: '10%', top: '75%', height: '20%' }
        ],
        xAxis: [
            {
                type: 'category',
                data: times,"""

new_minute = """        grid: [
            { left: '10%', right: '10%', top: '15%', height: '55%' },
            { left: '10%', right: '10%', top: '75%', height: '20%' }
        ],
        axisPointer: {
            link: [{ xAxisIndex: [0, 1] }]
        },
        xAxis: [
            {
                type: 'category',
                data: times,"""

content = content.replace(old_minute, new_minute)

with open("app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Done!")
