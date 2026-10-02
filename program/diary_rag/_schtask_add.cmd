@echo off
cd /d C:\Users\su35\Documents\assistant-agent\program\diary_rag
.venv\Scripts\python.exe index_add_retry.py > index_schtask.log 2>&1
