@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "应用程序\win升级报告\WinUpdReport.UI.exe" (
  start "" "应用程序\win升级报告\WinUpdReport.UI.exe"
) else if exist "ui\WinUpdReport.UI\bin\Release\net48\WinUpdReport.UI.exe" (
  start "" "ui\WinUpdReport.UI\bin\Release\net48\WinUpdReport.UI.exe" --data-dir "%~dp0."
) else if exist "应用程序\win升级报告\win升级报告.exe" (
  start "" "应用程序\win升级报告\win升级报告.exe"
) else (
  rem 还没打包时，直接用源码跑：优先用 PATH 里的 pythonw / python，别再写死某台机器的路径
  where pythonw >nul 2>nul
  if not errorlevel 1 (
    start "" pythonw "gui.py"
  ) else (
    where python >nul 2>nul
    if not errorlevel 1 (
      start "" python "gui.py"
    ) else (
      echo 没有找到 Python，也没有找到打包好的程序。
      echo 请先解压完整的绿色版，或安装 Python 后重试。
      pause
    )
  )
)
exit

