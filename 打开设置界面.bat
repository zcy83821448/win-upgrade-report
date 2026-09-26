@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "应用程序\win升级报告.exe" (
  start "" "应用程序\win升级报告.exe"
) else (
  rem 还没打包时，直接用源码跑
  start "" "D:\python\pythonw.exe" "gui.py"
)
exit
