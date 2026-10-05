@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/2] 启动 Streamlit ...
start "Streamlit" cmd /k "venv\Scripts\streamlit run app.py --server.headless true --server.port 8501"

timeout /t 5 /nobreak >nul

echo [2/2] 创建公网链接（发给老师用）...
if not exist "tools\cloudflared.exe" (
    echo 正在下载 cloudflared ...
    mkdir tools 2>nul
    powershell -Command "Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/download/2026.5.0/cloudflared-windows-amd64.exe' -OutFile 'tools\cloudflared.exe'"
)

echo.
echo ========================================
echo  下面会出现 https://xxx.trycloudflare.com
echo  复制那个链接发给老师即可
echo  关闭此窗口后链接会失效
echo ========================================
echo.

tools\cloudflared.exe tunnel --url http://localhost:8501
