@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo    A股人气雷达 - 一键上传到 GitHub
echo    仓库： https://github.com/ZekeZJvow/TTT1
echo ============================================================
echo.

where git >nul 2>nul
if errorlevel 1 (
    echo [错误] 没有检测到 Git，请先安装 Git for Windows。
    echo.
    pause
    exit /b 1
)

set "PROXY=http://127.0.0.1:7897"

echo [1/4] 检查与 GitHub 的连接 ...
rem 先试直连（Clash 关闭 / TUN 模式时可用），失败再试代理
git -c http.proxy= -c https.proxy= ls-remote origin >nul 2>nul
if not errorlevel 1 goto ok_direct
git -c http.proxy=%PROXY% -c https.proxy=%PROXY% ls-remote origin >nul 2>nul
if not errorlevel 1 goto ok_proxy

echo.
echo [提示] 现在连不上 GitHub。请任选其一：
echo        1) 启动 Clash 后重新双击本文件；或
echo        2) 确认网络能直接访问 github.com。
echo.
pause
exit /b 1

:ok_direct
set "GITP=-c http.proxy= -c https.proxy="
echo       连接正常（直连）。
goto conn_ok

:ok_proxy
set "GITP=-c http.proxy=%PROXY% -c https.proxy=%PROXY%"
echo       连接正常（已自动走 Clash 代理 %PROXY%）。
goto conn_ok

:conn_ok

echo [2/4] 收集本次改动 ...
git add -A
git diff --cached --quiet
if not errorlevel 1 (
    echo.
    echo [完成] 没有需要上传的改动，已经在最新状态。
    echo.
    pause
    exit /b 0
)

echo [3/4] 提交 ...
set "MSG=%~1"
if "%MSG%"=="" set "MSG=更新 %date% %time%"
git commit -q -m "%MSG%"
if errorlevel 1 (
    echo.
    echo [错误] 提交失败，请把上面的提示发给开发者。
    echo.
    pause
    exit /b 1
)
echo       本次说明：%MSG%

echo [4/4] 上传中 ...
git %GITP% push
if errorlevel 1 (
    echo.
    echo [错误] 上传失败。请检查网络后重试。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo    [完成] 已成功上传到 GitHub
echo    打开看看： https://github.com/ZekeZJvow/TTT1
echo ============================================================
echo.
pause
