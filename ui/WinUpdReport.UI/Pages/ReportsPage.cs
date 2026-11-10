using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace WinUpd
{
    /// <summary>
    /// 报告：左边是时间线，右边按原生排版预览全文；窗口窄时自动收起预览，点一条直接进阅读模式。
    /// </summary>
    public sealed class ReportsPage : IPage
    {
        private readonly MainWindow _shell;
        private readonly Grid _root = new Grid();
        private readonly StackPanel _list = new StackPanel();
        private readonly FlowDocumentScrollViewer _preview;
        private readonly TextBlock _previewTitle;
        private readonly TextBlock _previewMeta;
        private readonly Dictionary<string, List<Dictionary<string, object>>> _cache
            = new Dictionary<string, List<Dictionary<string, object>>>();
        private string _selFile = "";
        private string _query = "";
        private readonly ColumnDefinition _leftCol;
        private readonly ColumnDefinition _midCol;
        private readonly ColumnDefinition _rightCol;
        private Border _rightCard;
        private TextBlock _listHint;
        private bool _narrow;
        private int _requestToken;

        public string Key { get { return "reports"; } }
        public string Title { get { return "报告"; } }
        public FrameworkElement Root { get { return _root; } }

        public ReportsPage(MainWindow shell)
        {
            _shell = shell;
            _root.Margin = new Thickness(D.PagePadL, D.PagePadT, D.PagePadR, D.PagePadB);
            _root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            _root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

            var folder = Ui.B("打开报告文件夹", "BtnSecondary", () => _shell.OpenExternal("report_folder"));
            var refresh = Ui.IconButton("\uE72C", "刷新", () => _shell.RefreshSoon());
            refresh.Margin = new Thickness(D.S3, 0, 0, 0);
            _root.Children.Add(Ui.PageHeader("运行与记录", "报告",
                "每一份更新都会写一篇中文解读，按时间排好，点开就能看。", folder, refresh));

            var body = new Grid();
            _leftCol = new ColumnDefinition { Width = new GridLength(D.LeftRatio, GridUnitType.Star) };
            _midCol = new ColumnDefinition { Width = new GridLength(D.S5) };
            _rightCol = new ColumnDefinition { Width = new GridLength(D.RightRatio, GridUnitType.Star) };
            body.ColumnDefinitions.Add(_leftCol);
            body.ColumnDefinitions.Add(_midCol);
            body.ColumnDefinitions.Add(_rightCol);
            Grid.SetRow(body, 1);
            _root.Children.Add(body);

            // 左：时间线
            var left = new Grid();
            left.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            left.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            var searchRow = Ui.SearchBox("搜索更新线、版本或摘要", v => { _query = v; RebuildList(); },
                double.NaN);
            searchRow.Margin = new Thickness(0, 0, 0, D.S3);
            left.Children.Add(searchRow);
            var scroll = new ScrollViewer
            {
                Style = (Style)Application.Current.Resources["SlimScroll"],
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                Content = _list
            };
            ScrollViewer.SetPanningMode(scroll, PanningMode.VerticalOnly);
            Grid.SetRow(scroll, 1);
            left.Children.Add(scroll);
            var leftCard = Ui.Card(left, D.CardPadTight);
            body.Children.Add(leftCard);

            // 右：原生预览
            var right = new Grid();
            right.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            right.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            right.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            var header = new Grid { Margin = new Thickness(D.CardPad, D.CardPad, D.CardPad, D.S4) };
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            header.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var titles = new StackPanel { Margin = new Thickness(0, 0, D.S3, 0) };
            _previewTitle = Ui.T("选一份报告", null, D.Subhead, FontWeights.SemiBold);
            _previewTitle.TextTrimming = TextTrimming.CharacterEllipsis;
            titles.Children.Add(_previewTitle);
            _previewMeta = Ui.T("点左边开始阅读；也可以在浏览器里打开。", "FieldHint");
            _previewMeta.Margin = new Thickness(0, 3, 0, 0);
            titles.Children.Add(_previewMeta);
            header.Children.Add(titles);
            var actions = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Top
            };
            var read = Ui.B("阅读模式", "BtnSecondary", () =>
            {
                if (!string.IsNullOrEmpty(_selFile))
                    _shell.OpenReport(_selFile, _previewTitle.Text);
            });
            actions.Children.Add(read);
            var browser = Ui.IconButton("\uE774", "在浏览器打开", () =>
            {
                if (!string.IsNullOrEmpty(_selFile))
                    _shell.OpenExternal("browser", MainWindow.HtmlSiblingOf(_selFile));
            });
            browser.Margin = new Thickness(D.S2, 0, 0, 0);
            actions.Children.Add(browser);
            Grid.SetColumn(actions, 1);
            header.Children.Add(actions);
            right.Children.Add(header);
            var rule = new Border
            {
                Height = 1,
                Background = (Brush)Application.Current.Resources["LineBrush"],
                Margin = new Thickness(D.CardPad, 0, D.CardPad, 0)
            };
            Grid.SetRow(rule, 1);
            right.Children.Add(rule);
            _preview = new FlowDocumentScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                IsToolBarVisible = false,
                Background = Brushes.Transparent,
                Margin = new Thickness(D.CardPad - 8, D.S3, D.CardPad - 12, D.S4)
            };
            Grid.SetRow(_preview, 2);
            right.Children.Add(_preview);
            _rightCard = Ui.Card(right, 0);
            Grid.SetColumn(_rightCard, 2);
            body.Children.Add(_rightCard);

            _shell.SizeChanged += (s, e) => ApplyNarrow();
            ApplyNarrow();
        }

        public void LoadData(AppData data)
        {
            if (string.IsNullOrEmpty(_selFile) && data.Reports.Count > 0)
                _selFile = Json.Str(data.Reports[0], "file");
            RebuildList();
            ApplyNarrow();
            if (!_narrow && !string.IsNullOrEmpty(_selFile) && _preview.Document == null)
                SelectReport(_selFile, FindReport(_selFile));
        }

        private void ApplyNarrow()
        {
            bool narrow = _shell.ActualWidth < 1080;
            if (narrow == _narrow && _rightCard != null) return;
            _narrow = narrow;
            _leftCol.Width = new GridLength(1, GridUnitType.Star);
            _rightCol.Width = narrow ? new GridLength(0)
                                     : new GridLength(D.RightRatio, GridUnitType.Star);
            _midCol.Width = narrow ? new GridLength(0) : new GridLength(D.S5);
            if (_rightCard != null)
                _rightCard.Visibility = narrow ? Visibility.Collapsed : Visibility.Visible;
            if (!narrow && _preview.Document == null && !string.IsNullOrEmpty(_selFile))
                SelectReport(_selFile, FindReport(_selFile));
            if (_listHint != null)
                _listHint.Text = narrow
                    ? "点一条直接在阅读模式里打开" : "点一条在右边预览";
        }

        public void ApplyPoll(PollUpdate poll) { }

        private Dictionary<string, object> FindReport(string file)
        {
            foreach (var r in _shell.Data.Reports)
                if (Json.Str(r, "file") == file) return r;
            return null;
        }

        private void RebuildList()
        {
            _list.Children.Clear();
            var data = _shell.Data;
            string q = (_query ?? "").Trim().ToLowerInvariant();
            int shown = 0;
            foreach (var r in data.Reports)
            {
                string hay = (Json.Str(r, "channel_name") + " " + Json.Str(r, "build") + " "
                    + Json.Str(r, "summary")).ToLowerInvariant();
                if (q.Length > 0 && hay.IndexOf(q, StringComparison.Ordinal) < 0) continue;
                if (shown == 0)
                {
                    _listHint = Ui.T("", "FieldHint");
                    _listHint.Margin = new Thickness(D.S1, 0, 0, D.S2);
                    _list.Children.Add(_listHint);
                    ApplyNarrowHint();
                }
                _list.Children.Add(RowFor(r));
                shown++;
            }
            if (shown == 0)
                _list.Children.Add(Ui.Empty("还没有报告",
                    data.Reports.Count > 0 ? "换个词试试" : "检测到新版本后，这里会出现对应的中文解读"));
        }

        private void ApplyNarrowHint()
        {
            if (_listHint != null)
                _listHint.Text = _narrow ? "点一条直接在阅读模式里打开" : "点一条在右边预览";
        }

        private FrameworkElement RowFor(Dictionary<string, object> r)
        {
            string file = Json.Str(r, "file");
            bool selected = file == _selFile;
            var btn = new Button
            {
                Style = (Style)Application.Current.Resources["BtnGhost"],
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Padding = new Thickness(D.S3, D.S2, D.S3, D.S2),
                Margin = new Thickness(0, 0, 0, 1)
            };
            if (selected)
            {
                btn.Background = (Brush)Application.Current.Resources["AccentSoftBrush"];
                btn.FontWeight = FontWeights.SemiBold;
            }
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var left = new StackPanel();
            var top = new StackPanel { Orientation = Orientation.Horizontal };
            top.Children.Add(Ui.T(Fmt.CompactName(Json.Str(r, "channel_name")), null, 13,
                FontWeights.SemiBold));
            string build = Json.Str(r, "build");
            if (!string.IsNullOrEmpty(build))
            {
                var b = Ui.T(build, "MonoText", 11);
                b.Margin = new Thickness(D.S2, 2, 0, 0);
                top.Children.Add(b);
            }
            left.Children.Add(top);
            var sub = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 3, 0, 0) };
            string date = Json.Str(r, "date");
            if (string.IsNullOrEmpty(date)) date = Json.Str(r, "mtime");
            sub.Children.Add(Ui.T(Fmt.Mmdd(date), "FieldHint"));
            var sum = Ui.T("  " + Fmt.Truncate(Json.Str(r, "summary"), 56), "FieldHint");
            sum.TextTrimming = TextTrimming.CharacterEllipsis;
            sub.Children.Add(sum);
            left.Children.Add(sub);
            grid.Children.Add(left);
            var chev = Ui.Glyph("\uE76C", 10, (Brush)Application.Current.Resources["Ink3Brush"]);
            chev.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(chev, 1);
            grid.Children.Add(chev);
            btn.Content = grid;
            btn.Click += (s, e) =>
            {
                if (_narrow)
                {
                    _selFile = file;
                    RebuildList();
                    _shell.OpenReport(file, Json.Str(r, "channel_name"));
                    return;
                }
                SelectReport(file, r);
            };
            return btn;
        }

        private async void SelectReport(string file, Dictionary<string, object> r)
        {
            _selFile = file;
            RebuildList();
            if (r == null) return;
            _previewTitle.Text = Fmt.CompactName(Json.Str(r, "channel_name"));
            string date = Json.Str(r, "date");
            if (string.IsNullOrEmpty(date)) date = Json.Str(r, "mtime");
            string build = Json.Str(r, "build");
            _previewMeta.Text = (string.IsNullOrEmpty(build) ? "" : build + " · ") + Fmt.Mmdd(date);
            int token = ++_requestToken;
            List<Dictionary<string, object>> blocks;
            string key = CacheKey(file, r);
            if (_cache.TryGetValue(key, out blocks))
            {
                _preview.Document = ReportRenderer.Build(blocks);
                return;
            }
            _preview.Document = ReportRenderer.Message("正在打开报告…");
            var resp = await _shell.CallService("report_doc", new Dictionary<string, object>
            {
                { "file", file }
            }, 25000);
            if (token != _requestToken) return;
            var result = UiClient.Result(resp);
            if (!UiClient.IsOk(resp) || result == null || !Json.Bool(result, "ok", true))
            {
                _preview.Document = ReportRenderer.Error("这份报告打不开："
                    + (result != null ? Json.Str(result, "error", "读不出来") : UiClient.ErrorOf(resp)));
                return;
            }
            blocks = Json.DictList(result, "blocks");
            if (_cache.Count > 12) _cache.Clear();
            _cache[key] = blocks;
            _preview.Document = ReportRenderer.Build(blocks);
            Anim.FadeSlideIn(_preview, Anim.Base, 0, 5);
        }

        /// <summary>
        /// 缓存键带上报告的修改时间：同一个路径的报告被重新生成（覆盖）时，
        /// 只按路径做键会把旧内容一直显示出来。
        /// </summary>
        private static string CacheKey(string file, Dictionary<string, object> r)
        {
            string mtime = r != null ? Json.Str(r, "mtime") : "";
            return (file ?? "") + "|" + mtime;
        }
    }
}
