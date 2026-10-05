# 安装 / 删除 / 查询计划任务
#
# 两种模式：
#   -Mode watch  （默认，新版）  常驻哨兵：登录时启动、一直开着，每隔几分钟问一次官方看板
#   -Mode daily  （旧版）        每天定时跑一次检测（现在不再需要，保留只为兼容）
#
# 哨兵是「常驻进程」，设置上必须和「跑一次就退出」的任务不一样，否则会被系统杀掉：
#   * ExecutionTimeLimit = PT0S（不限时）—— 默认是 3 天，而旧脚本里写死了 30 分钟，
#     常驻程序到点就被终止，表现成「刚还能用，过一会儿就没动静了」，非常难查
#   * 崩了自动重启（RestartCount / RestartInterval）
#   * 切到电池、进入空闲都不许停
#   * MultipleInstances IgnoreNew：重复触发不会起出第二个哨兵
#
# 注意：参数不能叫 $Args —— 那是 PowerShell 的自动变量，会被静默吃掉。
param(
    [string]$Action = "install",       # install | remove | query
    [string]$Mode = "watch",           # watch | daily
    [string]$TaskName = "",            # 留空则按 Mode 取默认名
    [string]$Time = "12:00",
    [int]$DaysInterval = 1,
    [string]$Exe = "",
    [string]$Arguments = "",
    [string]$WorkDir = "",
    [string]$AlsoRemove = "",          # 安装时顺便卸掉的旧任务名（逗号分隔）
    [int]$LogonDelaySeconds = 15,
    [switch]$AtLogon
)

$ErrorActionPreference = "Stop"

$watchName = "WinUpdReport_Watch"
$dailyName = "WinUpdReport_Daily"
if (-not $TaskName) {
    $TaskName = if ($Mode -eq "daily") { $dailyName } else { $watchName }
}

function Remove-One([string]$name) {
    if (-not $name) { return }
    $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($null -ne $t) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Output "REMOVED $name"
    } else {
        Write-Output "NOTFOUND $name"
    }
}

if ($Action -eq "remove") {
    Remove-One $TaskName
    if ($AlsoRemove) {
        foreach ($n in ($AlsoRemove -split ",")) { Remove-One $n.Trim() }
    }
    exit 0
}

if ($Action -eq "query") {
    foreach ($name in @($TaskName, $watchName, $dailyName) | Select-Object -Unique) {
        $t = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
        if ($null -eq $t) {
            Write-Output ("{0}: NONE" -f $name)
            continue
        }
        $i = Get-ScheduledTaskInfo -TaskName $name
        $kinds = @($t.Triggers | ForEach-Object {
            $_.CimClass.CimClassName -replace '^MSFT_Task', '' -replace 'Trigger$', '' })
        Write-Output ("{0}: STATE={1}; NEXT={2}; LAST={3}; TRIGGERS={4}; LIMIT={5}" -f `
            $name, $t.State, $i.NextRunTime, $i.LastRunTime, ($kinds -join "+"), `
            $t.Settings.ExecutionTimeLimit)
    }
    exit 0
}

if (-not (Test-Path $Exe)) { throw "找不到要运行的程序: $Exe" }
if (-not $WorkDir -or -not (Test-Path $WorkDir)) { $WorkDir = Split-Path -Parent $Exe }
if (-not $Arguments) { throw "没给要运行的参数（-Arguments）" }

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

if ($Mode -eq "daily") {
    # ---------------- 旧版：每天（或每 N 天）定时跑一次 ----------------
    $logonArguments = if ($Arguments -match '--at-logon') { $Arguments } else { "$Arguments --at-logon" }
    $dailyAct = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $WorkDir
    $logonAct = New-ScheduledTaskAction -Execute $Exe -Argument $logonArguments -WorkingDirectory $WorkDir
    $act = @($dailyAct)
    $trg = @(New-ScheduledTaskTrigger -Daily -DaysInterval $DaysInterval -At $Time)
    if ($AtLogon) {
        $logonTrg = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
        $logonTrg.Delay = "PT2M"
        $trg += $logonTrg
        $act += $logonAct
    }
    $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
    Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg `
        -Settings $set -Principal $principal -Force | Out-Null
    if ($AlsoRemove) {
        foreach ($n in ($AlsoRemove -split ",")) { Remove-One $n.Trim() }
    }
    Write-Output ("OK; daily every {0} day(s) at {1}" -f $DaysInterval, $Time)
    exit 0
}

# ---------------- 新版：常驻哨兵 ----------------
# 先按“常驻”要求构造设置。不同 Windows 版本支持的参数不完全一样，所以：
# 先用完整参数试一次，不行就退回基础参数，再逐项用属性补上。
# 绝不能因为某个可选设置装不上，就整个任务都装不了。
try {
    $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0)
} catch {
    Write-Output ("WARN: 完整参数不被支持，改用基础参数再逐项设置（" + `
                  $_.Exception.Message + "）")
    $set = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden `
        -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew
}

$tweaks = @(
    @{ Name = "ExecutionTimeLimit";         Value = "PT0S" },  # 不限时（最关键）
    @{ Name = "RestartCount";               Value = 3 },       # 崩了自动重启
    @{ Name = "RestartInterval";            Value = "PT1M" },
    @{ Name = "DisallowStartIfOnBatteries"; Value = $false },
    @{ Name = "StopIfGoingOnBatteries";     Value = $false }
)
foreach ($t in $tweaks) {
    try { $set.($t.Name) = $t.Value } catch { }
}
try { $set.IdleSettings.StopOnIdleEnd = $false } catch { }

$trg = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
# 登录瞬间系统很忙，稍等几秒再起来；只是错过几秒，不影响「一有新版本就通知」
try { $trg.Delay = "PT${LogonDelaySeconds}S" } catch { }

$act = New-ScheduledTaskAction -Execute $Exe -Argument $Arguments -WorkingDirectory $WorkDir

Register-ScheduledTask -TaskName $TaskName -Action $act -Trigger $trg `
    -Settings $set -Principal $principal -Force | Out-Null

# 顺便把旧的每日任务卸掉：哨兵已经取代它了，留着会重复检测、重复通知
if (-not $AlsoRemove) { $AlsoRemove = $dailyName }
foreach ($n in ($AlsoRemove -split ",")) {
    if ($n.Trim() -and $n.Trim() -ne $TaskName) { Remove-One $n.Trim() }
}

$limit = (Get-ScheduledTask -TaskName $TaskName).Settings.ExecutionTimeLimit
Write-Output ("OK; watch mode (at logon, limit={0}, auto-restart=3)" -f $limit)
