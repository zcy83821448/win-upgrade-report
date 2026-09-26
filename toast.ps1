# 弹出一条 Windows 通知，点击正文 / 按钮都走自定义协议，交给 viewer.py 处理
param(
    [Parameter(Mandatory=$true)][string]$AppId,
    [Parameter(Mandatory=$true)][string]$Title,
    [Parameter(Mandatory=$true)][string]$Body,
    [string]$Protocol = "winupdrept",
    [string]$Arg1 = "",              # 点击通知正文时传的参数
    [string]$Arg2 = "",
    [string]$Button1 = "",
    [string]$Button2 = "",
    [string]$Tag = "winupd",
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType=WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime]

function Esc([string]$s) { return [System.Security.SecurityElement]::Escape($s) }
function Uri([string]$s) { return [System.Uri]::EscapeDataString($s) }

$actions = ""
if ($Button1) { $actions += "<action content=`"$(Esc $Button1)`" activationType=`"protocol`" arguments=`"$Protocol`:$Arg1`" />" }
if ($Button2) { $actions += "<action content=`"$(Esc $Button2)`" activationType=`"protocol`" arguments=`"$Protocol`:$Arg2`" />" }
$actionsXml = ""
if ($actions -ne "") { $actionsXml = "<actions>$actions</actions>" }

$audio = ""
if ($Silent) { $audio = "<audio silent=`"true`" />" }

$xml = @"
<toast activationType="protocol" launch="$Protocol`:$Arg1" duration="long" tag="$(Esc $Tag)">
  <visual>
    <binding template="ToastGeneric">
      <text>$(Esc $Title)</text>
      <text>$(Esc $Body)</text>
      <text placement="attribution">win升级报告</text>
    </binding>
  </visual>
  $actionsXml
  $audio
</toast>
"@

$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = New-Object Windows.UI.Notifications.ToastNotification $doc
$toast.Tag = $Tag
$toast.Group = "winupd"
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId).Show($toast)
Write-Output "OK"
