@echo off
REM 闪亮大世界 ShiningWorld 一键启动（Windows）
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] 创建虚拟环境...
    python -m venv .venv || goto :err
    ".venv\Scripts\python.exe" -m pip install -q --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -q -e ".[dev]" || goto :err
)

echo [2/3] 初始化工作区（幂等）...
".venv\Scripts\python.exe" scripts\init_world.py --config config.yaml || goto :err

echo [3/3] 启动 SSE 服务 http://127.0.0.1:8791/sse
".venv\Scripts\python.exe" -m shining_world sse --config config.yaml
goto :eof

:err
echo 启动失败，请查看上方错误信息。
exit /b 1
