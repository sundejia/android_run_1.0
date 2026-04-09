@echo off
chcp 65001 > nul
echo ========================================
echo AI 服务器连通性测试
echo ========================================
echo.

REM 检查 Python 是否安装
python --version > nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.7+
    pause
    exit /b 1
)

REM 检查 requests 库是否安装
python -c "import requests" 2> nul
if errorlevel 1 (
    echo [提示] 正在安装 requests 库...
    pip install requests
    if errorlevel 1 (
        echo [错误] 安装 requests 失败
        pause
        exit /b 1
    )
)

REM 运行测试脚本
echo.
echo 开始测试...
echo.
python test_ai_server.py %*

pause
