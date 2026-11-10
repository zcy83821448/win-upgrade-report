using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace WinUpd
{
    /// <summary>
    /// 通知：左边是"什么时候提醒我"，右边是"提醒长什么样"。
    /// 把预览放在设置旁边，用户不用去猜改完之后的后果。
    /// </summary>
    public sealed class NotifyPage : IPage
    {
        private readonly MainWindow _shell;
        private readonly StackPanel _root = new StackPanel();
        private readonly ScrollViewer _scroller;
        private StackPanel _ignoreHost;
        private ToggleButton _mergeToggle;
        private FrameworkElement _holdBox;

        public string Key { get { return "notify"; } }
        public string Title { get { return "通知"; } }
        public FrameworkElement Root { get { return _scroller; } }

        public NotifyPage(MainWindow shell)
        {
            _shell = shell;
            _scroller = Ui.Scroller(_root);
        }

        public void ApplyPoll(PollUpdate poll) { }

        public void LoadData(AppData data)
        {
            _root.Children.Clear();
            var cfg = data.Config;

            var test = Ui.B("发一条测试通知", "BtnSecondary", () =>
                _shell.SendAction("test_toast", new Dictionary<string, object>(), null,
                    "正在发测试通知…", 20000));
            _root.Children.Add(Ui.PageHeader("监控", "通知",
                "什么时候提醒、提醒几次、什么情况下先别打扰你。", test));

            var left = new StackPanel();
            left.Children.Add(Ui.Section("通知", null, NotifyCard(cfg)));
            left.Children.Add(Ui.Section("检查节奏", null, PaceCard(cfg)));
            left.Children.Add(Ui.Section("不打扰", null, QuietCard(cfg)));

            var right = new StackPanel();
            right.Children.Add(Ui.Section("通知预览", null, PreviewCard(cfg)));
            right.Children.Add(Ui.Section("托盘图标", data.TrayStyles.Count + " 款", TrayCard(data)));
            right.Children.Add(Ui.Section("报告详细程度", null, DetailCard(data)));
            right.Children.Add(Ui.Section("暂时静默", null, SilentCard(cfg), 0));

            _root.Children.Add(Ui.TwoColumn(left, right));
        }

        // ---------------------------------------------------------------- 通知
        private FrameworkElement NotifyCard(Dictionary<string, object> cfg)
        {
            bool notifyOn = Json.Bool(cfg, "notify", true);
            var card = new StackPanel();
            ToggleButton notifyToggle;
            card.Children.Add(Ui.SwitchRow("发现新版本时提醒我",
                notifyOn ? "用 Windows 通知提醒，右下角会弹出来" : "关掉后只在界面的「报告」里攒着",
                notifyOn, v =>
                {
                    _shell.QueueSave("notify", v);
                    // 只更新依赖它的开关，不触发整页重建（重建会让卡片闪一下）
                    if (_mergeToggle != null) _mergeToggle.IsEnabled = v;
                }, out notifyToggle));
            card.Children.Add(Ui.Rule(D.S3, D.S3));
            ToggleButton mergeToggle;
            var mergeRow = Ui.SwitchRow("多条线的更新合并成一条通知",
                "一次发现好几个新版本时只发一条，不刷屏",
                Json.Bool(cfg, "merge_notifications", true),
                v => _shell.QueueSave("merge_notifications", v), out mergeToggle);
            _mergeToggle = mergeToggle;
            if (!notifyOn) mergeToggle.IsEnabled = false;
            card.Children.Add(mergeRow);
            return Ui.Card(card);
        }

        private FrameworkElement PaceCard(Dictionary<string, object> cfg)
        {
            var card = new StackPanel();
            card.Children.Add(Ui.Row("多久检查一次", "后台监控开着的时候，按这个间隔自动查一遍",
                Ui.NumberBox(cfg.ContainsKey("watch_interval_minutes") ? cfg["watch_interval_minutes"] : 5,
                    1, 1440, false, v => _shell.QueueSave("watch_interval_minutes", (int)v), "分钟")));
            card.Children.Add(Ui.Rule(D.S3, D.S3));
            card.Children.Add(Ui.Row("连续出错几次才提醒", "连续出错到这个次数才发一次通知；填 0 表示不提醒",
                Ui.NumberBox(cfg.ContainsKey("notify_on_error_after") ? cfg["notify_on_error_after"] : 3,
                    0, 99, false, v => _shell.QueueSave("notify_on_error_after", (int)v), "次")));
            return Ui.Card(card);
        }

        // ---------------------------------------------------------------- 不打扰
        private FrameworkElement QuietCard(Dictionary<string, object> cfg)
        {
            var card = new StackPanel();
            card.Children.Add(Ui.Row("免打扰时段", "这个时间段里不弹通知；留空表示不启用",
                Ui.Input(Json.Str(cfg, "quiet_hours"), v => _shell.QueueSave("quiet_hours", v),
                    false, false, 140)));
            card.Children.Add(Ui.Rule(D.S3, D.S3));

            bool gameOn = Json.Bool(cfg, "game_mode_enabled", true);
            ToggleButton gameToggle;
            card.Children.Add(Ui.SwitchRow("全屏玩游戏时先不打扰我",
                "检测到全屏游戏就先不检查、不弹通知",
                gameOn, v =>
                {
                    _shell.QueueSave("game_mode_enabled", v);
                    // 只更新下面那个等待时长控件，不重建整页
                    if (_holdBox != null) _holdBox.IsEnabled = v;
                }, out gameToggle));
            card.Children.Add(Ui.Rule(D.S3, D.S3));

            var holdBox = Ui.NumberBox(cfg.ContainsKey("game_exit_hold_seconds") ? cfg["game_exit_hold_seconds"] : 60,
                0, 3600, false, v => _shell.QueueSave("game_exit_hold_seconds", (int)v), "秒");
            _holdBox = holdBox;
            var holdRow = Ui.Row("退出全屏后等多久恢复", "刚退出游戏时先缓一缓，免得立刻弹通知", holdBox);
            if (!gameOn) holdBox.IsEnabled = false;
            card.Children.Add(holdRow);
            card.Children.Add(Ui.Rule(D.S3, D.S3));

            var ignoreGrid = new Grid();
            ignoreGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            ignoreGrid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var ignoreLeft = new StackPanel();
            ignoreLeft.Children.Add(Ui.T("忽略的游戏或程序", "RowLabel"));
            ignoreLeft.Children.Add(Ui.T("这些程序全屏时，同样先不打扰你", "RowHelp"));
            _ignoreHost = new StackPanel { Margin = new Thickness(0, D.S2, 0, 0) };
            BuildIgnoreChips(cfg);
            ignoreLeft.Children.Add(_ignoreHost);
            ignoreGrid.Children.Add(ignoreLeft);
            var pick = Ui.B("选择程序…", "BtnSecondary", PickIgnore);
            pick.VerticalAlignment = VerticalAlignment.Top;
            pick.Margin = new Thickness(D.S3, 2, 0, 0);
            Grid.SetColumn(pick, 1);
            ignoreGrid.Children.Add(pick);
            card.Children.Add(ignoreGrid);
            return Ui.Card(card);
        }

        // ---------------------------------------------------------------- 预览
        private FrameworkElement PreviewCard(Dictionary<string, object> cfg)
        {
            var card = new StackPanel();
            var note = new Border
            {
                Background = (Brush)Application.Current.Resources["Surface2Brush"],
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(10),
                Padding = new Thickness(D.S3, D.S3, D.S3, D.S3)
            };
            var row = new Grid();
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var iconBox = new Border
            {
                Width = 30,
                Height = 30,
                CornerRadius = new CornerRadius(8),
                Background = (Brush)Application.Current.Resources["AccentSoftBrush"],
                VerticalAlignment = VerticalAlignment.Top
            };
            var glow = Ui.Glyph("\uE7C3", 15, (Brush)Application.Current.Resources["AccentBrush"]);
            glow.HorizontalAlignment = HorizontalAlignment.Center;
            iconBox.Child = glow;
            row.Children.Add(iconBox);
            var text = new StackPanel { Margin = new Thickness(D.S3, 0, 0, 0) };
            text.Children.Add(Ui.T("win升级报告", "FieldHint"));
            var title = Ui.T("发现新版本", null, 12.5, FontWeights.SemiBold);
            title.Margin = new Thickness(0, 2, 0, 0);
            text.Children.Add(title);
            var body = Ui.T("Windows 11 26H2 · 22631.4890 → 22631.5189，点开看中文解读", "FieldHint");
            body.Margin = new Thickness(0, 2, 0, 0);
            body.TextWrapping = TextWrapping.Wrap;
            text.Children.Add(body);
            Grid.SetColumn(text, 1);
            row.Children.Add(text);
            note.Child = row;
            card.Children.Add(note);
            var hint = Ui.T("实际样式由 Windows 通知中心决定，这里只是内容示意。", "FieldHint");
            hint.Margin = new Thickness(0, D.S3, 0, 0);
            card.Children.Add(hint);
            return Ui.Card(card);
        }

        // ---------------------------------------------------------------- 托盘
        private FrameworkElement TrayCard(AppData data)
        {
            var card = new StackPanel();
            var grid = new WrapPanel();
            foreach (var t in data.TrayStyles)
            {
                var tile = BuildTrayTile(t);
                grid.Children.Add(tile);
            }
            card.Children.Add(grid);
            var trayHint = Ui.T("这是右下角托盘里的样子；改完几秒内就会换过来。", "FieldHint");
            trayHint.Margin = new Thickness(0, D.S3, 0, 0);
            card.Children.Add(trayHint);
            return Ui.Card(card);
        }

        private FrameworkElement BuildTrayTile(Dictionary<string, object> t)
        {
            var btn = new Button
            {
                Style = (Style)Application.Current.Resources["BtnGhost"],
                Padding = new Thickness(D.S2, D.S2, D.S2, D.S2),
                Margin = new Thickness(0, 0, D.S2, D.S2),
                Width = 76
            };
            bool active = Json.Bool(t, "active", false);
            if (active)
            {
                btn.Style = (Style)Application.Current.Resources["BtnSecondary"];
                btn.BorderBrush = (Brush)Application.Current.Resources["AccentBrush"];
            }
            var sp = new StackPanel { HorizontalAlignment = HorizontalAlignment.Center };
            string preview = Json.Str(t, "preview");
            var img = DecodeImage(preview);
            if (img != null)
            {
                sp.Children.Add(new Image
                {
                    Source = img,
                    Width = 26,
                    Height = 26,
                    Stretch = Stretch.Uniform
                });
            }
            else
            {
                sp.Children.Add(Ui.Glyph("\uE7C3", 20,
                    (Brush)Application.Current.Resources["Ink3Brush"]));
            }
            var name = Ui.T(Json.Str(t, "name"), "FieldHint");
            name.HorizontalAlignment = HorizontalAlignment.Center;
            name.FontSize = 11;
            name.Margin = new Thickness(0, D.S2, 0, 0);
            sp.Children.Add(name);
            btn.Content = sp;
            string id = Json.Str(t, "id");
            btn.Click += (s, e) =>
                _shell.SendAction("set_tray_style", new Dictionary<string, object>
                {
                    { "id", id }
                }, null, null, 20000, r => _shell.RefreshSoon());
            return btn;
        }

        private static ImageSource DecodeImage(string dataUri)
        {
            if (string.IsNullOrEmpty(dataUri)) return null;
            int comma = dataUri.IndexOf(',');
            if (comma < 0) return null;
            try
            {
                byte[] raw = Convert.FromBase64String(dataUri.Substring(comma + 1));
                var bmp = new BitmapImage();
                bmp.BeginInit();
                bmp.StreamSource = new System.IO.MemoryStream(raw);
                bmp.CacheOption = BitmapCacheOption.OnLoad;
                bmp.EndInit();
                bmp.Freeze();
                return bmp;
            }
            catch { return null; }
        }

        // ---------------------------------------------------------------- 详细程度
        private FrameworkElement DetailCard(AppData data)
        {
            var options = data.DetailOptions.Count > 0
                ? data.DetailOptions.ToArray() : new[] { "简短", "标准", "详细" };
            string cur = Json.Str(data.Config, "detail", "标准");
            var card = new StackPanel();
            var row = new Grid();
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            row.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var left = new StackPanel();
            left.Children.Add(Ui.T("报告写多详细", "RowLabel"));
            left.Children.Add(Ui.T("越详细，读起来越完整，写起来也越慢", "RowHelp"));
            row.Children.Add(left);
            var seg = Ui.Segmented(options, cur, v => _shell.QueueSave("detail", v));
            seg.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(seg, 1);
            row.Children.Add(seg);
            card.Children.Add(row);
            return Ui.Card(card);
        }

        // ---------------------------------------------------------------- 静默
        private FrameworkElement SilentCard(Dictionary<string, object> cfg)
        {
            var card = new StackPanel();
            bool silentActive = IsFuture(Json.Str(cfg, "silent_until"));
            var label = Ui.T("暂时静默", "RowLabel");
            card.Children.Add(label);
            var desc = Ui.T(silentActive
                ? "现在处于静默状态，" + Fmt.Hhmm(Json.Str(cfg, "silent_until")) + " 之后恢复检查"
                : "临时不想被打扰时，设一个时长；到点自动恢复检查", "RowHelp");
            card.Children.Add(desc);

            if (silentActive)
            {
                var cancel = Ui.B("取消静默", "BtnSecondary", () =>
                    _shell.SendAction("quiet_now", new Dictionary<string, object>(), "已取消静默",
                        null, 15000));
                cancel.Margin = new Thickness(0, D.S3, 0, 0);
                card.Children.Add(cancel);
            }
            else
            {
                var ctl = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, D.S3, 0, 0) };
                var qty = Ui.Input("2", null, false, false, 56);
                qty.TextAlignment = TextAlignment.Right;
                ctl.Children.Add(qty);
                int unitMinutes = 60;
                var unit = Ui.Segmented(new[] { "小时", "分钟" }, "小时",
                    v => unitMinutes = v == "分钟" ? 1 : 60);
                unit.Margin = new Thickness(D.S2, 0, 0, 0);
                ctl.Children.Add(unit);
                var go = Ui.B("静默", "BtnSecondary", () =>
                {
                    int n;
                    int.TryParse(qty.Text, out n);
                    if (n < 1) { _shell.ToastErr("静默时长要填一个大于 0 的数字"); return; }
                    int mins = n * unitMinutes;
                    if (mins > 7 * 24 * 60) { _shell.ToastErr("最多静默 7 天"); return; }
                    _shell.SendAction("quiet_now", new Dictionary<string, object>
                    {
                        { "minutes", mins }
                    }, "已开始静默", null, 15000);
                });
                go.Margin = new Thickness(D.S2, 0, 0, 0);
                ctl.Children.Add(go);
                card.Children.Add(ctl);
            }
            return Ui.Card(card);
        }

        // ---------------------------------------------------------------- 忽略名单
        private void BuildIgnoreChips(Dictionary<string, object> cfg)
        {
            _ignoreHost.Children.Clear();
            var names = Json.StrList(cfg, "game_ignore");
            if (names.Count == 0)
            {
                _ignoreHost.Children.Add(Ui.T("名单是空的", "FieldHint"));
                return;
            }
            var wrap = new WrapPanel();
            foreach (string name in names)
            {
                var chip = new Border { Style = (Style)Application.Current.Resources["ChipBorder"] };
                var sp = new StackPanel { Orientation = Orientation.Horizontal };
                sp.Children.Add(Ui.T(name, null, 12));
                string captured = name;
                var x = Ui.Link("✕", () =>
                {
                    var list = new List<string>();
                    foreach (string n in Json.StrList(_shell.Data.Config, "game_ignore"))
                        if (n != captured) list.Add(n);
                    _shell.QueueSave("game_ignore", list);
                    BuildIgnoreChips(_shell.Data.Config);
                }, false, true);
                x.Margin = new Thickness(D.S2, 0, 0, 0);
                sp.Children.Add(x);
                chip.Child = sp;
                wrap.Children.Add(chip);
            }
            _ignoreHost.Children.Add(wrap);
            _shell.RefreshFrostLayer();
        }

        private void PickIgnore()
        {
            // exclude_pid：后台服务不是本进程，得把自己的 pid 告诉它，
            // 否则列出来的第一项就是设置窗口自己。
            var args = new Dictionary<string, object>
            {
                { "exclude_pid", System.Diagnostics.Process.GetCurrentProcess().Id }
            };
            _shell.SendAction("list_windows", args, null,
                "正在读取窗口列表…", 15000, r =>
                {
                    // 失败（命令被拒 / 后台断了）时别再弹一个空对话框：错误提示已经由
                    // SendAction 弹过了，这里只把这次点击当失败处理。
                    if (r == null || !Json.Bool(r, "ok", true)) return;
                    var wins = new List<Dictionary<string, object>>();
                    foreach (var w in Json.DictList(r, "windows"))
                    {
                        if (Json.Bool(w, "ignored", false)) continue;
                        wins.Add(w);
                    }
                    if (wins.Count == 0)
                    {
                        _shell.ToastInfo("没有可以加进忽略名单的窗口（已经在名单里的不重复列）");
                        return;
                    }
                    var dlg = new Window
                    {
                        Title = "选择要忽略的程序",
                        Width = 480,
                        Height = 540,
                        Owner = _shell,
                        WindowStartupLocation = WindowStartupLocation.CenterOwner,
                        Background = (Brush)Application.Current.Resources["BgBrush"],
                        FontFamily = (FontFamily)Application.Current.Resources["UiFont"]
                    };
                    var panel = new DockPanel { Margin = new Thickness(D.S5) };
                    var listBox = new ListBox { Margin = new Thickness(0, D.S3, 0, D.S4) };
                    foreach (var w in wins)
                    {
                        var item = new ListBoxItem
                        {
                            Content = Json.Str(w, "name") + "  (" + Json.Str(w, "exe") + ")",
                            Tag = Json.Str(w, "exe")
                        };
                        listBox.Items.Add(item);
                    }
                    var buttons = new StackPanel
                    {
                        Orientation = Orientation.Horizontal,
                        HorizontalAlignment = HorizontalAlignment.Right
                    };
                    var ok = Ui.B("加入忽略名单", "BtnPrimary", () =>
                    {
                        var current = new List<string>(Json.StrList(_shell.Data.Config, "game_ignore"));
                        foreach (object o in listBox.SelectedItems)
                        {
                            var it = o as ListBoxItem;
                            string exe = it != null ? Convert.ToString(it.Tag) : "";
                            if (!string.IsNullOrEmpty(exe) && !current.Contains(exe)) current.Add(exe);
                        }
                        _shell.QueueSave("game_ignore", current);
                        BuildIgnoreChips(_shell.Data.Config);
                        dlg.Close();
                    });
                    var cancel = Ui.B("取消", "BtnSecondary", () => dlg.Close());
                    cancel.Margin = new Thickness(D.S3, 0, 0, 0);
                    buttons.Children.Add(ok);
                    buttons.Children.Add(cancel);
                    DockPanel.SetDock(buttons, Dock.Bottom);
                    panel.Children.Add(buttons);
                    panel.Children.Add(listBox);
                    dlg.Content = panel;
                    dlg.ShowDialog();
                });
        }

        private static bool IsFuture(string iso)
        {
            if (string.IsNullOrEmpty(iso)) return false;
            DateTime dt;
            return DateTime.TryParse(iso, out dt) && dt > DateTime.Now;
        }
    }
}
