using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Shapes;

namespace WinUpd
{
    /// <summary>
    /// 自启与后台：上面是"现在跑没跑"，下面左边是两种自启方式，右边是快捷入口和诊断。
    /// </summary>
    public sealed class StartupPage : IPage
    {
        private readonly MainWindow _shell;
        private readonly StackPanel _root = new StackPanel();
        private readonly ScrollViewer _scroller;
        private Ellipse _dot;
        private TextBlock _title;
        private TextBlock _meta;
        private Button _toggle;
        private ToggleButton _startupSwitch;
        private TextBlock _startupState;
        private TextBlock _taskText;
        private bool _updatingSwitch;

        public string Key { get { return "startup"; } }
        public string Title { get { return "自启与后台"; } }
        public FrameworkElement Root { get { return _scroller; } }

        public StartupPage(MainWindow shell)
        {
            _shell = shell;
            _scroller = Ui.Scroller(_root);
        }

        public void LoadData(AppData data)
        {
            _root.Children.Clear();
            _root.Children.Add(Ui.PageHeader("运行与记录", "自启与后台",
                "让后台监控在登录后自动跑起来，并给程序一个正式的通知身份。"));

            _root.Children.Add(StatusCard(data));

            var left = new StackPanel();
            left.Children.Add(Ui.Section("办法一 · 登录自启", "不需要管理员", StartupCard(data)));
            left.Children.Add(Ui.Section("办法二 · 后台任务", "需要管理员", TaskCard(data)));

            var right = new StackPanel();
            right.Children.Add(Ui.Section("快捷方式与身份", null, ShortcutCard()));
            right.Children.Add(Ui.Section("诊断工具", null, DiagCard(), 0));

            _root.Children.Add(Ui.TwoColumn(left, right));
        }

        public void ApplyPoll(PollUpdate poll)
        {
            UpdateStatus();
        }

        private void UpdateStatus()
        {
            var data = _shell.Data;
            bool online = data.WatchOnline;
            bool enabled = data.WatchEnabled;
            if (_dot != null)
                _dot.Fill = (Brush)Application.Current.Resources[
                    online ? "OkBrush" : (enabled ? "WarnBrush" : "LineStrongBrush")];
            if (_title != null)
                _title.Text = data.WatchStatusText;
            if (_meta != null)
            {
                var parts = new List<string>();
                string activity = Json.Str(data.Watch, "activity");
                if (!string.IsNullOrEmpty(activity)) parts.Add(activity);
                string pid = Json.Str(data.Watch, "pid");
                if (!string.IsNullOrEmpty(pid)) parts.Add("进程 " + pid);
                string last = Json.Str(data.Watch, "last_check");
                if (!string.IsNullOrEmpty(last)) parts.Add("上次检查 " + Fmt.Mmdd(last) + " " + Fmt.Hhmm(last));
                if (parts.Count == 0)
                    parts.Add(online ? "正在等下一次检查…"
                        : (enabled ? "点下面的按钮重新开启" : "点下面的按钮开启后台监控"));
                _meta.Text = string.Join(" · ", parts.ToArray());
            }
            if (_toggle != null) _toggle.Content = data.WatchToggleLabel;
            if (_taskText != null && !string.IsNullOrEmpty(data.TaskText))
                _taskText.Text = data.TaskText;
            bool startupEnabled = Json.Bool(data.Startup, "enabled", false);
            if (_startupSwitch != null)
            {
                _updatingSwitch = true;
                _startupSwitch.IsChecked = startupEnabled;
                _updatingSwitch = false;
            }
            if (_startupState != null)
                _startupState.Text = startupEnabled ? "已开启" : "未开启";
        }

        // ---------------------------------------------------------------- 状态
        private FrameworkElement StatusCard(AppData data)
        {
            var content = new StackPanel();
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var left = new StackPanel();
            var line = new StackPanel { Orientation = Orientation.Horizontal };
            _dot = new Ellipse { Width = 10, Height = 10, VerticalAlignment = VerticalAlignment.Center };
            line.Children.Add(_dot);
            _title = Ui.T("正在读取…", null, D.H2, FontWeights.SemiBold);
            _title.FontFamily = (FontFamily)Application.Current.Resources["UiDisplayFont"];
            _title.Margin = new Thickness(D.S3, 0, 0, 0);
            line.Children.Add(_title);
            left.Children.Add(line);
            _meta = Ui.T("", "RowHelp");
            _meta.Margin = new Thickness(20, D.S2, 0, 0);
            _meta.TextWrapping = TextWrapping.Wrap;
            left.Children.Add(_meta);
            grid.Children.Add(left);

            var actions = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                VerticalAlignment = VerticalAlignment.Center
            };
            _toggle = Ui.B("开启后台监控", "BtnPrimary", ToggleWatch);
            actions.Children.Add(_toggle);
            var check = Ui.B("立刻检查", "BtnSecondary", () =>
                _shell.SendAction("check_now", new Dictionary<string, object>(), null,
                    "正在检测…", 90000));
            check.Margin = new Thickness(D.S3, 0, 0, 0);
            actions.Children.Add(check);
            var toast = Ui.B("测试通知", "BtnGhost", () =>
                _shell.SendAction("test_toast", new Dictionary<string, object>(), null,
                    "正在发测试通知…", 20000));
            toast.Margin = new Thickness(D.S3, 0, 0, 0);
            actions.Children.Add(toast);
            Grid.SetColumn(actions, 1);
            grid.Children.Add(actions);
            content.Children.Add(grid);

            content.Children.Add(Ui.Rule(D.S5, D.S5));
            var metrics = new Grid();
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(D.S5) });
            metrics.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var m1 = new StackPanel();
            m1.Children.Add(Ui.T("登录自启", "MetricLabel"));
            _startupState = Ui.T("未开启", "MetricValue");
            m1.Children.Add(_startupState);
            metrics.Children.Add(m1);
            var m2 = new StackPanel();
            Grid.SetColumn(m2, 2);
            m2.Children.Add(Ui.T("后台任务", "MetricLabel"));
            string taskStateText = string.IsNullOrEmpty(data.TaskText) ? "未安装"
                : (data.TaskText.Contains("已安装") ? "已安装" : "见下方");
            var taskState = Ui.T(taskStateText, "MetricValue");
            taskState.TextTrimming = TextTrimming.CharacterEllipsis;
            m2.Children.Add(taskState);
            metrics.Children.Add(m2);
            content.Children.Add(metrics);

            UpdateStatus();
            return Ui.Card(content, D.S5, false, D.S5);
        }

        private void ToggleWatch()
        {
            bool online = _shell.Data.WatchOnline;
            _shell.SendAction("toggle_watch", new Dictionary<string, object>(),
                online ? "已停止后台监控" : "已开启后台监控",
                online ? "正在停止后台监控…" : "正在开启后台监控…", 60000);
        }

        // ---------------------------------------------------------------- 自启
        private FrameworkElement StartupCard(AppData data)
        {
            var sp = new StackPanel();
            sp.Children.Add(Ui.T("登录 Windows 之后自动在右下角跑起来，不需要管理员权限。", "RowHelp"));
            var row = new Grid { Margin = new Thickness(0, D.S4, 0, 0) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var left = new StackPanel();
            left.Children.Add(Ui.T("登录后自动启动", "RowLabel"));
            left.Children.Add(Ui.T("开启后，下次登录就会自动跑", "RowHelp"));
            row.Children.Add(left);
            _startupSwitch = Ui.SwitchRaw(Json.Bool(data.Startup, "enabled", false), v =>
            {
                if (_updatingSwitch) return;
                // 不刷新整页：轮询里带 startup 状态，会在一秒内自然更新开关/状态文字
                _shell.SendAction("toggle_startup", new Dictionary<string, object>(), null,
                    v ? "正在开启登录自启…" : "正在关闭登录自启…", 90000, null, false);
            });
            _startupSwitch.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(_startupSwitch, 1);
            row.Children.Add(_startupSwitch);
            sp.Children.Add(row);

            string link = Json.Str(data.App, "startup_link");
            if (!string.IsNullOrEmpty(link))
            {
                var p = Ui.T(link, "FieldHint");
                p.Margin = new Thickness(0, D.S3, 0, 0);
                p.TextTrimming = TextTrimming.CharacterEllipsis;
                p.ToolTip = link;
                sp.Children.Add(p);
            }
            return Ui.Card(sp);
        }

        private FrameworkElement TaskCard(AppData data)
        {
            var sp = new StackPanel();
            sp.Children.Add(Ui.T("想让它在登录前就开始检查，或者更稳地一直待在后台，用这个办法。安装时会弹一次管理员确认。", "RowHelp"));

            var taskBox = new Border
            {
                Background = (Brush)Application.Current.Resources["Surface2Brush"],
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(8),
                Padding = new Thickness(D.S3, D.S2, D.S3, D.S2),
                Margin = new Thickness(0, D.S4, 0, 0)
            };
            _taskText = Ui.T(string.IsNullOrEmpty(data.TaskText) ? "正在查询…" : data.TaskText,
                "MonoText", 11.5);
            _taskText.TextWrapping = TextWrapping.Wrap;
            taskBox.Child = _taskText;
            sp.Children.Add(taskBox);

            var actions = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, D.S4, 0, 0) };
            actions.Children.Add(Ui.B("安装后台任务", "BtnSecondary", () =>
                _shell.SendAction("install_task", new Dictionary<string, object>(), null,
                    "正在安装后台任务…（需要管理员确认）", 180000, r => _shell.RefreshSoon())));
            var remove = Ui.B("移除", "BtnGhost", () => { });
            remove.Margin = new Thickness(D.S3, 0, 0, 0);
            remove.Click += (s, e) =>
            {
                if (!_shell.ConfirmThen(remove, "再点一次移除")) return;
                _shell.SendAction("remove_task", new Dictionary<string, object>(), null,
                    "正在移除后台任务…", 180000, r => _shell.RefreshSoon());
            };
            actions.Children.Add(remove);
            var refresh = Ui.Link("刷新状态", () =>
                _shell.SendAction("refresh_task_info", new Dictionary<string, object>(), null,
                    null, 30000, r => _shell.RefreshSoon()));
            refresh.Margin = new Thickness(D.S3, 0, 0, 0);
            actions.Children.Add(refresh);
            sp.Children.Add(actions);
            var hint = Ui.T("如果管理员确认被取消了，可以改用上面的「登录自启」这个免管理员办法。", "FieldHint");
            hint.Margin = new Thickness(0, D.S3, 0, 0);
            sp.Children.Add(hint);
            return Ui.Card(sp);
        }

        // ---------------------------------------------------------------- 右栏
        private FrameworkElement ShortcutCard()
        {
            var sp = new StackPanel();
            sp.Children.Add(IconRow("\uE8B5", "创建桌面快捷方式", () =>
                _shell.SendAction("make_shortcut", new Dictionary<string, object>
                {
                    { "where", "desktop" }
                }, "已创建桌面快捷方式", null, 30000)));
            sp.Children.Add(IconRow("\uE71D", "添加到开始菜单", () =>
                _shell.SendAction("make_shortcut", new Dictionary<string, object>
                {
                    { "where", "startmenu" }
                }, "已添加到开始菜单", null, 30000)));
            sp.Children.Add(IconRow("\uEA8F", "注册通知身份", () =>
                _shell.SendAction("register_app", new Dictionary<string, object>(),
                    "已注册通知身份", null, 30000)));
            var hint = Ui.T("注册之后，通知里会显示程序的名字和图标；只需要做一次。", "FieldHint");
            hint.Margin = new Thickness(0, D.S2, 0, 0);
            sp.Children.Add(hint);
            return Ui.Card(sp);
        }

        private FrameworkElement DiagCard()
        {
            var sp = new StackPanel();
            sp.Children.Add(IconRow("\uE9D9", "体检并自动修复", () =>
                _shell.SendAction("run_selfcheck", new Dictionary<string, object>(),
                    null, "正在体检…", 60000, r => _shell.Navigate("logs"))));
            sp.Children.Add(IconRow("\uEA8F", "发一条测试通知", () =>
                _shell.SendAction("test_toast", new Dictionary<string, object>(), null,
                    "正在发测试通知…", 20000)));
            sp.Children.Add(IconRow("\uE756", "打开日志文件", () => _shell.OpenExternal("log")));
            sp.Children.Add(IconRow("\uE8B7", "打开程序目录", () => _shell.OpenExternal("app_folder")));
            sp.Children.Add(IconRow("\uE7C3", "打开报告目录", () => _shell.OpenExternal("report_folder")));
            var hint = Ui.T("体检会修好能修的问题，结果显示在「日志与诊断」里。", "FieldHint");
            hint.Margin = new Thickness(0, D.S2, 0, 0);
            sp.Children.Add(hint);
            return Ui.Card(sp);
        }

        private static FrameworkElement IconRow(string glyph, string text, Action click)
        {
            var btn = new Button
            {
                Style = (Style)Application.Current.Resources["BtnGhost"],
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Padding = new Thickness(D.S2, D.S2, D.S2, D.S2),
                Margin = new Thickness(0, 0, 0, 1)
            };
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(28) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var icon = Ui.Glyph(glyph, 14, (Brush)Application.Current.Resources["Ink2Brush"]);
            grid.Children.Add(icon);
            var label = Ui.T(text, null, 13);
            Grid.SetColumn(label, 1);
            label.VerticalAlignment = VerticalAlignment.Center;
            grid.Children.Add(label);
            var chev = Ui.Glyph("\uE76C", 10, (Brush)Application.Current.Resources["Ink3Brush"]);
            Grid.SetColumn(chev, 2);
            grid.Children.Add(chev);
            btn.Content = grid;
            btn.Click += (s, e) => click();
            return btn;
        }
    }
}
