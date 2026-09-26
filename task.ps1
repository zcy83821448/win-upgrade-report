# 安装 / 删除计划任务：以当前用户身份、隐藏窗口、每天（或每 N 天）定时静默运行检测
#
# 打包版：-Exe "D:\...\应用程序\win升级报告.exe" -Arguments "--check"
# 源码版：-Exe "D:\python\pythonw.exe" -Arguments '"D:\...\checker.py"'
# 注意：参数不能叫 $Args —— 那是 PowerShell 的自动变量，会被静默吃掉。
param(
    [string]$Action = "install",       # install | remove | query
    [string]$TaskName = "WinUpdReport_Daily",
    [string]$Time = "12:00",
    [int]$DaysInterval = 1,
    [string]$Exe = "",
    [string]$Arguments = "",
    [string]$WorkDir = ""
)

$ErrorActionPreference = "Stop"

if ($Action -eq "remove") {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "REMOVED"
    exit 0
}

if ($Action -eq "query") {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -eq $t) { Write-Output "NONE"; exit 0 }
    $i = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Output ("STATE={0}; NEXT={1}; LAST={2}" -f $t.State, $i.NextRunTime, $i.LastRunTime)
    exit 0
}

if (-not (Test-Path $Exe)) { throw "找不到要运行的程序: $Exe" }
if (-not $WorkDir -or -not (Test-Path $WorkDir)) { $WorkDir = Split-Path -Parent $Exe }

if (-not $Arguments) { throw "没给要运行的参数（-Arguments）" }
$act = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $WorkDir
$trg = New-ScheduledTaskTrigger -Daily -DaysInterval $DaysInterval -At $Time
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
$prn = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg `
    -Settings $set -Principal $prn -Force | Out-Null
Write-Output ("OK; every {0} day(s) at {1}" -f $DaysInterval, $Time)
