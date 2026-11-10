using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace WinUpd
{
    /// <summary>
    /// 更新线：左边是清单，右边是"检查器"。
    /// 右边只有一张卡片，所有信息用细分隔线分节——不再是六七个漂浮的小卡片。
    /// </summary>
    public sealed class ChannelsPage : IPage
    {
        private readonly MainWindow _shell;
        private readonly Grid _root = new Grid();
        private readonly StackPanel _list = new StackPanel();
        private readonly StackPanel _detail = new StackPanel();
        private ScrollViewer _detailScroll;
        private readonly TextBlock _count;
        private readonly ColumnDefinition _leftCol;
        private readonly ColumnDefinition _midCol;
        private readonly ColumnDefinition _rightCol;
        private string _sel = "";
        private bool _onlyEnabled;
        private string _query = "";
        private bool _updatingSwitch;
        private Border _statusTag;
        private ToggleButton _enableToggle;
        private readonly Dictionary<string, Ellipse> _rowDots =
            new Dictionary<string, Ellipse>();

        public string Key { get { return "channels"; } }
        public string Title { get { return "更新线"; } }
        public FrameworkElement Root { get { return _root; } }

        public ChannelsPage(MainWindow shell)
        {
            _shell = shell;
            _root.Margin = new Thickness(D.PagePadL, D.PagePadT, D.PagePadR, D.PagePadB);
            _root.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            _root.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });

            // ---- 页头 ----
            var refresh = Ui.B("刷新可选线", "BtnGhost", Discover);
            var header = Ui.PageHeader("监控", "更新线",
                "一条线就是一个 Windows 版本分支。启用后会按间隔检查，发现新版本就写报告。",
                refresh);
            _root.Children.Add(header);

            // ---- 主体：清单 : 检查器 = 1 : 1.618 ----
            var body = new Grid();
            _leftCol = new ColumnDefinition { Width = new GridLength(D.LeftRatio, GridUnitType.Star) };
            _midCol = new ColumnDefinition { Width = new GridLength(D.S5) };
            _rightCol = new ColumnDefinition { Width = new GridLength(D.RightRatio, GridUnitType.Star) };
            body.ColumnDefinitions.Add(_leftCol);
            body.ColumnDefinitions.Add(_midCol);
            body.ColumnDefinitions.Add(_rightCol);
            Grid.SetRow(body, 1);
            _root.Children.Add(body);

            // 左：清单卡片
            var leftCard = new Grid();
            leftCard.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            leftCard.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            leftCard.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            leftCard.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var search = Ui.SearchBox("搜索名称、分类或标签",
                v => { _query = v; RebuildList(); }, double.NaN);
            search.Margin = new Thickness(0, 0, 0, D.S3);
            leftCard.Children.Add(search);

            var filter = new Grid { Margin = new Thickness(D.S1, 0, D.S1, D.S3) };
            filter.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            filter.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            _count = Ui.T("", "FieldHint");
            _count.VerticalAlignment = VerticalAlignment.Center;
            filter.Children.Add(_count);
            var only = new CheckBox
            {
                Content = "仅看已启用",
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(D.S3, 0, 0, 0)
            };
            only.Checked += (s, e) => { _onlyEnabled = true; RebuildList(); };
            only.Unchecked += (s, e) => { _onlyEnabled = false; RebuildList(); };
            Grid.SetColumn(only, 1);
            filter.Children.Add(only);
            Grid.SetRow(filter, 1);
            leftCard.Children.Add(filter);

            var listScroll = new ScrollViewer
            {
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                Content = _list
            };
            Grid.SetRow(listScroll, 2);
            leftCard.Children.Add(listScroll);

            var addPanel = new StackPanel { Margin = new Thickness(0, D.S3, 0, 0) };
            addPanel.Children.Add(Ui.Rule(0, D.S3));
            var addRow = new Grid();
            addRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            addRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var addInput = Ui.Input("", null);
            addInput.FontSize = 12.5;
            addInput.KeyDown += (s, e) =>
            {
                if (e.Key == System.Windows.Input.Key.Enter)
                {
                    AddChannel(addInput);
                    e.Handled = true;
                }
            };
            addRow.Children.Add(addInput);
            var addBtn = Ui.B("添加", "BtnPrimary", () => AddChannel(addInput));
            addBtn.Margin = new Thickness(D.S2, 0, 0, 0);
            addBtn.Padding = new Thickness(14, 6, 14, 6);
            Grid.SetColumn(addBtn, 1);
            addRow.Children.Add(addBtn);
            addPanel.Children.Add(addRow);
            var hint = Ui.T("输入分类名（例如 w11-26h2-experimental），或直接粘贴 uupdump 网址", "FieldHint");
            hint.Margin = new Thickness(1, D.S2, 0, 0);
            addPanel.Children.Add(hint);
            Grid.SetRow(addPanel, 3);
            leftCard.Children.Add(addPanel);

            var leftWrapper = Ui.Card(leftCard, D.CardPadTight);
            body.Children.Add(leftWrapper);

            // 右：检查器。卡片本身固定高度（和左边卡片底部对齐），内容在卡片内部滚动，
            // 这样卡片下面的圆角始终可见，不会跟着内容一起被滚出视口。
            _detail.Margin = new Thickness(0);
            var rightScroll = new ScrollViewer
            {
                Style = (Style)Application.Current.Resources["SlimScroll"],
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                Padding = new Thickness(D.CardPad, D.CardPad, D.CardPad + 10, D.CardPad),
                Content = _detail
            };
            _detailScroll = rightScroll;
            ScrollViewer.SetPanningMode(rightScroll, PanningMode.VerticalOnly);
            var rightCard = Ui.Card(rightScroll, 0);
            Grid.SetColumn(rightCard, 2);
            body.Children.Add(rightCard);

            _shell.SizeChanged += (s, e) => ApplyResponsive();
            _root.Loaded += (s, e) => ApplyResponsive();
        }

        public void LoadData(AppData data)
        {
            var chans = data.Channels;
            if (string.IsNullOrEmpty(_sel) && chans.Count > 0)
            {
                foreach (var c in chans)
                {
                    if (Json.Bool(c, "enabled", false)) { _sel = Json.Str(c, "id"); break; }
                }
                if (string.IsNullOrEmpty(_sel)) _sel = Json.Str(chans[0], "id");
            }
            if (data.FindChannel(_sel) == null && chans.Count > 0)
                _sel = Json.Str(chans[0], "id");
            RebuildList();
            RebuildDetail(data);
        }

        public void ApplyPoll(PollUpdate poll) { }

        /// <summary>窄窗口时把左栏收窄一点，保证右边检查器仍然可读。</summary>
        private void ApplyResponsive()
        {
            if (_rightCol == null) return;
            bool narrow = _shell.ActualWidth < 1100;
            double gap = narrow ? D.S4 : D.S5;
            _midCol.Width = new GridLength(gap);
            _leftCol.Width = new GridLength(1, GridUnitType.Star);
            _rightCol.Width = new GridLength(narrow ? 1.35 : D.RightRatio, GridUnitType.Star);
        }

        // ---------------------------------------------------------------- 清单
        private void RebuildList()
        {
            _list.Children.Clear();
            _rowDots.Clear();
            var data = _shell.Data;
            string q = (_query ?? "").Trim().ToLowerInvariant();
            var shown = new List<Dictionary<string, object>>();
            foreach (var c in data.Channels)
            {
                if (_onlyEnabled && !Json.Bool(c, "enabled", false)) continue;
                if (q.Length > 0)
                {
                    string hay = (Json.Str(c, "name") + " " + Json.Str(c, "folder") + " "
                        + Json.Str(c, "category") + " " + Json.Str(c, "url") + " "
                        + Json.Str(c, "id")).ToLowerInvariant();
                    if (hay.IndexOf(q, StringComparison.Ordinal) < 0) continue;
                }
                shown.Add(c);
            }
            if (_count != null) _count.Text = shown.Count + " 条";
            if (shown.Count == 0)
            {
                _list.Children.Add(Ui.Empty("没有匹配的更新线", "换个词试试，或者清空搜索"));
                return;
            }
            AddGroup("Flight Hub", shown, "flighthub");
            AddGroup("uupdump", shown, "uupdump");
        }

        private void AddGroup(string label, List<Dictionary<string, object>> rows, string source)
        {
            var items = new List<Dictionary<string, object>>();
            foreach (var c in rows)
                if (Json.Str(c, "source", "flighthub") == source) items.Add(c);
            if (items.Count == 0) return;
            var head = Ui.T(label + " · " + items.Count, "FieldHint");
            head.FontWeight = FontWeights.SemiBold;
            head.Margin = new Thickness(D.S2, D.S3, 0, D.S2);
            _list.Children.Add(head);
            foreach (var c in items) _list.Children.Add(RowFor(c));
        }

        private FrameworkElement RowFor(Dictionary<string, object> c)
        {
            string id = Json.Str(c, "id");
            bool on = Json.Bool(c, "enabled", false);
            bool selected = id == _sel;
            var btn = new Button
            {
                Style = (Style)Application.Current.Resources["BtnGhost"],
                HorizontalContentAlignment = HorizontalAlignment.Stretch,
                Padding = new Thickness(D.S3, D.S2, D.S3, D.S2),
                Margin = new Thickness(0, 1, 0, 1)
            };
            if (selected)
            {
                btn.Background = (Brush)Application.Current.Resources["AccentSoftBrush"];
                btn.FontWeight = FontWeights.SemiBold;
            }
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var dot = new Ellipse
            {
                Width = 7,
                Height = 7,
                Fill = (Brush)Application.Current.Resources[on ? "OkBrush" : "LineStrongBrush"],
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(1, 0, 9, 0)
            };
            grid.Children.Add(dot);
            _rowDots[id] = dot;
            var name = Ui.T(Json.Str(c, "name"), null, 13);
            name.TextTrimming = TextTrimming.CharacterEllipsis;
            name.ToolTip = Json.Str(c, "name");
            if (selected) name.Foreground = (Brush)Application.Current.Resources["InkBrush"];
            Grid.SetColumn(name, 1);
            grid.Children.Add(name);
            var side = new StackPanel { Orientation = Orientation.Horizontal };
            if (Json.Bool(c, "preset", false))
            {
                var tag = new Border
                {
                    Style = (Style)Application.Current.Resources["TagQuiet"],
                    Margin = new Thickness(D.S1, 0, 0, 0)
                };
                tag.Child = Ui.T("可选", null, 10.5, null,
                    (Brush)Application.Current.Resources["Ink3Brush"]);
                side.Children.Add(tag);
            }
            if (Json.Str(c, "arch") == "arm64")
            {
                var tag = new Border
                {
                    Style = (Style)Application.Current.Resources["TagQuiet"],
                    Margin = new Thickness(D.S1, 0, 0, 0)
                };
                tag.Child = Ui.T("arm64", null, 10.5, null,
                    (Brush)Application.Current.Resources["Ink3Brush"]);
                side.Children.Add(tag);
            }
            Grid.SetColumn(side, 2);
            grid.Children.Add(side);
            btn.Content = grid;
            btn.Click += (s, e) =>
            {
                if (_sel == id) return;
                _sel = id;
                RebuildList();
                RebuildDetail(_shell.Data);
            };
            return btn;
        }

        // ---------------------------------------------------------------- 检查器
        /// <summary>开关的本地即时反馈：状态标签 + 清单小圆点，不触发任何重排。</summary>
        private void SetLocalEnabled(string id, bool on)
        {
            foreach (var c in _shell.Data.Channels)
            {
                if (Json.Str(c, "id") != id) continue;
                c["enabled"] = on;
                break;
            }
            if (_statusTag != null)
            {
                _statusTag.Style = (Style)Application.Current.Resources[on ? "TagOk" : "TagQuiet"];
                var tb = _statusTag.Child as TextBlock;
                if (tb != null)
                {
                    tb.Text = on ? "已启用" : "未启用";
                    tb.Foreground = (Brush)Application.Current.Resources[on ? "OkBrush" : "Ink2Brush"];
                }
            }
            Ellipse dot;
            if (_rowDots.TryGetValue(id, out dot) && dot != null)
                dot.Fill = (Brush)Application.Current.Resources[on ? "OkBrush" : "LineStrongBrush"];
        }

        private void RebuildDetail(AppData data)
        {
            if (_detailScroll != null) _detailScroll.ScrollToTop();
            _detail.Children.Clear();
            var ch = data.FindChannel(_sel);
            if (ch == null)
            {
                _detail.Children.Add(Ui.Empty("选一条更新线",
                    "左边点一条，这里显示它的版本、检测记录和设置。"));
                _shell.RefreshFrostTargets();
                return;
            }
            string id = Json.Str(ch, "id");
            var st = data.ChannelState(id) ?? new Dictionary<string, object>();
            bool enabled = Json.Bool(ch, "enabled", false);
            var content = new StackPanel();

            // 标题 + 启用开关
            var head = new Grid();
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var titleBox = new StackPanel();
            var title = Ui.T(Json.Str(ch, "name"), null, D.H2, FontWeights.SemiBold);
            title.FontFamily = (FontFamily)Application.Current.Resources["UiDisplayFont"];
            title.TextWrapping = TextWrapping.Wrap;
            titleBox.Children.Add(title);
            var tags = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, D.S2, 0, 0) };
            tags.Children.Add(Ui.Tag(Json.Str(ch, "source") == "flighthub" ? "Flight Hub" : "uupdump", "quiet"));
            if (Json.Str(ch, "arch") == "arm64") tags.Children.Add(Ui.Tag("ARM64", "quiet"));
            _statusTag = Ui.Tag(enabled ? "已启用" : "未启用", enabled ? "ok" : "quiet");
            tags.Children.Add(_statusTag);
            titleBox.Children.Add(tags);
            head.Children.Add(titleBox);

            var switchBox = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Top, Margin = new Thickness(D.S5, 2, 0, 0) };
            switchBox.Children.Add(Ui.T("启用", null, 12.5, null, (Brush)Application.Current.Resources["Ink2Brush"]));
            var toggle = Ui.SwitchRaw(enabled, v =>
            {
                if (_updatingSwitch) return;
                // 先本地生效（开关立刻跟手），再把结果静默同步给后台，不再整页重建
                SetLocalEnabled(id, v);
                _shell.SendAction("set_channel_enabled", new Dictionary<string, object>
                {
                    { "id", id }, { "enabled", v }
                }, null, null, 20000, r =>
                {
                    if (r != null && r.ContainsKey("channels"))
                    {
                        var list = Json.DictList(r, "channels");
                        if (list.Count > 0) _shell.UpdateChannelsQuiet(list);
                    }
                    else
                    {
                        SetLocalEnabled(id, !v);
                        _updatingSwitch = true;
                        if (_enableToggle != null) _enableToggle.IsChecked = !v;
                        _updatingSwitch = false;
                        _shell.ToastErr("这个开关没保存成功，再点一次试试");
                    }
                }, false, () =>
                {
                    // 请求根本没送到（后台断了）：回滚，别让开关显示错状态
                    SetLocalEnabled(id, !v);
                    _updatingSwitch = true;
                    if (_enableToggle != null) _enableToggle.IsChecked = !v;
                    _updatingSwitch = false;
                });
            });
            _enableToggle = toggle;
            toggle.VerticalAlignment = VerticalAlignment.Center;
            toggle.Margin = new Thickness(D.S3, 0, 0, 0);
            switchBox.Children.Add(toggle);
            Grid.SetColumn(switchBox, 1);
            head.Children.Add(switchBox);
            content.Children.Add(head);

            if (Json.Bool(ch, "preset", false))
            {
                var note = Ui.T("这是刚发现的可选线，打开右上角开关才会开始检查。", "FieldHint");
                note.Margin = new Thickness(0, D.S3, 0, 0);
                content.Children.Add(note);
            }

            // 检测状态
            content.Children.Add(SectionDivider());
            content.Children.Add(Caption("检测状态"));
            var kv = new Grid { Margin = new Thickness(0, D.S3, 0, 0) };
            kv.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            kv.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            kv.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            kv.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            AddKv(kv, 0, 0, "当前版本", Json.Str(st, "last_version", "还没检测过"));
            AddKv(kv, 1, 0, "上次检测", Fmt.Mmdd(Json.Str(st, "last_check_date")));
            AddKv(kv, 0, 1, "报告数量", Json.DictList(st, "reports").Count + " 份");
            AddKv(kv, 1, 1, "忽略版本", Json.StrList(st, "ignored").Count + " 个");
            content.Children.Add(kv);
            string lastErr = Json.Str(st, "last_error");
            if (!string.IsNullOrEmpty(lastErr))
            {
                var errBox = new Border
                {
                    Background = (Brush)Application.Current.Resources["BadSoftBrush"],
                    CornerRadius = new CornerRadius(8),
                    Padding = new Thickness(D.S3, D.S2, D.S3, D.S2),
                    Margin = new Thickness(0, D.S3, 0, 0)
                };
                var es = new StackPanel();
                var et = Ui.T(lastErr, null, 12, null, (Brush)Application.Current.Resources["BadBrush"]);
                et.TextWrapping = TextWrapping.Wrap;
                es.Children.Add(et);
                int fails = Json.Int(st, "fail_count", 0);
                if (fails > 0)
                    es.Children.Add(Ui.T("已经连续没查成 " + fails + " 次", "FieldHint"));
                errBox.Child = es;
                content.Children.Add(errBox);
            }

            // 版本架构
            content.Children.Add(SectionDivider());
            content.Children.Add(Caption("版本架构"));
            var archHint = Ui.T("选错会查不到更新。一般电脑选 amd64。", "FieldHint");
            archHint.Margin = new Thickness(0, 3, 0, D.S3);
            content.Children.Add(archHint);
            content.Children.Add(Ui.Segmented(new[] { "amd64", "arm64" },
                Json.Str(ch, "arch", "amd64"), v =>
                    _shell.SendAction("set_channel_arch", new Dictionary<string, object>
                    {
                        { "id", id }, { "arch", v }
                    }, null, null, 20000, r =>
                    {
                        if (r != null && r.ContainsKey("channels"))
                            _shell.UpdateChannelsQuiet(Json.DictList(r, "channels"));
                    }, false)));

            // 已忽略
            var ignored = Json.StrList(st, "ignored");
            if (ignored.Count > 0)
            {
                content.Children.Add(SectionDivider());
                var igHead = new Grid();
                igHead.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                igHead.Children.Add(Caption("已忽略的版本"));
                var clear = Ui.Link("全部恢复", () =>
                    _shell.SendAction("clear_ignored", new Dictionary<string, object>
                    {
                        { "id", id }
                    }, null, null, 20000, r =>
                    {
                        if (r != null && r.ContainsKey("channels"))
                            _shell.UpdateChannelsQuiet(Json.DictList(r, "channels"));
                    }, false), true);
                clear.HorizontalAlignment = HorizontalAlignment.Right;
                Grid.SetColumn(clear, 1);
                igHead.Children.Add(clear);
                content.Children.Add(igHead);
                var chips = new WrapPanel { Margin = new Thickness(0, D.S2, 0, 0) };
                foreach (string v in ignored)
                {
                    var chip = new Border { Style = (Style)Application.Current.Resources["ChipBorder"] };
                    chip.Child = Ui.T(v, "MonoText");
                    chips.Children.Add(chip);
                }
                content.Children.Add(chips);
                var igHint = Ui.T("这些版本不会再提醒你，报告也还在。", "FieldHint");
                igHint.Margin = new Thickness(0, D.S2, 0, 0);
                content.Children.Add(igHint);
            }

            // uupdump
            if (Json.Str(ch, "source") == "uupdump")
            {
                content.Children.Add(SectionDivider());
                var urlHead = new Grid();
                urlHead.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                urlHead.Children.Add(Caption("uupdump 分类"));
                string url = Json.Str(ch, "url");
                if (!string.IsNullOrEmpty(url))
                {
                    var open = Ui.Link("在浏览器打开", () => _shell.OpenExternal("browser", url), true);
                    open.HorizontalAlignment = HorizontalAlignment.Right;
                    Grid.SetColumn(open, 1);
                    urlHead.Children.Add(open);
                }
                content.Children.Add(urlHead);
                string cat = Json.Str(ch, "category");
                if (!string.IsNullOrEmpty(cat))
                {
                    var c = Ui.T(cat, "MonoText");
                    c.Margin = new Thickness(0, D.S2, 0, 2);
                    content.Children.Add(c);
                }
                if (!string.IsNullOrEmpty(url))
                {
                    var u = Ui.T(url, "FieldHint");
                    u.TextTrimming = TextTrimming.CharacterEllipsis;
                    content.Children.Add(u);
                }
            }

            // 这条线的报告
            var reports = Json.DictList(st, "reports");
            content.Children.Add(SectionDivider());
            content.Children.Add(Caption("这条线的报告"));
            if (reports.Count == 0)
            {
                var h = Ui.T("还没有报告。第一次检测到新版本后，会写一份中文解读放在这里。", "FieldHint");
                h.Margin = new Thickness(0, D.S2, 0, 0);
                content.Children.Add(h);
            }
            else
            {
                var rows = new StackPanel { Margin = new Thickness(0, D.S1, 0, 0) };
                int count = 0;
                foreach (var rep in reports)
                {
                    if (count++ >= 6) break;
                    rows.Children.Add(ReportRow(rep, Json.Str(ch, "name")));
                }
                content.Children.Add(rows);
            }

            // 操作
            content.Children.Add(SectionDivider());
            var actions = new WrapPanel();
            var check = Ui.B("只检测这条线", "BtnPrimary", () =>
                _shell.SendAction("check_channel", new Dictionary<string, object>
                {
                    { "id", id }
                }, null, "正在检测这条线…", 90000));
            check.Margin = new Thickness(0, 0, D.S2, D.S2);
            actions.Children.Add(check);
            string lastReport = Json.Str(st, "last_report");
            if (!string.IsNullOrEmpty(lastReport))
            {
                var open = Ui.B("打开最近报告", "BtnSecondary", () =>
                    _shell.OpenReport(lastReport, Json.Str(ch, "name")));
                open.Margin = new Thickness(0, 0, D.S2, D.S2);
                actions.Children.Add(open);
            }
            var folder = Ui.B("报告文件夹", "BtnGhost", () => _shell.OpenExternal("report_folder"));
            folder.Margin = new Thickness(0, 0, D.S2, D.S2);
            actions.Children.Add(folder);
            content.Children.Add(actions);
            var tail = Ui.T("检测过程显示在「日志与诊断」页，完成后这里会自动更新。", "FieldHint");
            tail.Margin = new Thickness(0, D.S2, 0, 0);
            content.Children.Add(tail);

            _detail.Children.Add(content);
            _shell.RefreshFrostTargets();
            _shell.FollowFrost(320);
        }

        private static FrameworkElement SectionDivider()
        {
            return Ui.Rule(D.S5, D.S5);
        }

        private static TextBlock Caption(string text)
        {
            return Ui.T(text, "SectionTitle");
        }

        private static void AddKv(Grid grid, int col, int row, string label, string value)
        {
            var sp = new StackPanel { Margin = new Thickness(0, 0, 0, D.S3) };
            sp.Children.Add(Ui.T(label, "MetricLabel"));
            var v = Ui.T(string.IsNullOrEmpty(value) ? "—" : value, null, 13.5,
                string.IsNullOrEmpty(value) ? FontWeights.Normal : FontWeights.SemiBold);
            v.Margin = new Thickness(0, 3, 0, 0);
            sp.Children.Add(v);
            Grid.SetColumn(sp, col);
            Grid.SetRow(sp, row);
            grid.Children.Add(sp);
        }

        private FrameworkElement ReportRow(Dictionary<string, object> rep, string channelName)
        {
            var row = new Grid
            {
                Margin = new Thickness(D.S1, D.S2, D.S1, D.S2),
                Cursor = Cursors.Hand,
                Background = Brushes.Transparent
            };
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(56) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.Children.Add(Ui.T(Fmt.Mmdd(Json.Str(rep, "date")), "MonoText"));
            var mid = Ui.T(Json.Str(rep, "build"), "MonoText");
            Grid.SetColumn(mid, 1);
            row.Children.Add(mid);
            var chev = Ui.Glyph("\uE76C", 11, (Brush)Application.Current.Resources["Ink3Brush"]);
            Grid.SetColumn(chev, 2);
            row.Children.Add(chev);
            string file = Json.Str(rep, "file");
            row.MouseLeftButtonUp += (s, e) => _shell.OpenReport(file, channelName);
            var border = new Border
            {
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(0, 0, 0, 1),
                Child = row
            };
            return border;
        }

        // ---------------------------------------------------------------- 动作
        private void AddChannel(TextBox input)
        {
            string text = (input.Text ?? "").Trim();
            if (text.Length == 0) { input.Focus(); return; }
            _shell.SendAction("add_channel", new Dictionary<string, object>
            {
                { "text", text }
            }, null, "正在解析这条更新线…", 60000, r =>
            {
                // SendAction 在 result.ok=false 时也会走到这里：那时不能清空输入框，
                // 否则用户刚粘进来的网址/分类名就被吃掉了，还得重新找一遍。
                if (r == null || !Json.Bool(r, "ok", true))
                {
                    if (input.IsVisible)
                    {
                        try { input.Focus(); input.SelectAll(); } catch { }
                    }
                    return;
                }
                if (r.ContainsKey("channels"))
                {
                    var list = Json.DictList(r, "channels");
                    if (list.Count > 0) _shell.ApplyChannels(list);
                }
                string msg = Json.Str(r, "message");
                if (!string.IsNullOrEmpty(msg)) _shell.ToastInfo(msg);
                input.Text = "";
            });
        }

        private void Discover()
        {
            _shell.SendAction("discover", new Dictionary<string, object>(), null,
                "正在从微软看板抓更新线…", 180000, r =>
                {
                    if (r != null && r.ContainsKey("channels"))
                    {
                        var list = Json.DictList(r, "channels");
                        if (list.Count > 0) _shell.ApplyChannels(list);
                    }
                });
        }
    }
}
