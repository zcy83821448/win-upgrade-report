using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media;

namespace WinUpd
{
    /// <summary>
    /// 设置：AI 接入是主角，高级参数收起来不吓人，右边放本机路径和提示。
    /// </summary>
    public sealed class SettingsPage : IPage
    {
        private readonly MainWindow _shell;
        private readonly StackPanel _root = new StackPanel();
        private readonly ScrollViewer _scroller;
        private TextBlock _apiResult;

        public string Key { get { return "settings"; } }
        public string Title { get { return "设置"; } }
        public FrameworkElement Root { get { return _scroller; } }

        public SettingsPage(MainWindow shell)
        {
            _shell = shell;
            _scroller = Ui.Scroller(_root);
            shell.ApiTestSink = (text, ok) =>
            {
                if (_apiResult == null) return;
                _apiResult.Text = text;
                _apiResult.Foreground = (Brush)Application.Current.Resources[
                    ok ? "OkBrush" : "BadBrush"];
            };
        }

        public void LoadData(AppData data)
        {
            _root.Children.Clear();
            _apiResult = null;
            var cfg = data.Config;

            _root.Children.Add(Ui.PageHeader("设置", "设置",
                "接上 AI 才能写出中文报告；改完自动保存，不需要点保存按钮。"));

            var left = new StackPanel();
            left.Children.Add(Ui.Section("AI 接入", "报告的全部文字都由它生成", AiCard(cfg)));
            left.Children.Add(AdvancedCard(cfg));

            var right = new StackPanel();
            right.Children.Add(Ui.Section("本机路径", null, AboutCard(data)));
            right.Children.Add(Ui.Section("配置提示", null, TipsCard()));

            _root.Children.Add(Ui.TwoColumn(left, right));
        }

        public void ApplyPoll(PollUpdate poll) { }

        // ---------------------------------------------------------------- AI
        private FrameworkElement AiCard(Dictionary<string, object> cfg)
        {
            var card = new StackPanel();

            card.Children.Add(Ui.Row("AI 服务地址", "和 OpenAI 兼容的服务都可以，一般不用改",
                Ui.Input(Json.Str(cfg, "api_base"), v => _shell.QueueSave("api_base", v), true, true)));
            card.Children.Add(Ui.Rule(D.S3, D.S3));

            // Key：单独一整行，输入框占满，眼睛和测试按钮在右侧
            var keyBox = new StackPanel();
            keyBox.Children.Add(Ui.T("AI 的 Key", "RowLabel"));
            keyBox.Children.Add(Ui.T(string.IsNullOrEmpty(Json.Str(cfg, "api_key"))
                ? "必填；不填的话，发现新版本也写不出中文报告"
                : "只保存在本机的设置里，不会上传", "RowHelp"));
            var keyRow = new Grid { Margin = new Thickness(0, D.S3, 0, 0) };
            keyRow.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            keyRow.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var pwd = new PasswordBox
            {
                Style = (Style)Application.Current.Resources["InputPassword"],
                Password = Json.Str(cfg, "api_key"),
                VerticalAlignment = VerticalAlignment.Center
            };
            var plain = new TextBox
            {
                Style = (Style)Application.Current.Resources["InputMono"],
                Text = Json.Str(cfg, "api_key"),
                Visibility = Visibility.Collapsed
            };
            pwd.PasswordChanged += (s, e) => _shell.QueueSave("api_key", pwd.Password);
            plain.TextChanged += (s, e) => _shell.QueueSave("api_key", plain.Text);
            var keyStack = new Grid();
            keyStack.Children.Add(pwd);
            keyStack.Children.Add(plain);
            var eye = Ui.IconButton("\uE7B3", "显示 / 隐藏 Key", () =>
            {
                bool show = pwd.Visibility == Visibility.Visible;
                if (show)
                {
                    plain.Text = pwd.Password;
                    pwd.Visibility = Visibility.Collapsed;
                    plain.Visibility = Visibility.Visible;
                    plain.Focus();
                }
                else
                {
                    pwd.Password = plain.Text;
                    plain.Visibility = Visibility.Collapsed;
                    pwd.Visibility = Visibility.Visible;
                    pwd.Focus();
                }
            });
            eye.HorizontalAlignment = HorizontalAlignment.Right;
            eye.VerticalAlignment = VerticalAlignment.Center;
            eye.Margin = new Thickness(0, 0, 3, 0);
            keyStack.Children.Add(eye);
            keyRow.Children.Add(keyStack);
            var test = Ui.B("测试", "BtnSecondary", TestApi);
            test.Margin = new Thickness(D.S2, 0, 0, 0);
            test.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(test, 1);
            keyRow.Children.Add(test);
            keyBox.Children.Add(keyRow);
            _apiResult = Ui.T("", "FieldHint");
            _apiResult.Margin = new Thickness(0, D.S2, 0, 0);
            keyBox.Children.Add(_apiResult);
            card.Children.Add(keyBox);

            card.Children.Add(Ui.Rule(D.S3, D.S3));
            card.Children.Add(Ui.Row("用哪个模型", "例如 deepseek-flash",
                Ui.Input(Json.Str(cfg, "model"), v => _shell.QueueSave("model", v), true, true)));
            card.Children.Add(Ui.Rule(D.S3, D.S3));

            ToggleButton thinking;
            card.Children.Add(Ui.SwitchRow("关闭思考，回答更快",
                "有些模型不支持思考模式，关掉也不影响使用",
                Json.Bool(cfg, "disable_thinking", true),
                v => _shell.QueueSave("disable_thinking", v), out thinking));
            return Ui.Card(card);
        }

        private void TestApi()
        {
            _shell.SendAction("test_api", new Dictionary<string, object>(), null,
                "正在测试 AI…", 120000, null);
        }

        // ---------------------------------------------------------------- 高级
        private FrameworkElement AdvancedCard(Dictionary<string, object> cfg)
        {
            var body = new StackPanel { Visibility = Visibility.Collapsed, Margin = new Thickness(0, D.S3, 0, 0) };
            body.Children.Add(Ui.Row("最大输出长度", "每次让 AI 写多少字，太长会变慢",
                Ui.NumberBox(cfg.ContainsKey("max_tokens") ? cfg["max_tokens"] : 1600,
                    100, 8000, false, v => _shell.QueueSave("max_tokens", (int)v), "字")));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            body.Children.Add(Ui.Row("温度", "0 更稳，1 更活；写报告一般用 0.3",
                Ui.NumberBox(cfg.ContainsKey("temperature") ? cfg["temperature"] : 0.3,
                    0, 2, true, v => _shell.QueueSave("temperature", v), "", 80)));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            body.Children.Add(Ui.Row("单次请求超时", "网络慢的时候可以调大",
                Ui.NumberBox(cfg.ContainsKey("request_timeout") ? cfg["request_timeout"] : 60,
                    10, 900, false, v => _shell.QueueSave("request_timeout", (int)v), "秒")));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            body.Children.Add(Ui.Row("失败重试", "请求失败后自动再试几次",
                Ui.NumberBox(cfg.ContainsKey("retries") ? cfg["retries"] : 2,
                    0, 10, false, v => _shell.QueueSave("retries", (int)v), "次")));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            body.Children.Add(Ui.Row("同时检测几条线", "网络好的话可以多一点",
                Ui.NumberBox(cfg.ContainsKey("max_workers") ? cfg["max_workers"] : 4,
                    1, 16, false, v => _shell.QueueSave("max_workers", (int)v), "条")));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            body.Children.Add(Ui.Row("报告最多读多少原文", "给 AI 的官方原文上限，太大容易超时",
                Ui.NumberBox(cfg.ContainsKey("max_context_chars") ? cfg["max_context_chars"] : 16000,
                    1000, 200000, false, v => _shell.QueueSave("max_context_chars", (int)v), "字", 104)));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            body.Children.Add(Ui.Row("保留最近几份报告", "更早的报告会被自动清理",
                Ui.NumberBox(cfg.ContainsKey("keep_reports") ? cfg["keep_reports"] : 200,
                    10, 5000, false, v => _shell.QueueSave("keep_reports", (int)v), "份")));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            body.Children.Add(Ui.Row("代理地址", "留空表示不使用代理",
                Ui.Input(Json.Str(cfg, "proxy"), v => _shell.QueueSave("proxy", v), true, true)));
            body.Children.Add(Ui.Rule(D.S3, D.S3));
            ToggleButton include;
            body.Children.Add(Ui.SwitchRow("报告里附上官方原文", "会多贴一段英文原文，方便对照",
                Json.Bool(cfg, "include_official_text", false),
                v => _shell.QueueSave("include_official_text", v), out include));
            body.Children.Add(Ui.Rule(D.S2, D.S2));
            ToggleButton openBrowser;
            body.Children.Add(Ui.SwitchRow("点报告时直接用浏览器打开", "默认在界面里看；打开后也可以再用浏览器看",
                Json.Bool(cfg, "open_report_on_click", false),
                v => _shell.QueueSave("open_report_on_click", v), out openBrowser));

            var card = new StackPanel();
            var head = new Button { Style = (Style)Application.Current.Resources["FoldHead"] };
            var hg = new Grid();
            hg.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            hg.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var label = Ui.T("高级选项", "RowLabel");
            hg.Children.Add(label);
            var chev = Ui.Glyph("\uE70D", 11, (Brush)Application.Current.Resources["Ink3Brush"]);
            chev.HorizontalAlignment = HorizontalAlignment.Right;
            Grid.SetColumn(chev, 1);
            hg.Children.Add(chev);
            head.Content = hg;
            head.Click += (s, e) =>
            {
                bool show = body.Visibility != Visibility.Visible;
                body.Visibility = show ? Visibility.Visible : Visibility.Collapsed;
                chev.Text = show ? "\uE70E" : "\uE70D";
                if (show) Anim.FadeSlideIn(body, Anim.Base, 0, -4);
                _shell.FollowFrost(380);
            };
            card.Children.Add(head);
            card.Children.Add(body);
            return Ui.Card(card);
        }

        // ---------------------------------------------------------------- 关于
        private FrameworkElement AboutCard(AppData data)
        {
            var card = new StackPanel();
            card.Children.Add(PathRow("程序位置", Json.Str(data.App, "exe"), "打开程序目录",
                () => _shell.OpenExternal("app_folder")));
            card.Children.Add(Ui.Rule(D.S3, D.S3));
            card.Children.Add(PathRow("设置存在哪里", Json.Str(data.App, "base_dir"), "打开设置目录",
                () => _shell.OpenExternal("folder", Json.Str(data.App, "base_dir"))));
            return Ui.Card(card);
        }

        private FrameworkElement PathRow(string label, string path, string btnText, Action click)
        {
            var sp = new StackPanel();
            sp.Children.Add(Ui.T(label, "RowLabel"));
            var p = Ui.T(string.IsNullOrEmpty(path) ? "—" : path, "MonoText");
            p.Margin = new Thickness(0, D.S2, 0, 0);
            p.TextTrimming = TextTrimming.CharacterEllipsis;
            p.ToolTip = path;
            sp.Children.Add(p);
            var open = Ui.B(btnText, "BtnGhost", click);
            open.HorizontalAlignment = HorizontalAlignment.Left;
            open.Margin = new Thickness(-2, D.S3, 0, 0);
            sp.Children.Add(open);
            return sp;
        }

        private FrameworkElement TipsCard()
        {
            var card = new StackPanel();
            AddTip(card, "Key 只在请求 AI 时用", "它保存在本机的 config.json 里，程序不会上传到别处。");
            AddTip(card, "改完立刻保存", "输入框失焦后自动保存；右上角会提示「已保存」。");
            AddTip(card, "报告默认只在本机", "报告写在程序目录的 reports 里，「报告」页可以打开文件夹。");
            var tail = Ui.T("更多排查在「日志与诊断」页。", "FieldHint");
            tail.Margin = new Thickness(0, D.S2, 0, 0);
            card.Children.Add(tail);
            return Ui.Card(card);
        }

        private static void AddTip(Panel card, string title, string help)
        {
            var sp = new StackPanel { Margin = new Thickness(0, 0, 0, D.S3) };
            var line = new StackPanel { Orientation = Orientation.Horizontal };
            var dot = new System.Windows.Shapes.Ellipse
            {
                Width = 6,
                Height = 6,
                Fill = (Brush)Application.Current.Resources["LineStrongBrush"],
                VerticalAlignment = VerticalAlignment.Top,
                Margin = new Thickness(0, 6, D.S3, 0)
            };
            line.Children.Add(dot);
            var t = Ui.T(title, "RowLabel");
            t.FontWeight = FontWeights.SemiBold;
            line.Children.Add(t);
            sp.Children.Add(line);
            var h = Ui.T(help, "FieldHint");
            h.Margin = new Thickness(19, 2, 0, 0);
            sp.Children.Add(h);
            card.Children.Add(sp);
        }
    }
}
