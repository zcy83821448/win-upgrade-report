# win升级报告

静默盯着你挑的 Windows 更新线（任意 Insider 频道 / 正式版线）：每天定时去看有没有新构建，
有的话用 DeepSeek 把微软官方的发布说明整理成一份简短的中文 Markdown 报告，然后弹一条 Windows
通知。点通知就能看到排版好的报告。

检测过程没有窗口、没有提示音、不打扰你；只有**真的出了新版本**才通知一次。

## 支持哪些更新线

设置界面「更新线」页可以直接勾选，两类来源：

| 来源 | 覆盖范围 | 为什么用两套 |
| --- | --- | --- |
| **微软 Flight Hub**（`learn.microsoft.com/windows-insider/flight-hub/`） | 所有 Insider 频道：26H2 Experimental、26H1 Experimental、未来平台、Beta、26H1 Beta、Release Preview（26H1、24H2/25H2） | 这是微软官方看板，既能拿到构建号，也能**直接拿到该构建官方发布说明的精确链接**，最可靠 |
| **uupdump**（`uupdump.net`） | 正式版 / 零售版本线：26H2、25H2、24H2、23H2…… 以及 Server | Flight Hub 不管正式版线，这些只有 uupdump 有 |

两条来源的构建号判定标准一样：**构建号变大 = 有新版本**（例如 28120.3002 → 28120.3122）。
每次运行还会顺带把 Flight Hub 上新出现的频道自动收进列表（默认不启用，勾一下就能用）。

## 它是怎么跑的

```
计划任务(每天 12:00, 隐藏窗口)
   └─ pythonw checker.py
        ├─ 1. 抓 Flight Hub（一次抓取，所有 Insider 线共用）+ 各 uupdump 线
        │     得到每条线的最新构建号                    ← 这一步不调用 AI
        ├─ 2. 和 state.json 里每条线记录的版本比
        │     没变 → 记一笔日志就退出（你完全察觉不到）
        │     变了 ↓
        ├─ 3. 取该构建的微软官方发布说明原文
        │     Flight Hub 已给出精确链接；正式版线按构建号去 Learn 搜索 / 网页搜索找
        ├─ 4. 把原文丢给 DeepSeek（deepseek-flash，思考模式关闭）
        │     按固定模板写成简短中文 Markdown
        ├─ 5. 存到 reports\<更新线>\更新报告_构建号_日期.md，并更新总览页
        └─ 6. 发 Windows 通知 ──点击──> winupdrept: 协议 → viewer.py → 渲染成网页打开
```

几个刻意的设计：

- **首次运行只记基线**，不写报告也不通知——不然第一天就报一次没意义的"更新"。
- **只跟上一版比**，中间跳过的版本不会补报。
- 官方说明偶尔取不到（新构建刚发布、页面还没生成）：照常写报告，但会写明"未取到官方原文"，
  并附上失败原因，不会默默什么都不做。
- 同一天只跑一次；`interval_days > 1` 时没到间隔天数直接退出；关机时错过的那次会在开机后补跑。
- 通知被静默时段挡住时（可配 `23:00-07:00`），先攒着，出了时段补一条汇总通知。

## 应用程序（打包成 exe）

`应用程序\win升级报告.exe` 是打包好的单文件程序（约 10 MB，自带 Python 运行时，**换台电脑
不用装任何东西**）。双击就是设置界面。

```
应用程序\
  win升级报告.exe      双击 = 设置界面；计划任务和通知协议都指向它
  使用说明.txt         给使用者看的简短说明
```

它按参数分流：

| 命令 | 作用 |
| --- | --- |
| `win升级报告.exe` | 设置界面 |
| `win升级报告.exe --check` | 跑一次检测（计划任务用的就是这个） |
| `win升级报告.exe --check --force` | 忽略「今天跑过」，立刻检测 |
| `win升级报告.exe --list-channels` | 列出更新线和当前记录 |
| `win升级报告.exe --view index` | 打开报告总览页 |
| `win升级报告.exe --task query` | 查计划任务状态 |
| `win升级报告.exe --task install 12:00 1` | 装计划任务（弹 UAC） |
| `win升级报告.exe --selftest --with-gui` | 自检，结果写到 `logs\自检报告.txt` |

**数据放哪**：exe 会先找自己同目录有没有 `config.json`，没有就找上一级目录——所以现在
`config.json / state.json / reports / logs` 仍在 `win升级报告\` 这一层，exe 自动用它们。
把这几样一起拷进 `应用程序\` 里，这个文件夹就成了完全独立、能整体拷走的绿色版。

**重新打包**：改了源码后跑 `python 打包.py`（加 `--verify` 会顺便自检一遍）。

## 怎么用

1. 双击 **应用程序\win升级报告.exe**（或根目录的 `打开设置界面.bat`）。
2. **更新线**页：点「从 Flight Hub 刷新频道列表」→ 双击要盯的线启用（默认已启用
   26H2 Experimental）→ 还可以在下面加自定义 uupdump 分类。
3. **DeepSeek API** 页：在「API Key」框里粘贴你的 Key（从
   [platform.deepseek.com](https://platform.deepseek.com/api_keys) 拿），点「测试 Key 与模型」。
   Key 只存在本机 `config.json` 里，不会上传到任何地方。
4. **检测与通知**页：确认时间（默认 `12:00`）、间隔、报告详细程度。
5. **计划任务**页：点「安装 / 更新计划任务」→ 弹一次 UAC 点「是」。
   不想给管理员权限就用「装/卸 登录自启」。顺手可以点「在桌面放快捷方式」。
6. 点「保存设置」收工。想立刻验证整条链路：点下面的「立即检测全部」，
   过程会实时显示在「状态与日志」页里（不弹控制台）。

> 改了时间/间隔/更新线后，要再点一次「安装 / 更新计划任务」让任务参数同步。

## 界面各页说明

| 页 | 内容 |
| --- | --- |
| **更新线** | 全部可选频道列表（☑/☐）、双击启停、选中看详情、单条线立即检测、忽略某个版本、改架构（amd64/arm64）、添加自定义 uupdump 分类 |
| **检测与通知** | 检测时间、间隔天数、静默时段、通知开关、多线合并通知、连续失败几次后告警、报告详细程度（简短/标准/详细）、是否附官方原文、报告保留份数 |
| **DeepSeek API** | API 地址、模型、API Key、关闭思考模式、max_tokens / temperature / 超时 / 重试 / 代理、原文喂给模型的上限 |
| **计划任务** | 安装/删除计划任务、立即静默跑一次、免管理员的登录自启、注册通知协议 |
| **状态与日志** | 每条线当前基线、上次运行、待补发通知、最近错误，以及 `logs\checker.log` 的内容 |

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `应用程序\win升级报告.exe` | 打包好的应用程序（单文件，自带运行环境） |
| `app.py` | exe 的入口，按参数分流到界面 / 检测 / 查看器 |
| `打包.py` | 用 PyInstaller 重新打包到 `应用程序\` |
| `gui.py` / `打开设置界面.bat` | 设置界面（源码方式运行） |
| `checker.py` | 检测主程序 |
| `channels.py` | 更新线定义、Flight Hub 页面解析、预设频道表 |
| `source.py` | 所有抓取：Flight Hub、uupdump、官方发布说明（三级回退 + 重试 + 代理） |
| `deepseek_api.py` | DeepSeek 调用、提示词模板、兜底报告 |
| `reporter.py` | 写报告、按频道归档、清理旧报告、生成总览页 |
| `notify.py` / `toast.ps1` | Windows 通知 + 注册 AUMID 和 `winupdrept:` 协议 |
| `viewer.py` | 通知点击后打开的查看器（Markdown → 排版好的网页） |
| `mdlite.py` | 自带的极简 Markdown 渲染（无第三方依赖） |
| `task.ps1` | 计划任务注册/删除（PowerShell 计划任务模块） |
| `config.json` | 所有设置（含更新线列表） |
| `state.json` | 每条线的当前版本、上次检测、报告历史、忽略列表、失败计数 |
| `reports\<更新线>\` | 各条线的报告（`.md` 原件 + `.html` 渲染页） |
| `reports\总览.html` | 所有报告的时间线 + 各线当前基线 |
| `logs\checker.log` | 运行日志，出问题先看它 |

## 命令行

```bat
python checker.py --list-channels            列出所有更新线和当前记录
python checker.py --dry-run --verbose        只抓数据看会做什么，不调 API、不写文件、不通知
python checker.py --force --verbose          忽略「今天跑过」和间隔，完整跑一遍
python checker.py --only fh:experimental --force   只测某一条线
python checker.py --no-notify --force        跑但这次不通知
python notify.py --test                      发一条测试通知
python viewer.py index                       打开总览页（也可 folder / log / r/<线>/<构建号>）
```

## 可调参数（config.json）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `channels` | 26H2 Experimental | 更新线列表：`source` = flighthub / uupdump，`enabled` 是否监控，`arch` 架构偏好 |
| `check_time` / `interval_days` | `12:00` / `1` | 每天触发时间 / 每隔几天真正检测一次 |
| `quiet_hours` | 空 | 静默时段，如 `23:00-07:00`；期间的通知攒到时段外补发 |
| `api_key` | 空 | DeepSeek 的 Key，在设置界面「DeepSeek API」页填，存本机 `config.json` |
| `model` / `disable_thinking` | `deepseek-flash` / `true` | 模型与思考模式开关 |
| `detail` | `标准` | 报告详细程度：简短 / 标准 / 详细 |
| `include_official_text` | `false` | 报告末尾附官方原文全文 |
| `merge_notifications` | `true` | 一次多条线更新时合并成一条通知 |
| `notify_on_error_after` | `3` | 连续失败几次后发一次错误通知，0 = 不发 |
| `proxy` | 空 | 例如 `http://127.0.0.1:7897`，留空直连 |
| `retries` | `2` | 网络请求重试次数 |
| `keep_reports` | `200` | 每条线最多保留多少份报告 |
| `auto_discover_channels` | `true` | 自动收录 Flight Hub 上新出现的频道（默认不启用） |

## 已知限制 / 排错

- **通知可能被专注助手/勿扰吞掉**：控制面板 → 系统 → 通知，确认「win升级报告」没被静音。
- **改了 `.ps1` 里的中文注释后通知失灵**：PowerShell 5.1 要求 `.ps1` 带 UTF-8 BOM，
  程序启动时会自动补 BOM（`notify.ensure_bom`）。手动编辑后如果报"找不到参数名"，就是这个原因。
  （另外 PowerShell 参数别叫 `$Args`——那是自动变量，会被静默吃掉，所以用的是 `$Arguments`。）
- **uupdump / Flight Hub 改版**：日志会写"没解析到任何版本/频道"，改 `source.py` 里的正则。
- **想重报某个版本**：在「更新线」页选中该线 →「清除忽略」，或删掉 `state.json` 里该频道的
  `last_version` 再跑一次 `--force`。
- **换到别的时间线**：勾选时自动按构建号大小判断，不会因为换线而产生错误比较；但建议清掉该线
  `last_version` 重新建基线。
- **exe 被杀软拦**：PyInstaller 单文件程序常被误报，加个白名单即可；这也是不用安装包的原因。
- **exe 启动比源码慢一点**：单文件模式每次启动要先把自己解压到临时目录，约 1 秒。
  嫌慢可以改成 `--onedir`（`打包.py` 里 `--onefile` 换掉），出来是个文件夹，启动快很多。

## 构建者

| 角色 | 谁 |
| --- | --- |
| 需求、设计取舍、试运行与验收 | [@zcy83821448](https://github.com/zcy83821448) |
| 代码实现、文档编写 | Claude Code（Anthropic） |

这个工具是**结对写出来的**：上面每个模块、这份 README、`打包.py` 都是在对话里一轮一轮长出来的。
作者定需求、跑真实环境、指出哪里不对；Claude Code 负责查资料、写实现、改 bug。
抓取失败怎么降级、通知怎么防打扰、报告模板怎么定，都是两边来回磨出来的。
