@echo off
rem 重建 diary-rag 向量索引（在普通 cmd 窗口双击或手动运行；不要在 ZCode 里跑）
rem chroma 1.5.9 的 rust 绑定在本机「新建数据库」会报 code 14；
rem 已验证的闭环：先让它建出基础库 -> 手动补迁移 -> 再跑一次即可正常灌库。
chcp 65001 >nul
cd /d C:\Users\su35\Documents\assistant-agent\program\diary_rag

echo [1/5] 清空旧 chroma 目录...
if exist data\chroma rmdir /s /q data\chroma
mkdir data\chroma

echo [2/5] 第一次运行 index.py（预期失败：创建基础库）...
.venv\Scripts\python.exe index.py > index_try1.log 2>&1
if exist data\chroma\chroma.sqlite3 (
    echo       基础库已创建。
) else (
    echo       !! index.py 连基础库都没建出来，检查 data\diary 目录。退出。
    exit /b 1
)

echo [3/5] 手动补迁移...
.venv\Scripts\python.exe apply_migrations.py

echo [4/6] 灌库（带重试的分批脚本，32781 块需要十几分钟）...
.venv\Scripts\python.exe index_add_retry.py > index_retry.log 2>&1
findstr /C:"Done." index_retry.log

echo [5/6] 补洞（失败批次的 id 差集补齐）...
.venv\Scripts\python.exe index_two_phase.py holes

echo [6/6] 校验...
.venv\Scripts\python.exe verify.py
echo.
echo 完成。之后运行 run_mcp.cmd 即可恢复 diary-rag MCP 服务。
pause
