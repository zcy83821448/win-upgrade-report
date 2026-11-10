using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace WinUpd
{
    /// <summary>
    /// 日志与诊断：实时输出 → 程序日志 → 体检结果，按"先看现象、再看细节"的顺序排。
    /// </summary>
    public sealed class LogsPage : IPage
    {
        private readonly MainWindow _shell;
        private readonly StackPanel _root = new StackPanel();
        private readonly ScrollViewer _scroller;
        private TextBox _liveBox;
        private Border _liveCard;
        private FrameworkElement _liveSection;
        private TextBlock _liveTitle;
        private TextBox _logBox;
        private StackPanel _checkHost;
        private TextBlock _logPath;
        private int _pollTick;
        private bool _logLoading;

        public string Key { get { return "logs"; } }
        public string Title { get { return "日志与诊断"; } }
        public FrameworkElement Root { get { return _scroller; } }

        public LogsPage(MainWindow shell)
        {
            _shell = shell;
            _scroller = Ui.Scroller(_root);
            shell.SelfcheckSink = (summary, items) =>
            {
                if (_checkHost != null) RenderCheck(summary, items);
            };
        }

        public void LoadData(AppData data)
        {
            _root.Children.Clear();
            var runCheck = Ui.B("体检并修复", "BtnPrimary", () =>
                _shell.SendAction("run_selfcheck", new Dictionary<string, object>(), null,
                    "正在体检…", 60000, r => _shell.RefreshSoon()));
            var openLog = Ui.B("打开日志文件", "BtnSecondary", () => _shell.OpenExternal("log"));
            _root.Children.Add(Ui.PageHeader("运行与记录", "日志与诊断",
                "检测过程、出错原因和体检结果都在这里；出问题时先跑一次体检。", runCheck, openLog));

            _liveCard = BuildLiveCard();
            _liveCard.Visibility = Visibility.Collapsed;
            _liveSection = Ui.Section("本次检测输出", "实时", _liveCard);
            _liveSection.Visibility = Visibility.Collapsed;
            _root.Children.Add(_liveSection);
            _root.Children.Add(Ui.Section("程序日志", "自动刷新", BuildLogCard(data)));
            _root.Children.Add(Ui.Section("体检结果", null, BuildCheckCard(), 0));

            LoadLog();
            if (_shell.SelfcheckItems != null)
                RenderCheck(_shell.SelfcheckSummary, _shell.SelfcheckItems);
        }

        public void ApplyPoll(PollUpdate poll)
        {
            // 界面写着「自动刷新」，就得真的自动刷新：poll 大约每秒一次，
            // 每 4 秒重新读一次日志文件（没有变化时不会动 TextBox，不会闪）。
            _pollTick++;
            if (_pollTick % 4 == 0) LoadLog();

            var live = poll.Live;
            if (live == null) return;
            bool active = Json.Bool(live, "active", false);
            var lines = Json.StrList(live, "lines");
            if (active || lines.Count > 0)
            {
                bool wasVisible = _liveSection != null
                    && _liveSection.Visibility == Visibility.Visible;
                if (_liveSection != null) _liveSection.Visibility = Visibility.Visible;
                if (_liveCard != null) _liveCard.Visibility = Visibility.Visible;
                if (!wasVisible) _shell.FollowFrost(300);
                if (_liveTitle != null)
                {
                    string txt = active ? "正在检测…" : "上次检测输出";
                    if (_liveTitle.Text != txt) _liveTitle.Text = txt;
                }
                if (_liveBox != null)
                {
                    _liveBox.Text = string.Join("\r\n", lines.ToArray());
                    _liveBox.ScrollToEnd();
                }
            }
        }

        private Border BuildLiveCard()
        {
            var card = new StackPanel();
            var head = new Grid { Margin = new Thickness(0, 0, 0, D.S2) };
            _liveTitle = Ui.T("正在检测…", null, 12.5, FontWeights.SemiBold);
            head.Children.Add(_liveTitle);
            card.Children.Add(head);
            _liveBox = LogBox(150);
            card.Children.Add(_liveBox);
            return Ui.Card(card, D.CardPadTight);
        }

        private static TextBox LogBox(double height)
        {
            return new TextBox
            {
                IsReadOnly = true,
                Height = height,
                FontFamily = (FontFamily)Application.Current.Resources["MonoFont"],
                FontSize = 11.5,
                TextWrapping = TextWrapping.NoWrap,
                AcceptsReturn = true,
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
                Background = (Brush)Application.Current.Resources["Surface2Brush"],
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(1),
                Padding = new Thickness(D.S3, D.S2, D.S3, D.S2),
                Foreground = (Brush)Application.Current.Resources["Ink2Brush"]
            };
        }

        private Border BuildLogCard(AppData data)
        {
            var card = new StackPanel();
            var head = new Grid { Margin = new Thickness(0, 0, 0, D.S3) };
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var line = new StackPanel { Orientation = Orientation.Horizontal };
            var icon = Ui.Glyph("\uE756", 12, (Brush)Application.Current.Resources["Ink3Brush"]);
            icon.Margin = new Thickness(0, 0, D.S2, 0);
            line.Children.Add(icon);
            _logPath = Ui.T(string.IsNullOrEmpty(data.LogPath) ? "日志文件" : data.LogPath,
                "MonoText", 11.5);
            _logPath.TextTrimming = TextTrimming.CharacterEllipsis;
            _logPath.MaxWidth = 460;
            _logPath.ToolTip = data.LogPath;
            line.Children.Add(_logPath);
            head.Children.Add(line);
            var actions = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };
            actions.Children.Add(Small("刷新", LoadLog));
            actions.Children.Add(Small("打开", () => _shell.OpenExternal("log")));
            var clear = Small("清空", () => { });
            clear.Click += (s, e) =>
            {
                if (!_shell.ConfirmThen(clear, "再点一次清空")) return;
                _shell.SendAction("clear_log", new Dictionary<string, object>(), "日志已清空",
                    null, 20000, r => LoadLog());
            };
            actions.Children.Add(clear);
            Grid.SetColumn(actions, 1);
            head.Children.Add(actions);
            card.Children.Add(head);
            _logBox = LogBox(300);
            card.Children.Add(_logBox);
            var hint = Ui.T("只显示最近的日志；更多内容可以在日志文件里看。", "FieldHint");
            hint.Margin = new Thickness(0, D.S3, 0, 0);
            card.Children.Add(hint);
            return Ui.Card(card);
        }

        private static Button Small(string text, Action click)
        {
            var b = Ui.B(text, "BtnGhost", click, 12, new Thickness(D.S2, 4, D.S2, 4));
            b.Margin = new Thickness(D.S2, 0, 0, 0);
            return b;
        }

        private Border BuildCheckCard()
        {
            var card = new StackPanel();
            var head = new Grid { Margin = new Thickness(0, 0, 0, D.S3) };
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var desc = Ui.T("看看有没有哪里没弄好；能修的会直接修好。", "FieldHint");
            desc.VerticalAlignment = VerticalAlignment.Center;
            head.Children.Add(desc);
            var run = Ui.B("运行体检", "BtnSecondary", () =>
                _shell.SendAction("run_selfcheck", new Dictionary<string, object>(), null,
                    "正在体检…", 60000), 12, new Thickness(D.S3, 4, D.S3, 4));
            run.HorizontalAlignment = HorizontalAlignment.Right;
            Grid.SetColumn(run, 1);
            head.Children.Add(run);
            card.Children.Add(head);
            _checkHost = new StackPanel();
            card.Children.Add(_checkHost);
            return Ui.Card(card);
        }

        private void RenderCheck(string summary, List<Dictionary<string, object>> items)
        {
            if (_checkHost == null) return;
            _checkHost.Children.Clear();
            if (!string.IsNullOrEmpty(summary))
            {
                var s = Ui.T(summary, "RowLabel");
                s.Margin = new Thickness(0, 0, 0, D.S3);
                _checkHost.Children.Add(s);
            }
            if (items == null) return;
            foreach (var it in items)
            {
                string status = Json.Str(it, "status");
                bool ok = status == "ok";
                bool warn = status == "warn" || status == "fixed";
                var row = new Grid { Margin = new Thickness(0, D.S2, 0, D.S2) };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(18) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                var dot = new System.Windows.Shapes.Ellipse
                {
                    Width = 8,
                    Height = 8,
                    VerticalAlignment = VerticalAlignment.Top,
                    Margin = new Thickness(0, 5, 0, 0),
                    Fill = (Brush)Application.Current.Resources[
                        ok ? "OkBrush" : (warn ? "WarnBrush" : "BadBrush")]
                };
                row.Children.Add(dot);
                var sp = new StackPanel();
                sp.Children.Add(Ui.T(Json.Str(it, "name"), null, 12.5, FontWeights.SemiBold));
                string msg = Json.Str(it, "msg");
                if (!string.IsNullOrEmpty(msg))
                {
                    var m = Ui.T(msg, "FieldHint");
                    m.Margin = new Thickness(0, 2, 0, 0);
                    m.TextWrapping = TextWrapping.Wrap;
                    sp.Children.Add(m);
                }
                Grid.SetColumn(sp, 1);
                row.Children.Add(sp);
                _checkHost.Children.Add(row);
            }
        }

        private async void LoadLog()
        {
            if (_logLoading) return;
            _logLoading = true;
            try
            {
                var resp = await _shell.CallService("read_log", new Dictionary<string, object>(), 15000);
                if (!UiClient.IsOk(resp)) return;
                var result = UiClient.Result(resp);
                if (result == null) return;
                string path = Json.Str(result, "path");
                if (!string.IsNullOrEmpty(path) && _logPath != null && _logPath.Text != path)
                {
                    _logPath.Text = path;
                    _logPath.ToolTip = path;
                }
                string text = Json.Str(result, "text");
                if (_logBox != null && _logBox.Text != text) SetLogText(text);
            }
            finally { _logLoading = false; }
        }

        /// <summary>
        /// 只替换真正变化的内容，并保住用户当前的阅读位置：
        /// 自动刷新不能把正在往上翻的日志顶回末尾，只有原本就在底部才继续跟到底。
        /// </summary>
        private void SetLogText(string text)
        {
            if (_logBox == null) return;
            double keep = _logBox.VerticalOffset;
            bool atBottom = keep >= _logBox.ExtentHeight - _logBox.ViewportHeight - 8;
            _logBox.Text = text ?? "";
            if (atBottom) _logBox.ScrollToEnd();
            else _logBox.ScrollToVerticalOffset(keep);
        }
    }
}
