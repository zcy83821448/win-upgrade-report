using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Shapes;

namespace WinUpd
{
    /// <summary>
    /// 概览：先回答"现在什么状态"，再给"最近一份报告"，然后是明细。
    /// 三段式从上到下，视线走一条直线，不需要到处找。
    /// </summary>
    public sealed class OverviewPage : IPage
    {
        private readonly MainWindow _shell;
        private readonly StackPanel _root = new StackPanel();
        private readonly ScrollViewer _scroller;
        private Ellipse _watchDot;
        private TextBlock _watchTitle;
        private TextBlock _watchMeta;
        private Button _watchBtn;
        private TextBlock _mInterval;
        private TextBlock _mLast;
        private TextBlock _mWatching;

        public string Key { get { return "overview"; } }
        public string Title { get { return "概览"; } }
        public FrameworkElement Root { get { return _scroller; } }

        public OverviewPage(MainWindow shell)
        {
            _shell = shell;
            _scroller = Ui.Scroller(_root);
        }

        public void LoadData(AppData data)
        {
            _root.Children.Clear();

            var check = Ui.B("立刻检查", "BtnPrimary", CheckNow);
            var all = Ui.B("全部报告", "BtnSecondary", () => _shell.Navigate("reports"));
            _root.Children.Add(Ui.PageHeader("监控", "概览",
                "后台监控的状态、正在盯的更新线和最近一份中文报告。", check, all));

            _root.Children.Add(BuildHero(data));
            _root.Children.Add(BuildLatestReport(data));
            _root.Children.Add(BuildChannelSection(data));
            _root.Children.Add(BuildBottom(data));
        }

        public void ApplyPoll(PollUpdate poll)
        {
            if (_watchTitle == null) return;
            UpdateWatchLabels();
        }

        // ---------------------------------------------------------------- 状态
        private FrameworkElement BuildHero(AppData data)
        {
            var content = new StackPanel();

            var top = new Grid();
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var left = new StackPanel();
            var line = new StackPanel { Orientation = Orientation.Horizontal };
            _watchDot = new Ellipse { Width = 10, Height = 10, VerticalAlignment = VerticalAlignment.Center };
            line.Children.Add(_watchDot);
            _watchTitle = Ui.T("正在读取…", null, D.H2, FontWeights.SemiBold);
            _watchTitle.Margin = new Thickness(D.S3, 0, 0, 0);
            _watchTitle.FontFamily = (FontFamily)Application.Current.Resources["UiDisplayFont"];
            line.Children.Add(_watchTitle);
            left.Children.Add(line);
            _watchMeta = Ui.T("", "RowHelp");
            _watchMeta.Margin = new Thickness(20, D.S2, 0, 0);
            _watchMeta.TextWrapping = TextWrapping.Wrap;
            _watchMeta.MaxWidth = 520;
            left.Children.Add(_watchMeta);
            top.Children.Add(left);

            _watchBtn = Ui.B("开启后台监控", "BtnPrimary", ToggleWatch);
            _watchBtn.VerticalAlignment = VerticalAlignment.Center;
            _watchBtn.Margin = new Thickness(D.S5, 0, 0, 0);
            Grid.SetColumn(_watchBtn, 1);
            top.Children.Add(_watchBtn);
            content.Children.Add(top);

            content.Children.Add(Ui.Rule(D.S5, D.S5));

            var metrics = new Grid();
            _mInterval = AddMetric(metrics, 0, "检查间隔", "每 5 分钟");
            _mLast = AddMetric(metrics, 2, "上次检查", "还没检查过");
            _mWatching = AddMetric(metrics, 4, "正在盯", "0 条更新线");
            content.Children.Add(metrics);

            UpdateWatchLabelsFrom(data);
            return Ui.Card(content, D.S5, false, D.S5);
        }

        private static TextBlock AddMetric(Grid grid, int col, string label, string value)
        {
            if (col > 0) grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(D.S5) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var sp = new StackPanel();
            sp.Children.Add(Ui.T(label, "MetricLabel"));
            var v = Ui.T(value, "MetricValue");
            sp.Children.Add(v);
            Grid.SetColumn(sp, grid.ColumnDefinitions.Count - 1);
            grid.Children.Add(sp);
            return v;
        }

        private void UpdateWatchLabels()
        {
            var data = _shell.Data;
            bool online = data.WatchOnline;
            bool enabled = data.WatchEnabled;
            int interval = Json.Int(data.Config, "watch_interval_minutes", 5);
            if (_watchDot != null)
                _watchDot.Fill = (Brush)Application.Current.Resources[
                    online ? "OkBrush" : (enabled ? "WarnBrush" : "LineStrongBrush")];
            _watchTitle.Text = data.WatchStatusText;
            if (_watchBtn != null)
                _watchBtn.Content = data.WatchToggleLabel;

            var parts = new List<string>();
            string watching = EnabledChannelNames(data);
            if (!string.IsNullOrEmpty(watching)) parts.Add("正在盯 " + watching);
            parts.Add("每 " + interval + " 分钟检查一次");
            string last = Json.Str(data.Watch, "last_check");
            if (!string.IsNullOrEmpty(last)) parts.Add("上次检查 " + Fmt.Mmdd(last) + " " + Fmt.Hhmm(last));
            string activity = Json.Str(data.Watch, "activity");
            if (online && !string.IsNullOrEmpty(activity)) parts.Add(activity);
            if (_watchMeta != null) _watchMeta.Text = string.Join(" · ", parts.ToArray());

            if (_mInterval != null) _mInterval.Text = "每 " + interval + " 分钟";
            if (_mLast != null)
                _mLast.Text = string.IsNullOrEmpty(last) ? "还没检查过" : Fmt.Mmdd(last) + " " + Fmt.Hhmm(last);
            if (_mWatching != null)
            {
                int count = 0;
                foreach (var c in data.Channels)
                    if (Json.Bool(c, "enabled", false)) count++;
                _mWatching.Text = count + " 条更新线";
            }
        }

        private void UpdateWatchLabelsFrom(AppData data)
        {
            UpdateWatchLabels();
        }

        private static string EnabledChannelNames(AppData data)
        {
            var names = new List<string>();
            foreach (var c in data.Channels)
            {
                if (!Json.Bool(c, "enabled", false)) continue;
                names.Add(Fmt.CompactName(Json.Str(c, "name")));
                if (names.Count >= 2) break;
            }
            return string.Join("、", names.ToArray());
        }

        private void ToggleWatch()
        {
            // 和 gui.toggle_watch 一样按"哨兵在不在跑"决定动作，文案才和点下去的结果一致
            bool online = _shell.Data.WatchOnline;
            _shell.SendAction("toggle_watch", new Dictionary<string, object>(),
                online ? "已停止后台监控" : "已开启后台监控",
                online ? "正在停止后台监控…" : "正在开启后台监控…", 60000);
        }

        private void CheckNow()
        {
            _shell.SendAction("check_now", new Dictionary<string, object>(), null,
                "正在检测更新…", 90000);
        }

        // ---------------------------------------------------------------- 最新报告
        private FrameworkElement BuildLatestReport(AppData data)
        {
            var reports = data.Reports;
            if (reports.Count == 0)
            {
                var empty = Ui.Empty("还没有报告", "检测到新版本后，这里会出现中文解读。",
                    Ui.B("去选更新线", "BtnSecondary", () => _shell.Navigate("channels")));
                return Ui.Section("最新报告", null, Ui.Card(empty), D.SectionGap);
            }
            var r = reports[0];
            var card = new StackPanel();

            var head = new Grid();
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var meta = new StackPanel { Orientation = Orientation.Horizontal };
            var pill = new Border
            {
                Style = (Style)Application.Current.Resources["TagAccent"],
                Padding = new Thickness(8, 2, 8, 2),
                Margin = new Thickness(0, 0, D.S3, 0)
            };
            pill.Child = Ui.T("最新", null, 11.5, null,
                (Brush)Application.Current.Resources["AccentBrush"]);
            meta.Children.Add(pill);
            string build = Json.Str(r, "build");
            string date = Json.Str(r, "date");
            if (string.IsNullOrEmpty(date)) date = Json.Str(r, "mtime");
            meta.Children.Add(Ui.T(Fmt.CompactName(Json.Str(r, "channel_name")), null, 13,
                FontWeights.SemiBold));
            var sub = Ui.T("  " + build + " · " + Fmt.Mmdd(date), null, 12.5, null,
                (Brush)Application.Current.Resources["Ink2Brush"]);
            sub.VerticalAlignment = VerticalAlignment.Center;
            meta.Children.Add(sub);
            head.Children.Add(meta);

            var read = Ui.B("阅读报告", "BtnPrimary", () =>
                _shell.OpenReport(Json.Str(r, "file"), Json.Str(r, "channel_name")));
            Grid.SetColumn(read, 1);
            head.Children.Add(read);
            card.Children.Add(head);

            string summary = Json.Str(r, "summary");
            if (string.IsNullOrEmpty(summary)) summary = "（这份报告没有一句话总结）";
            var sum = Ui.T(summary, null, D.Subhead, FontWeights.SemiBold);
            sum.TextWrapping = TextWrapping.Wrap;
            sum.LineHeight = 24;
            sum.LineStackingStrategy = LineStackingStrategy.BlockLineHeight;
            sum.Margin = new Thickness(0, D.S4, 0, 0);
            sum.MaxWidth = 600;
            sum.HorizontalAlignment = HorizontalAlignment.Left;
            card.Children.Add(sum);

            return Ui.Section("最新报告", "打开后可进入阅读模式", Ui.Card(card), D.SectionGap);
        }

        // ---------------------------------------------------------------- 更新线状态
        private FrameworkElement BuildChannelSection(AppData data)
        {
            var enabled = new List<Dictionary<string, object>>();
            foreach (var c in data.Channels)
                if (Json.Bool(c, "enabled", false)) enabled.Add(c);

            var card = new StackPanel();
            var header = new Grid { Margin = new Thickness(D.S5, 0, D.S5, 0) };
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(150) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(110) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(54) });
            AddHead(header, 0, "更新线", TextAlignment.Left);
            AddHead(header, 1, "当前版本", TextAlignment.Left);
            AddHead(header, 2, "上次检测", TextAlignment.Left);
            AddHead(header, 3, "报告", TextAlignment.Right);
            var headBorder = new Border
            {
                Padding = new Thickness(0, D.S4, 0, D.S3),
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(0, 0, 0, 1),
                Child = header
            };
            card.Children.Add(headBorder);

            if (enabled.Count == 0)
            {
                card.Children.Add(Ui.Empty("还没有启用的更新线", "去「更新线」页选一条，后台就会开始检查它。",
                    Ui.B("选择更新线", "BtnSecondary", () => _shell.Navigate("channels"))));
            }
            foreach (var ch in enabled) card.Children.Add(ChannelRow(data, ch));

            int index = 0;
            foreach (UIElement child in card.Children)
            {
                var border = child as Border;
                if (border != null && index > 0)
                    border.BorderBrush = (Brush)Application.Current.Resources["LineBrush"];
                index++;
            }
            return Ui.Section("更新线状态", enabled.Count + " 条已启用", Ui.Card(card, 0), D.SectionGap);
        }

        private static void AddHead(Grid grid, int col, string text, TextAlignment align)
        {
            var t = Ui.T(text, "TableHead");
            t.HorizontalAlignment = align == TextAlignment.Right
                ? HorizontalAlignment.Right : HorizontalAlignment.Left;
            Grid.SetColumn(t, col);
            grid.Children.Add(t);
        }

        private FrameworkElement ChannelRow(AppData data, Dictionary<string, object> ch)
        {
            string id = Json.Str(ch, "id");
            var st = data.ChannelState(id) ?? new Dictionary<string, object>();
            var row = new Grid { Margin = new Thickness(D.S5, D.S3, D.S5, D.S3), Cursor = System.Windows.Input.Cursors.Hand };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(150) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(110) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(54) });

            var nameGrid = new Grid();
            nameGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            nameGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var nameText = Ui.T(Json.Str(ch, "name"), null, 13);
            nameText.TextTrimming = TextTrimming.CharacterEllipsis;
            nameText.Margin = new Thickness(0, 0, D.S3, 0);
            nameText.ToolTip = Json.Str(ch, "name");
            nameGrid.Children.Add(nameText);
            string source = Json.Str(ch, "source");
            var tag = new Border { Style = (Style)Application.Current.Resources["TagQuiet"] };
            tag.Child = Ui.T(source == "flighthub" ? "Flight Hub" : "uupdump", null, 11,
                null, (Brush)Application.Current.Resources["Ink3Brush"]);
            Grid.SetColumn(tag, 1);
            nameGrid.Children.Add(tag);
            row.Children.Add(nameGrid);

            var ver = Ui.T(Json.Str(st, "last_version", "还没检测过"), null, 12.5);
            if (string.IsNullOrEmpty(Json.Str(st, "last_version")))
                ver.Foreground = (Brush)Application.Current.Resources["Ink3Brush"];
            Grid.SetColumn(ver, 1);
            row.Children.Add(ver);

            var date = Ui.T(Fmt.Mmdd(Json.Str(st, "last_check_date")), null, 12.5,
                null, (Brush)Application.Current.Resources["Ink2Brush"]);
            Grid.SetColumn(date, 2);
            row.Children.Add(date);

            string report = Json.Str(st, "last_report");
            if (!string.IsNullOrEmpty(report))
            {
                var open = Ui.Link("打开", () => _shell.OpenReport(report, Json.Str(ch, "name")), true);
                open.HorizontalAlignment = HorizontalAlignment.Right;
                Grid.SetColumn(open, 3);
                row.Children.Add(open);
            }
            var border = new Border
            {
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(0, 0, 0, 1),
                Child = row,
                Background = Brushes.Transparent
            };
            border.MouseLeftButtonUp += (s, e) => _shell.Navigate("channels");
            return border;
        }

        // ---------------------------------------------------------------- 底部两栏
        private FrameworkElement BuildBottom(AppData data)
        {
            var reports = new StackPanel();
            int shown = 0;
            for (int i = 1; i < data.Reports.Count && shown < 4; i++, shown++)
                reports.Children.Add(ReportRow(data.Reports[i]));
            if (shown == 0)
                reports.Children.Add(Ui.Empty("还没有更早的报告", "检测到新版本后，这里会按时间列出历史报告。"));

            var left = Ui.Section("更早的报告", null, Ui.Card(reports, 0));

            // 四个入口在拉高后的卡片里等分高度，均匀铺开，而不是挤在顶部
            var quick = new Grid();
            for (int i = 0; i < 4; i++)
                quick.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            var quickRows = new[]
            {
                QuickRow("\uE7C3", "打开报告", "按时间翻看所有中文解读", () => _shell.Navigate("reports")),
                QuickRow("\uE895", "检查更新", "马上问一次官方有没有新版", CheckNow),
                QuickRow("\uE790", "个性化外观", "背景图、毛玻璃和强调色", () => _shell.Navigate("personalize")),
                QuickRow("\uE756", "查看日志", "检测过程和体检结果都在这里", () => _shell.Navigate("logs"))
            };
            for (int i = 0; i < quickRows.Length; i++)
            {
                Grid.SetRow(quickRows[i], i);
                quick.Children.Add(quickRows[i]);
            }
            // 右栏做成「标题 + 自动拉高的卡片」：卡片底部会跟着左栏卡片一起到底，
            // 两张卡的圆角就能在同一条线上，而不是右边短一截。
            var right = new Grid { Margin = new Thickness(0, 0, 0, D.SectionGap) };
            right.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            right.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            var quickHead = Ui.T("快捷入口", "SectionTitle");
            quickHead.Margin = new Thickness(0, 0, 0, D.S3);
            right.Children.Add(quickHead);
            var quickCard = Ui.Card(quick, D.S2);
            quickCard.VerticalAlignment = VerticalAlignment.Stretch;
            Grid.SetRow(quickCard, 1);
            right.Children.Add(quickCard);

            var grid = Ui.TwoColumn(left, right);
            return grid;
        }

        private static FrameworkElement QuickRow(string glyph, string title, string help, Action click)
        {
            var btn = new Button
            {
                Style = (Style)Application.Current.Resources["BtnGhost"],
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                VerticalContentAlignment = VerticalAlignment.Center,
                Padding = new Thickness(D.S3, D.S3, D.S3, D.S3),
                Cursor = System.Windows.Input.Cursors.Hand
            };
            var grid = new Grid { VerticalAlignment = VerticalAlignment.Center };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(30) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var icon = Ui.Glyph(glyph, 15, (Brush)Application.Current.Resources["AccentBrush"]);
            icon.VerticalAlignment = VerticalAlignment.Center;
            icon.Margin = new Thickness(0, 0, 0, 0);
            grid.Children.Add(icon);
            var text = new StackPanel { VerticalAlignment = VerticalAlignment.Center };
            text.Children.Add(Ui.T(title, "RowLabel"));
            text.Children.Add(Ui.T(help, "FieldHint"));
            Grid.SetColumn(text, 1);
            grid.Children.Add(text);
            var chev = Ui.Glyph("\uE76C", 11, (Brush)Application.Current.Resources["Ink3Brush"]);
            Grid.SetColumn(chev, 2);
            chev.VerticalAlignment = VerticalAlignment.Center;
            grid.Children.Add(chev);
            btn.Content = grid;
            btn.Click += (s, e) => click();
            return btn;
        }

        private FrameworkElement ReportRow(Dictionary<string, object> r)
        {
            var row = new Grid { Margin = new Thickness(D.S5, D.S3, D.S5, D.S3) };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(56) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            string date = Json.Str(r, "date");
            if (string.IsNullOrEmpty(date)) date = Json.Str(r, "mtime");
            var when = Ui.T(Fmt.Mmdd(date), "MonoText");
            when.VerticalAlignment = VerticalAlignment.Top;
            row.Children.Add(when);
            var mid = new StackPanel();
            var title = new StackPanel { Orientation = Orientation.Horizontal };
            title.Children.Add(Ui.T(Fmt.CompactName(Json.Str(r, "channel_name")), null, 13));
            string build = Json.Str(r, "build");
            if (!string.IsNullOrEmpty(build))
            {
                var b = Ui.T(" " + build, "MonoText", 12);
                b.VerticalAlignment = VerticalAlignment.Center;
                title.Children.Add(b);
            }
            mid.Children.Add(title);
            var sum = Ui.T(Json.Str(r, "summary"), "FieldHint");
            sum.TextTrimming = TextTrimming.CharacterEllipsis;
            sum.Margin = new Thickness(0, 3, 0, 0);
            mid.Children.Add(sum);
            Grid.SetColumn(mid, 1);
            row.Children.Add(mid);
            var chevron = Ui.Glyph("\uE76C", 11, (Brush)Application.Current.Resources["Ink3Brush"]);
            chevron.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(chevron, 2);
            row.Children.Add(chevron);
            var border = new Border
            {
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(0, 0, 0, 1),
                Child = row,
                Background = Brushes.Transparent,
                Cursor = System.Windows.Input.Cursors.Hand
            };
            border.MouseLeftButtonUp += (s, e) =>
                _shell.OpenReport(Json.Str(r, "file"), Json.Str(r, "channel_name"));
            return border;
        }
    }
}
