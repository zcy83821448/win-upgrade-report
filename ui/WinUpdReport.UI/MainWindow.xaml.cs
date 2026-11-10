using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Media.Imaging;
using System.Windows.Threading;

namespace WinUpd
{
    public partial class MainWindow : Window
    {
        private readonly UiClient _client;
        private readonly Dictionary<string, IPage> _pages = new Dictionary<string, IPage>();
        private readonly DispatcherTimer _pollTimer;
        private readonly DispatcherTimer _saveTimer;
        private readonly DispatcherTimer _refreshTimer;
        private readonly Dictionary<string, object> _pendingSave = new Dictionary<string, object>();
        private AppData _data = new AppData();
        private PollUpdate _lastPoll = new PollUpdate();
        private string _currentPage = "overview";
        private string _readerFile = "";
        private bool _polling;
        private bool _bootstrapRunning;
        private bool _shotDone;
        private bool _quitting;
        private readonly RotateTransform _spinner = new RotateTransform();
        private readonly DispatcherTimer _blurTimer;
        private BlurBase _blurBase;
        private BitmapSource _wallpaperSharp;
        private bool _frostCollectPending;
        private bool _frostScrollPending;
        private DateTime _frostFollowUntil;
        private EventHandler _frostFollowFrame;
        private bool _wallpaperDark;
        private bool _personalized;

        public AppData Data { get { return _data; } }
        public string CurrentPage { get { return _currentPage; } }

        /// <summary>Settings 页的 AI 测试结果回调。</summary>
        public Action<string, bool> ApiTestSink;
        /// <summary>Logs 页的体检结果回调。</summary>
        public Action<string, List<Dictionary<string, object>>> SelfcheckSink;
        public string SelfcheckSummary = "";
        public List<Dictionary<string, object>> SelfcheckItems
            = new List<Dictionary<string, object>>();

        public void ApplyChannels(List<Dictionary<string, object>> channels)
        {
            if (channels == null || channels.Count == 0) return;
            _data.Channels = channels;
            ReloadCurrentPage();
        }

        /// <summary>只更新数据、不重建页面：开关这类"小状态"用它，避免整页闪一下。</summary>
        public void UpdateChannelsQuiet(List<Dictionary<string, object>> channels)
        {
            if (channels == null || channels.Count == 0) return;
            _data.Channels = channels;
        }

        public void ApplyReports(List<Dictionary<string, object>> reports)
        {
            if (reports == null) return;
            _data.Reports = reports;
            ReloadCurrentPage();
        }

        private void ReloadCurrentPage()
        {
            IPage page;
            if (_pages.TryGetValue(_currentPage, out page))
            {
                try { page.LoadData(_data); } catch (Exception e) { AppEnv.Log("刷新页面失败：" + e); }
            }
            UpdateWatchUI();
            ScheduleFrostCollect();
        }

        public void ApplyAccentColor(string hex)
        {
            ApplyAccent(hex);
        }

        /// <summary>个性化参数实时预览（拖动滑杆时直接生效，不等保存）。</summary>
        public void PreviewPersonalize(int blur, int cardAlpha, int scrim)
        {
            if (_data.Personalize == null) _data.Personalize = new Dictionary<string, object>();
            bool changed = blur != Json.Int(_data.Personalize, "blur", 15)
                || cardAlpha != Json.Int(_data.Personalize, "card_alpha", 70)
                || scrim != Json.Int(_data.Personalize, "scrim_alpha", 0);
            _data.Personalize["blur"] = blur;
            _data.Personalize["card_alpha"] = cardAlpha;
            _data.Personalize["scrim_alpha"] = scrim;
            if (!_personalized) return;
            // 值没变就别重建模糊底图：个性化页每次 LoadData 都会调到这里，
            // 以前切一次页就重算一遍高斯模糊，设了壁纸时会明显卡一下/闪一下。
            if (!changed) return;
            ApplyPalette(_wallpaperDark, cardAlpha / 100.0);
            ApplyScrim(scrim / 100.0);
            _blurTimer.Stop();
            _blurTimer.Start();
            CollectFrostTargets();
        }

        public MainWindow(UiClient client)
        {
            _client = client;
            AppEnv.Mark("MainWindow ctor start");
            App.Boot("MW: before InitializeComponent");
            InitializeComponent();
            {
                // 默认 1200x800；小屏幕（缩放 125% 的 1366x768 等）按工作区自动收一档
                double ww = AppEnv.WindowW, hh = AppEnv.WindowH;
                var wa = SystemParameters.WorkArea;
                ww = Math.Min(ww, Math.Max(MinWidth, wa.Width - 48));
                hh = Math.Min(hh, Math.Max(MinHeight, wa.Height - 48));
                if (!double.IsNaN(ww) && ww > 0) Width = ww;
                if (!double.IsNaN(hh) && hh > 0) Height = hh;
            }
            if (AppEnv.Maximized) WindowState = WindowState.Maximized;
            App.Boot("MW: InitializeComponent done");
            AppEnv.Mark("MainWindow InitializeComponent done");

            // 首屏直接用磁盘快照，不等 Python 服务。
            try
            {
                AppSnapshot snap = LocalData.Load();
                if (snap.Config.Count > 0 || snap.State.Count > 0)
                {
                    _data.Config = snap.Config;
                    _data.State = snap.State;
                    _data.LogPath = Path.Combine(AppEnv.DataDir, "logs", "checker.log");
                    _data.BaseDir = AppEnv.DataDir;
                }
            }
            catch (Exception e)
            {
                AppEnv.Log("读取本地快照失败：" + e.Message);
            }

            App.Boot("MW: snapshot loaded");
            ActivitySpinner.RenderTransform = _spinner;
            App.Boot("MW: spinner set");
            _pollTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            _pollTimer.Tick += (s, e) => PollTick();
            _saveTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(600) };
            _saveTimer.Tick += (s, e) => { _saveTimer.Stop(); FlushSave(); };
            _refreshTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(450) };
            _refreshTimer.Tick += (s, e) => { _refreshTimer.Stop(); RequestBootstrap(false); };
            _blurTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(240) };
            _blurTimer.Tick += (s, e) => { _blurTimer.Stop(); RebuildBlur(true); };

            Loaded += OnLoaded;
            SourceInitialized += OnSourceInitialized;
            SizeChanged += (s, e) =>
            {
                UpdateMaxGlyph();
                MoveNavIndicator(false);
                OnWindowLayoutMoved();
            };
            // 页面里滚动/翻页不再需要同步任何"补丁"：背景是固定的整张模糊壁纸。
            // 页面里任何滚动（整页/列表/日志）都会让卡片位置变化，
            // 毛玻璃只在卡片底下有，所以必须跟着卡片重画。
            AddHandler(ScrollViewer.ScrollChangedEvent,
                new ScrollChangedEventHandler(OnAnyScrollChanged), true);
            StateChanged += (s, e) => { UpdateMaxGlyph(); };
            PreviewKeyDown += OnPreviewKeyDown;
            // 滚轮平滑滚动（整页 / 列表 / 日志 / 阅读器都生效）
            SmoothScroll.Attach(Root);
            SmoothScroll.FrameTick += OnSmoothScrollFrame;
            ReaderOverlay.MouseLeftButtonDown += (s, e) =>
            {
                if (e.Source == ReaderOverlay) CloseReader();
            };
            Activated += (s, e) => { UpdateMaxGlyph(); };

            App.Boot("MW: before Navigate");
            Navigate(AppEnv.InitialPage);
            App.Boot("MW: Navigate done");
            UpdateWatchUI();
            App.Boot("MW: UpdateWatchUI done");
            AppEnv.Mark("MainWindow first page built");
        }

        // ================================================================ 生命周期
        private void OnLoaded(object sender, RoutedEventArgs e)
        {
            App.Boot("Loaded enter");
            AppEnv.Mark("MainWindow.Loaded");
            try
            {
                App.Boot("Loaded: before Dwm");
                Dwm.RoundCorners(this);
                App.Boot("Loaded: after Dwm");
                Anim.WindowIn(Root);
                App.Boot("Loaded: after WindowIn");
                Dispatcher.BeginInvoke(new Action(() => MoveNavIndicator(false)),
                    System.Windows.Threading.DispatcherPriority.Loaded);
            }
            catch (Exception ex) { App.Boot("Loaded anim error: " + ex.Message); }
            AttachClient();
            App.Boot("Loaded: client attached");
            _pollTimer.Start();
            if (!string.IsNullOrEmpty(AppEnv.ShotPath)) ScheduleShot();
            App.Boot("Loaded done");
        }

        private void OnSourceInitialized(object sender, EventArgs e)
        {
            var helper = new WindowInteropHelper(this);
            HwndSource source = HwndSource.FromHwnd(helper.Handle);
            if (source != null) source.AddHook(WndProc);
            Dwm.RoundCorners(this);
        }

        private void AttachClient()
        {
            App.Boot("AttachClient enter");
            if (_client == null)
            {
                App.Boot("AttachClient: client null");
                SetConn(false, "只读模式：后台服务不可用");
                return;
            }
            App.Boot("AttachClient: subscribing");
            _client.ConnectionChanged += (ok, msg) =>
            {
                Dispatcher.BeginInvoke(new Action(() =>
                {
                    if (ok) OnConnected();
                    else SetConn(false, msg);
                }));
            };
            App.Boot("AttachClient: subscribed, connected=" + _client.Connected);
            if (_client.Connected)
            {
                // 不在 Loaded 里同步跑任何后台请求，推迟到窗口画出来之后
                Dispatcher.BeginInvoke(new Action(() => { App.Boot("OnConnected via dispatcher"); OnConnected(); }),
                    System.Windows.Threading.DispatcherPriority.Background);
            }
            App.Boot("AttachClient done");
        }

        private void OnConnected()
        {
            App.Boot("OnConnected enter");
            SetConn(true, "");
            App.Boot("OnConnected: conn hint set");
            AppEnv.Mark("service connected");
            if (!_bootstrapRunning) RequestBootstrap(true);
            App.Boot("OnConnected done");
        }

        public async void RequestBootstrap(bool showActivity)
        {
            if (_client == null || _bootstrapRunning || !_client.Connected)
            {
                if (showActivity) SetConn(false, "正在连接后台…");
                return;
            }
            _bootstrapRunning = true;
            App.Boot("bootstrap: before SetActivity");
            if (showActivity) SetActivity("正在读取设置…");
            App.Boot("bootstrap: after SetActivity, before RequestAsync");
            try
            {
                var resp = await _client.RequestAsync("bootstrap", null, 25000);
                if (UiClient.IsOk(resp))
                {
                    var result = UiClient.Result(resp);
                    ApplyData(AppData.FromBootstrap(result));
                    SetConn(true, "");
                    AppEnv.Mark("bootstrap applied");
                }
                else
                {
                    SetConn(false, "后台没有回应，正在重试…");
                    if (showActivity) ToastErr("读取设置失败：" + UiClient.ErrorOf(resp));
                }
            }
            catch (Exception e)
            {
                SetConn(false, "后台连接出错，正在重试…");
                if (showActivity) ToastErr("读取设置失败：" + e.Message);
            }
            finally
            {
                _bootstrapRunning = false;
                if (showActivity) ClearActivity();
                MaybeFinishShot();
            }
        }

        private void ApplyData(AppData d)
        {
            _data = d;
            UpdateWatchUI();
            ApplyPersonalize();
            // 只重建当前可见页；其它页在切过去时 Navigate 会自己 LoadData。
            // （以前这里把所有页都重建一遍，点个开关触发一次 bootstrap 就会让整窗卡一下。）
            IPage page;
            if (_pages.TryGetValue(_currentPage, out page))
            {
                try { page.LoadData(_data); }
                catch (Exception e) { AppEnv.Log("当前页刷新失败 " + _currentPage + "：" + e); }
            }
            ScheduleFrostCollect();
            MaybeFinishShot();
        }

        // ================================================================ 轮询
        private async void PollTick()
        {
            if (_client == null || !_client.Connected || _polling || _bootstrapRunning)
                return;
            _polling = true;
            try
            {
                var resp = await _client.RequestAsync("poll", null, 5000);
                if (!UiClient.IsOk(resp))
                {
                    SetConn(false, "后台连接中断，正在自动重试…");
                    return;
                }
                SetConn(true, "");
                var update = PollUpdate.From(UiClient.Result(resp));
                ApplyPoll(update);
            }
            catch { }
            finally { _polling = false; }
        }

        private void ApplyPoll(PollUpdate u)
        {
            _lastPoll = u;
            if (u.Watch != null) _data.Watch = u.Watch;
            if (u.Startup != null) _data.Startup = u.Startup;
            if (!string.IsNullOrEmpty(u.TaskText)) _data.TaskText = u.TaskText;
            if (!string.IsNullOrEmpty(u.Now)) _data.Now = u.Now;
            UpdateWatchUI();
            IPage page;
            if (_pages.TryGetValue(_currentPage, out page))
            {
                try { page.ApplyPoll(u); } catch (Exception e) { AppEnv.Log("轮询刷新失败：" + e); }
            }
            if (u.Events != null && u.Events.Count > 0)
            {
                foreach (var ev in u.Events) HandleEvent(ev);
            }
            if (u.Live != null && Json.Bool(u.Live, "active", false))
                SetActivity(Json.Str(u.Live, "text") ?? "正在处理…");
            else if (u.Live != null && !Json.Bool(u.Live, "active", false)
                     && Json.DictList(u.Raw, "events").Count == 0)
            {
                // 后台空闲时不强行关掉页面自己开的 activity（由命令回调负责）
            }
            if (u.Live == null) { }
        }

        private void HandleEvent(Dictionary<string, object> ev)
        {
            string type = Json.Str(ev, "type");
            if (type == "busy")
            {
                if (Json.Bool(ev, "active", false)) SetActivity(Json.Str(ev, "text"));
                else ClearActivity();
                return;
            }
            if (type == "done")
            {
                string kind = Json.Str(ev, "kind");
                string text = Json.Str(ev, "text");
                bool ok = Json.Bool(ev, "ok", true);
                if (!string.IsNullOrEmpty(text))
                {
                    if (ok) ToastOk(text); else ToastErr(text);
                }
                if (kind == "api_test") OnApiTest(text, ok);
                if (kind == "check" || kind == "selfcheck" || kind == "discover"
                    || kind == "task_install" || kind == "task_remove")
                    RefreshSoon();
                return;
            }
            if (type == "selfcheck")
            {
                SelfcheckSummary = Json.Str(ev, "summary");
                SelfcheckItems = Json.DictList(ev, "items");
                var sink = SelfcheckSink;
                if (sink != null) sink(SelfcheckSummary, SelfcheckItems);
                return;
            }
            if (type == "task_info")
            {
                _data.TaskText = Json.Str(ev, "text");
                return;
            }
            if (type == "reports")
            {
                ApplyReports(Json.DictList(ev, "reports"));
                return;
            }
            if (type == "channels")
            {
                var list = Json.DictList(ev, "channels");
                if (list.Count > 0)
                {
                    // 只是某条线启用/架构变了：静默更新数据，不重建页面（重建会让卡片闪一下）。
                    // 真加了/删了线（条数变化）才整页刷新。
                    bool structural = list.Count != _data.Channels.Count;
                    if (!structural)
                    {
                        var ids = new HashSet<string>();
                        foreach (var c in _data.Channels) ids.Add(Json.Str(c, "id"));
                        foreach (var c in list)
                            if (!ids.Contains(Json.Str(c, "id"))) { structural = true; break; }
                    }
                    if (structural) ApplyChannels(list);
                    else UpdateChannelsQuiet(list);
                }
                return;
            }
            if (type == "discover")
            {
                string text = Json.Str(ev, "text");
                if (!string.IsNullOrEmpty(text))
                {
                    if (Json.Bool(ev, "ok", true)) ToastOk(text); else ToastErr(text);
                }
            }
        }

        private void OnApiTest(string text, bool ok)
        {
            var sink = ApiTestSink;
            if (sink != null) sink(text, ok);
        }

        // ================================================================ 保存
        public void QueueSave(string key, object value)
        {
            _data.Config[key] = value;
            _pendingSave[key] = value;
            _saveTimer.Stop();
            _saveTimer.Start();
            ShowSaved("未保存…", false);
        }

        private async void FlushSave()
        {
            if (_pendingSave.Count == 0) return;
            var partial = new Dictionary<string, object>(_pendingSave);
            _pendingSave.Clear();
            var resp = await CallService("save_config", new Dictionary<string, object>
            {
                { "partial", partial }
            }, 15000);
            var result = UiClient.Result(resp);
            if (UiClient.IsOk(resp) && (result == null || Json.Bool(result, "ok", true)))
            {
                ShowSaved("已保存", false);
            }
            else if (result != null && Json.Bool(result, "retry", false))
            {
                foreach (var kv in partial) _pendingSave[kv.Key] = kv.Value;
                _saveTimer.Start();
                ShowSaved("正在重试保存…", false);
            }
            else
            {
                ShowSaved("未保存", true);
                ToastErr("保存失败：" + UiClient.ErrorOf(resp));
            }
        }

        /// <summary>关窗/退出前把没保存的设置同步写掉（最多等 timeoutMs，不能无声丢掉用户的改动）。</summary>
        private void FlushSaveBlocking(int timeoutMs)
        {
            _saveTimer.Stop();
            if (_pendingSave.Count == 0 || _client == null) return;
            var partial = new Dictionary<string, object>(_pendingSave);
            _pendingSave.Clear();
            try
            {
                var task = _client.RequestAsync("save_config", new Dictionary<string, object>
                {
                    { "partial", partial }
                }, timeoutMs);
                if (!task.Wait(timeoutMs))
                {
                    foreach (var kv in partial) _pendingSave[kv.Key] = kv.Value;
                }
            }
            catch
            {
                foreach (var kv in partial) _pendingSave[kv.Key] = kv.Value;
            }
        }

        public void ShowSaved(string text, bool bad)
        {
            SavedHint.Text = text;
            SavedHint.Foreground = (Brush)Application.Current.Resources[
                bad ? "BadBrush" : "Ink3Brush"];
            SavedHint.Opacity = 0;
            Anim.Fade(SavedHint, 0, 1, 180);
            if (text == "已保存")
            {
                var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2.2) };
                timer.Tick += (s, e) =>
                {
                    timer.Stop();
                    if (SavedHint.Text == "已保存") SavedHint.Text = "";
                };
                timer.Start();
            }
        }

        // ================================================================ 服务命令
        public async System.Threading.Tasks.Task<Dictionary<string, object>> CallService(
            string cmd, Dictionary<string, object> args = null, int timeoutMs = 20000)
        {
            if (_client == null) return UiClient.Error("后台服务不可用");
            return await _client.RequestAsync(cmd, args, timeoutMs);
        }

        public void SendAction(string cmd, Dictionary<string, object> args,
            string okToast = null, string activity = null, int timeoutMs = 60000,
            Action<Dictionary<string, object>> after = null, bool refreshAfter = true,
            Action fail = null)
        {
            if (activity != null) SetActivity(activity);
            Action<Dictionary<string, object>> done = resp =>
            {
                if (activity != null) ClearActivity();
                if (UiClient.IsOk(resp))
                {
                    var result = UiClient.Result(resp);
                    if (result != null && !Json.Bool(result, "ok", true))
                    {
                        ToastErr(UiClient.ErrorOf(resp));
                    }
                    else
                    {
                        if (!string.IsNullOrEmpty(okToast)) ToastOk(okToast);
                    }
                    if (after != null) after(result);
                    if (refreshAfter) RefreshSoon();
                }
                else
                {
                    ToastErr(UiClient.ErrorOf(resp));
                    if (fail != null) fail();
                }
            };
            System.Threading.Tasks.Task.Run(async () =>
            {
                var resp = await CallService(cmd, args, timeoutMs);
                Dispatcher.BeginInvoke(new Action(() => done(resp)));
            });
        }

        public void OpenExternal(string kind, string path = "")
        {
            SendAction("open_external", new Dictionary<string, object>
            {
                { "kind", kind }, { "path", path ?? "" }
            }, null, null, 20000);
        }

        // ================================================================ 通知 / 忙碌
        public void ToastOk(string text) { Toast("ok", text); }
        public void ToastErr(string text) { Toast("error", text); }
        public void ToastInfo(string text) { Toast("info", text); }

        public void Toast(string kind, string text)
        {
            var border = new Border
            {
                Style = (Style)Application.Current.Resources["Card"],
                Padding = new Thickness(14, 11, 16, 11),
                Margin = new Thickness(0, 0, 0, 9),
                MaxWidth = 360,
                HorizontalAlignment = HorizontalAlignment.Right
            };
            string glyph = kind == "error" ? "\uE783" : (kind == "ok" ? "\uE73E" : "\uE946");
            Brush color = (Brush)Application.Current.Resources[
                kind == "error" ? "BadBrush" : (kind == "ok" ? "OkBrush" : "AccentBrush")];
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            var icon = Ui.Glyph(glyph, 15, color);
            icon.Margin = new Thickness(0, 1, 10, 0);
            icon.VerticalAlignment = VerticalAlignment.Top;
            grid.Children.Add(icon);
            var tb = new TextBlock
            {
                Text = text,
                TextWrapping = TextWrapping.Wrap,
                FontSize = 12.5,
                Foreground = (Brush)Application.Current.Resources["InkBrush"]
            };
            Grid.SetColumn(tb, 1);
            grid.Children.Add(tb);
            border.Child = grid;
            border.Margin = new Thickness(0, 0, 0, 9);
            ToastHost.Children.Add(border);
            Anim.ToastIn(border);
            while (ToastHost.Children.Count > 4)
                ToastHost.Children.RemoveAt(0);
            var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3.6) };
            timer.Tick += (s, e) =>
            {
                timer.Stop();
                Anim.ToastOut(border, () => { ToastHost.Children.Remove(border); });
            };
            timer.Start();
        }

        public void SetActivity(string text)
        {
            ActivityText.Text = text ?? "";
            if (ActivityBar.Visibility != Visibility.Visible)
            {
                Anim.ActivityIn(ActivityBar);
                StartFrostFollow(340);
                _spinner.BeginAnimation(RotateTransform.AngleProperty,
                    new DoubleAnimation(0, 360, TimeSpan.FromSeconds(1.2))
                    {
                        RepeatBehavior = RepeatBehavior.Forever
                    });
            }
        }

        public void ClearActivity()
        {
            _spinner.BeginAnimation(RotateTransform.AngleProperty, null);
            if (ActivityBar.Visibility == Visibility.Visible)
            {
                Anim.ActivityOut(ActivityBar, null);
                StartFrostFollow(240);
            }
        }

        public void SetConn(bool ok, string text)
        {
            if (ok)
            {
                ConnHint.Visibility = Visibility.Collapsed;
                return;
            }
            ConnHint.Text = text;
            ConnHint.Visibility = Visibility.Visible;
        }

        public void RefreshSoon()
        {
            _refreshTimer.Stop();
            _refreshTimer.Start();
        }

        // ================================================================ 导航
        private static readonly string[] NavOrder =
        {
            "overview", "channels", "notify", "personalize", "settings", "startup", "reports", "logs"
        };

        private static int NavIndex(string key)
        {
            int i = Array.IndexOf(NavOrder, key);
            return i < 0 ? 0 : i;
        }

        private void Nav_Click(object sender, RoutedEventArgs e)
        {
            var rb = sender as RadioButton;
            if (rb == null) return;
            string key = Convert.ToString(rb.CommandParameter);
            if (!string.IsNullOrEmpty(key) && key != _currentPage) Navigate(key);
        }

        /// <summary>
        /// 翻页：新旧两页短暂重叠，按导航的上下方向同步滑动；
        /// 侧栏指示条同时滑到新位置。这样"我从哪里来、到哪里去"是连贯的。
        /// </summary>
        public void Navigate(string key)
        {
            if (string.IsNullOrEmpty(key)) key = "overview";
            int newIndex = NavIndex(key);
            int oldIndex = NavIndex(_currentPage);
            bool same = key == _currentPage && PageHost.Children.Count > 0;

            IPage page;
            if (!_pages.TryGetValue(key, out page))
            {
                page = CreatePage(key);
                if (page == null) return;
                _pages[key] = page;
            }

            var root = page.Root as FrameworkElement;
            var old = PageHost.Children.Count > 0 ? PageHost.Children[0] as FrameworkElement : null;

            if (!same && root != null)
            {
                _currentPage = key;
                // 快速连点时先把上一次还没退完的页面清掉，避免页面堆叠
                while (PageHost.Children.Count > 1)
                    PageHost.Children.RemoveAt(1);
                // 再快速点回正在淡出的旧页：先把它的父级清掉再重新加入，否则 WPF 会报
                // "Visual 已经是另一个 Visual 的子级" 直接崩掉
                if (PageHost.Children.Contains(root)) PageHost.Children.Remove(root);
                if (ReferenceEquals(old, root)) old = null;
                PageHost.Children.Add(root);
            }

            try { page.LoadData(_data); } catch (Exception e) { AppEnv.Log("页面加载失败 " + key + "：" + e); }
            try { page.ApplyPoll(_lastPoll); } catch { }

            if (!same && root != null)
            {
                if (old == null)
                {
                    Anim.PageIn(root, 0);
                }
                else
                {
                    int direction = newIndex >= oldIndex ? 1 : -1;
                    Anim.PageIn(root, direction);
                    Anim.PageOut(old, direction);
                    var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(230) };
                    timer.Tick += (s, e) =>
                    {
                        timer.Stop();
                        if (PageHost.Children.Contains(old)) PageHost.Children.Remove(old);
                        ScheduleFrostCollect();
                    };
                    timer.Start();
                }
            }

            foreach (var rb in Ui.FindAll<RadioButton>(NavList))
            {
                if (rb.GroupName != "nav") continue;
                bool on = Convert.ToString(rb.CommandParameter) == key;
                if (rb.IsChecked != on) rb.IsChecked = on;
            }
            Dispatcher.BeginInvoke(new Action(() => MoveNavIndicator(true)),
                System.Windows.Threading.DispatcherPriority.Loaded);
            StartFrostFollow(420);
            ScheduleFrostCollect();
            UpdateMaxGlyph();
        }

        /// <summary>让侧栏的 3px 指示条滑到当前导航项，位置按实际布局算（不写死行高）。</summary>
        private void MoveNavIndicator(bool animate)
        {
            if (NavIndicator == null || NavHost == null || NavList == null) return;
            RadioButton active = null;
            foreach (var rb in Ui.FindAll<RadioButton>(NavList))
            {
                if (rb.GroupName != "nav") continue;
                if (rb.IsChecked == true) { active = rb; break; }
            }
            if (active == null) return;
            if (active.ActualHeight <= 0)
            {
                // 页面刚切过去，导航项还没完成布局：等下一帧再放
                Dispatcher.BeginInvoke(new Action(() => MoveNavIndicator(animate)),
                    System.Windows.Threading.DispatcherPriority.Loaded);
                return;
            }
            var tt = NavIndicator.RenderTransform as TranslateTransform;
            if (tt == null) return;
            double y = active.TranslatePoint(new Point(0, 0), NavHost).Y
                       + Math.Max(0, (active.ActualHeight - NavIndicator.Height) / 2);
            if (!animate || !Anim.Enabled)
            {
                tt.BeginAnimation(TranslateTransform.YProperty, null);
                tt.Y = y;
                return;
            }
            Anim.Animate(tt, TranslateTransform.YProperty, tt.Y, y, Anim.Slow, Anim.Standard);
        }

        private IPage CreatePage(string key)
        {
            switch (key)
            {
                case "overview": return new OverviewPage(this);
                case "channels": return new ChannelsPage(this);
                case "notify": return new NotifyPage(this);
                case "settings": return new SettingsPage(this);
                case "personalize": return new PersonalizePage(this);
                case "startup": return new StartupPage(this);
                case "reports": return new ReportsPage(this);
                case "logs": return new LogsPage(this);
            }
            return null;
        }

        // ================================================================ 窗口按钮
        private void TitleDrag_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
        {
            if (e.ClickCount == 2)
            {
                ToggleMaximize();
                return;
            }
            if (e.ButtonState == MouseButtonState.Pressed)
            {
                try { DragMove(); } catch { }
            }
        }

        private void Min_Click(object sender, RoutedEventArgs e)
        {
            WindowState = WindowState.Minimized;
        }

        private void Max_Click(object sender, RoutedEventArgs e)
        {
            ToggleMaximize();
        }

        private void ToggleMaximize()
        {
            WindowState = WindowState == WindowState.Maximized
                ? WindowState.Normal : WindowState.Maximized;
        }

        private void UpdateMaxGlyph()
        {
            if (MaxBtn == null) return;
            MaxBtn.Content = WindowState == WindowState.Maximized ? "\uE923" : "\uE922";
            MaxBtn.ToolTip = WindowState == WindowState.Maximized ? "还原" : "最大化";
        }

        private void Close_Click(object sender, RoutedEventArgs e)
        {
            Close();
        }

        private void CloseLink_Click(object sender, RoutedEventArgs e)
        {
            Close();
        }

        private void Quit_Click(object sender, RoutedEventArgs e)
        {
            var btn = sender as Button;
            if (btn != null && !ConfirmThen(btn, "再点一次完全退出")) return;
            _quitting = true;
            SendAction("quit_all", new Dictionary<string, object>(), null, "正在退出…", 15000,
                r => Close());
        }

        private void Selfcheck_Click(object sender, RoutedEventArgs e)
        {
            SendAction("run_selfcheck", new Dictionary<string, object>(),
                "开始体检，结果会显示在「日志与诊断」", "正在体检…", 60000,
                r => Navigate("logs"));
        }

        // 双击确认（危险操作）
        private readonly Dictionary<Button, DateTime> _armed = new Dictionary<Button, DateTime>();
        private readonly Dictionary<Button, object> _armedContent = new Dictionary<Button, object>();

        public bool ConfirmThen(Button btn, string armedText)
        {
            DateTime at;
            if (_armed.TryGetValue(btn, out at) && (DateTime.Now - at).TotalSeconds < 3.5)
            {
                _armed.Remove(btn);
                object old;
                if (_armedContent.TryGetValue(btn, out old)) btn.Content = old;
                _armedContent.Remove(btn);
                return true;
            }
            _armed[btn] = DateTime.Now;
            _armedContent[btn] = btn.Content;
            btn.Content = armedText;
            var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(3.5) };
            timer.Tick += (s, e) =>
            {
                timer.Stop();
                object old;
                if (_armedContent.TryGetValue(btn, out old)) btn.Content = old;
                _armed.Remove(btn);
                _armedContent.Remove(btn);
            };
            timer.Start();
            return false;
        }

        // ================================================================ 状态显示
        public void UpdateWatchUI()        {
            bool online = _data.WatchOnline;
            bool enabled = _data.WatchEnabled;
            int interval = Json.Int(_data.Config, "watch_interval_minutes", 5);
            TbDot.Fill = (Brush)Application.Current.Resources[
                online ? "OkBrush" : (enabled ? "WarnBrush" : "LineStrongBrush")];
            if (online)
            {
                string activity = Json.Str(_data.Watch, "activity");
                string suffix = string.IsNullOrEmpty(activity) ? "后台正在运行" : "后台正在运行 · " + activity;
                TbStateText.Text = suffix + " · 每 " + interval + " 分钟";
            }
            else
            {
                // 只按真实心跳说话：不再因为"配置里开着"就一直显示"正在启动…"
                TbStateText.Text = _data.WatchStatusText;
            }
        }

        // ================================================================ 个性化
        private string _personalizeSig = "";

        /// <summary>背景图/参数被外部改过（上传、移除、恢复默认）时调用，强制下次 bootstrap 重新应用一次。</summary>
        public void InvalidatePersonalize()
        {
            _personalizeSig = "";
        }

        private void ApplyPersonalize()
        {
            if (AppEnv.PlainMode)
            {
                _personalizeSig = "plain";
                ResetTheme();
                return;
            }
            var p = _data.Personalize ?? new Dictionary<string, object>();
            string bgPath = Json.Str(p, "bg_path");
            if (string.IsNullOrEmpty(bgPath))
            {
                string rel = Json.Str(_data.Config, "personalize_bg");
                if (!string.IsNullOrEmpty(rel))
                    bgPath = Path.IsPathRooted(rel) ? rel : Path.Combine(AppEnv.DataDir, rel);
            }
            bool has = !string.IsNullOrEmpty(bgPath) && File.Exists(bgPath);
            if (!has)
            {
                _personalizeSig = "plain";
                ResetTheme();
                return;
            }
            // 参数没变就不重复应用：每次 bootstrap 都重抓壁纸快照 + 重算模糊会让窗口明显卡一下
            string sig = bgPath + "|" + Json.Dbl(p, "blur", 15) + "|"
                + Json.Dbl(p, "card_alpha", 70) + "|" + Json.Dbl(p, "scrim_alpha", 0)
                + "|" + Json.Str(p, "accent");
            try
            {
                // 同一个路径换了新图也要重新应用：把文件时间和大小也带上
                var fi = new FileInfo(bgPath);
                sig += "|" + fi.LastWriteTimeUtc.Ticks + "|" + fi.Length;
            }
            catch { }
            if (_personalized && sig == _personalizeSig) return;
            _personalizeSig = sig;
            BitmapSource bmp = null;
            try
            {
                var img = new BitmapImage();
                img.BeginInit();
                img.CacheOption = BitmapCacheOption.OnLoad;
                img.UriSource = new Uri(bgPath);
                img.EndInit();
                img.Freeze();
                bmp = img;
                Wallpaper.Source = bmp;
                Wallpaper.Visibility = Visibility.Visible;
            }
            catch (Exception e)
            {
                AppEnv.Log("加载背景图失败：" + e.Message);
                ResetTheme();
                return;
            }
            _personalized = true;
            _wallpaperDark = IsDarkWallpaper(bmp);
            double cardAlpha = Json.Dbl(p, "card_alpha", 70) / 100.0;
            double scrim = Json.Dbl(p, "scrim_alpha", 0) / 100.0;
            ApplyPalette(_wallpaperDark, cardAlpha);
            Scrim.Visibility = Visibility.Visible;
            Scrim.Fill = _wallpaperDark ? Brushes.Black : Brushes.White;
            ApplyScrim(scrim);
            ApplyAccent(Json.Str(p, "accent"));
            _wallpaperSharp = bmp;
            Frost.Visibility = Visibility.Visible;
            Frost.SetCorner(14);
            RebuildBlur(true);
            ScheduleFrostCollect();
        }

        private void ResetTheme()
        {
            _personalized = false;
            Wallpaper.Visibility = Visibility.Collapsed;
            Wallpaper.Source = null;
            Scrim.Visibility = Visibility.Collapsed;
            if (Frost != null)
            {
                Frost.Visibility = Visibility.Collapsed;
                Frost.ClearTargets();
            }
            _blurBase = null;
            _wallpaperSharp = null;
            ApplyPalette(false, 1.0);
            Brush bg = (Brush)Application.Current.Resources["BgBrush"];
            Titlebar.Background = bg;
            Sidebar.Background = bg;
            ActivityBar.Background = (Brush)Application.Current.Resources["SurfaceBrush"];
            ReaderPanel.Background = Brushes.White;
            ApplyAccent("");
        }

        private static bool IsDarkWallpaper(BitmapSource bmp)
        {
            try
            {
                var small = new TransformedBitmap(bmp, new ScaleTransform(24.0 / bmp.PixelWidth, 24.0 / bmp.PixelHeight));
                var conv = new FormatConvertedBitmap(small, PixelFormats.Bgra32, null, 0);
                int w = conv.PixelWidth, h = conv.PixelHeight, stride = w * 4;
                byte[] px = new byte[stride * h];
                conv.CopyPixels(px, stride, 0);
                double sum = 0;
                int n = 0;
                for (int i = 0; i < px.Length; i += 4)
                {
                    sum += 0.114 * px[i] + 0.587 * px[i + 1] + 0.299 * px[i + 2];
                    n++;
                }
                return n > 0 && (sum / n) < 118;
            }
            catch { return false; }
        }

        private static void SetBrush(string key, Color color)
        {
            var b = new SolidColorBrush(color);
            b.Freeze();
            Application.Current.Resources[key] = b;
        }

        private static Color Lighten(Color c, int amount)
        {
            return Color.FromRgb(
                (byte)Math.Min(255, c.R + amount),
                (byte)Math.Min(255, c.G + amount),
                (byte)Math.Min(255, c.B + amount));
        }

        /// <summary>
        /// 壁纸蒙层：用户滑杆 + 一个最低保底值。
        /// 没有保底时，亮色壁纸会把卡片外的标题和说明冲得看不清；
        /// 保底值很小，只压暗/提亮一点点，不会破坏毛玻璃的通透感。
        /// </summary>
        private void ApplyScrim(double scrim01)
        {
            if (Scrim == null) return;
            double floor = _wallpaperDark ? 0.30 : 0.10;
            double op = Math.Max(scrim01 * 0.75, floor);
            Scrim.Opacity = Math.Max(0, Math.Min(0.68, op));
        }

        private void ApplyPalette(bool dark, double cardAlpha)
        {
            byte a = (byte)Math.Max(0, Math.Min(255, cardAlpha * 255));
            if (!dark)
            {
                SetBrush("BgBrush", Color.FromRgb(0xF7, 0xF5, 0xF1));
                SetBrush("SurfaceBrush", Color.FromArgb(a, 255, 255, 255));
                SetBrush("Surface2Brush", Color.FromArgb((byte)Math.Min(255, a + 14), 251, 250, 247));
                SetBrush("LineBrush", Color.FromRgb(0xE8, 0xE4, 0xDC));
                SetBrush("LineStrongBrush", Color.FromRgb(0xD9, 0xD3, 0xC9));
                SetBrush("InkBrush", Color.FromRgb(0x1B, 0x1A, 0x18));
                SetBrush("Ink2Brush", Color.FromRgb(0x57, 0x53, 0x4C));
                SetBrush("Ink3Brush", Color.FromRgb(0x6F, 0x6A, 0x61));
                SetBrush("ChipBrush", Color.FromRgb(0xF0, 0xF1, 0xF4));
                SetBrush("HoverBrush", Color.FromRgb(0xF0, 0xED, 0xE7));
                SetBrush("PressBrush", Color.FromRgb(0xE4, 0xE0, 0xD8));
                SetBrush("OkBrush", Color.FromRgb(0x2A, 0x7A, 0x55));
                SetBrush("OkSoftBrush", Color.FromRgb(0xEA, 0xF5, 0xEE));
                SetBrush("BadBrush", Color.FromRgb(0xB3, 0x26, 0x1E));
                SetBrush("BadSoftBrush", Color.FromRgb(0xFB, 0xEC, 0xEA));
                SetBrush("WarnBrush", Color.FromRgb(0xA9, 0x64, 0x00));
                SetBrush("WarnSoftBrush", Color.FromRgb(0xFC, 0xF3, 0xE4));
                SetBrush("PrimaryBrush", Color.FromRgb(0x1B, 0x1A, 0x18));
                SetBrush("PrimaryTextBrush", Colors.White);
                SetBrush("PrimaryHoverBrush", Color.FromRgb(0x35, 0x32, 0x2D));
                SetBrush("NavActiveBrush", Colors.White);
                Brush glass = new SolidColorBrush(Color.FromArgb(
                    (byte)Math.Max(36, (int)(cardAlpha * 232)), 0xF7, 0xF5, 0xF1));
                glass.Freeze();
                Titlebar.Background = glass;
                Sidebar.Background = glass;
                ActivityBar.Background = glass;
                ReaderPanel.Background = Brushes.White;
            }
            else
            {
                SetBrush("BgBrush", Color.FromRgb(0x16, 0x16, 0x15));
                SetBrush("SurfaceBrush", Color.FromArgb(a, 20, 20, 18));
                SetBrush("Surface2Brush", Color.FromArgb((byte)Math.Min(255, a + 14), 30, 30, 27));
                SetBrush("LineBrush", Color.FromArgb(56, 255, 255, 255));
                SetBrush("LineStrongBrush", Color.FromArgb(88, 255, 255, 255));
                SetBrush("InkBrush", Color.FromRgb(0xF2, 0xEF, 0xE9));
                SetBrush("Ink2Brush", Color.FromRgb(0xD6, 0xD1, 0xC8));
                SetBrush("Ink3Brush", Color.FromRgb(0xA8, 0xA3, 0x9A));
                SetBrush("ChipBrush", Color.FromArgb(34, 255, 255, 255));
                SetBrush("HoverBrush", Color.FromArgb(34, 255, 255, 255));
                SetBrush("PressBrush", Color.FromArgb(54, 255, 255, 255));
                SetBrush("OkBrush", Color.FromRgb(0x7A, 0xC7, 0x9C));
                SetBrush("OkSoftBrush", Color.FromArgb(40, 0x7A, 0xC7, 0x9C));
                SetBrush("BadBrush", Color.FromRgb(0xE8, 0x8A, 0x82));
                SetBrush("BadSoftBrush", Color.FromArgb(40, 0xB3, 0x26, 0x1E));
                SetBrush("WarnBrush", Color.FromRgb(0xE0, 0xA7, 0x5C));
                SetBrush("WarnSoftBrush", Color.FromArgb(40, 0xA9, 0x64, 0x00));
                SetBrush("PrimaryBrush", Color.FromRgb(0xF2, 0xEF, 0xE9));
                SetBrush("PrimaryTextBrush", Color.FromRgb(0x1C, 0x1B, 0x19));
                SetBrush("PrimaryHoverBrush", Colors.White);
                SetBrush("NavActiveBrush", Color.FromArgb(52, 255, 255, 255));
                Brush glass = new SolidColorBrush(Color.FromArgb(
                    (byte)Math.Max(170, (int)(cardAlpha * 238)), 20, 20, 18));
                glass.Freeze();
                Titlebar.Background = glass;
                Sidebar.Background = glass;
                ActivityBar.Background = glass;
                ReaderPanel.Background = new SolidColorBrush(Color.FromRgb(0x1E, 0x1E, 0x1B));
            }
            this.Foreground = (Brush)Application.Current.Resources["InkBrush"];
        }

        /// <summary>
        /// 把壁纸模糊一份，交给 FrostLayer 裁进卡片/标题栏底下。
        /// 壁纸本体（Wallpaper）始终是清晰的那张图，只有透过卡片看到的部分是模糊的。
        /// </summary>
        private void RebuildBlur(bool forceBase)
        {
            if (!_personalized || _wallpaperSharp == null || ActualWidth < 10) return;
            try
            {
                double blur = Json.Dbl(_data.Personalize, "blur", 15);
                DpiScale dpi = VisualTreeHelper.GetDpi(this);
                if (forceBase || _blurBase == null)
                {
                    // 直接抓 Wallpaper 控件在屏幕上的渲染结果当模糊底图：
                    // 与清晰壁纸逐像素同源，DPI/缩放/宽高比都不再自己算，从根上避免错位。
                    UpdateLayout();
                    _blurBase = WallpaperBlur.BuildBase(Wallpaper,
                        ActualWidth, ActualHeight, dpi.DpiScaleX);
                }
                if (blur <= 0.5)
                {
                    // 模糊拉到 0：卡片底下不垫模糊图，就是清晰的壁纸
                    Frost.SetBackdrop(null);
                    return;
                }
                BitmapSource bmp = WallpaperBlur.BlurFrom(_blurBase, blur);
                if (bmp != null)
                {
                    Frost.SetBackdrop(bmp);
                    Frost.Refresh();
                }
            }
            catch (Exception e)
            {
                AppEnv.Log("壁纸模糊失败：\r\n" + e);
            }
        }

        private void OnWindowLayoutMoved()
        {
            if (!_personalized) return;
            RefreshFrostSoon();
            _blurTimer.Stop();
            _blurTimer.Start(); // 尺寸变了，模糊底图要按新尺寸重建
        }

        // ================================================================ 毛玻璃跟随
        public void RefreshFrostTargets() { ScheduleFrostCollect(); }
        public void RefreshFrostLayer() { RefreshFrostSoon(); }
        public void FollowFrost(int durationMs) { StartFrostFollow(durationMs); }

        /// <summary>布局完成后重新登记卡片目标（切页/列表重建后调用）。</summary>
        private void ScheduleFrostCollect()
        {
            if (!_personalized || _frostCollectPending) return;
            _frostCollectPending = true;
            Dispatcher.BeginInvoke(new Action(() =>
            {
                _frostCollectPending = false;
                CollectFrostTargets();
                Frost.Refresh();
            }), DispatcherPriority.Loaded);
        }

        private void OnAnyScrollChanged(object sender, ScrollChangedEventArgs e)
        {
            // 滚轮平滑滚动期间由 SmoothScroll.FrameTick 每帧刷新，这里再来一次就是同一帧画两遍
            if (SmoothScroll.IsAnimating) return;
            if (e.VerticalChange == 0 && e.HorizontalChange == 0
                && e.ExtentHeightChange == 0 && e.ExtentWidthChange == 0) return;
            RefreshFrostSoon();
        }

        /// <summary>同一帧里只重画一次毛玻璃。</summary>
        private void RefreshFrostSoon()
        {
            if (!_personalized || _frostScrollPending) return;
            _frostScrollPending = true;
            Dispatcher.BeginInvoke(new Action(() =>
            {
                _frostScrollPending = false;
                Frost.Refresh();
            }), DispatcherPriority.Render);
        }

        /// <summary>
        /// 翻页、底部活动条这类"整块在动"的动画不会触发 ScrollChanged；
        /// 按每一渲染帧跟随（CompositionTarget.Rendering，和画面同帧），动画结束自动停。
        /// </summary>
        private void StartFrostFollow(int durationMs)
        {
            if (!_personalized) return;
            _frostFollowUntil = DateTime.Now.AddMilliseconds(durationMs);
            if (_frostFollowFrame == null)
            {
                _frostFollowFrame = (s, e) =>
                {
                    Frost.Refresh();
                    if (DateTime.Now >= _frostFollowUntil)
                    {
                        CompositionTarget.Rendering -= _frostFollowFrame;
                        _frostFollowFrame = null;
                        Frost.Refresh();
                    }
                };
            }
            else
            {
                CompositionTarget.Rendering -= _frostFollowFrame;
            }
            CompositionTarget.Rendering += _frostFollowFrame;
        }

        /// <summary>滚轮平滑滚动的每一帧：卡片在动，毛玻璃补丁跟着重画。</summary>
        private void OnSmoothScrollFrame()
        {
            if (_personalized) Frost.Refresh();
        }

        private void CollectFrostTargets()
        {
            if (!_personalized) return;
            Frost.ClearTargets();
            Frost.AddTarget(Titlebar);
            Frost.AddTarget(Sidebar);
            Frost.AddTarget(ActivityBar);
            Style card = (Style)Application.Current.Resources["Card"];
            Style hover = (Style)Application.Current.Resources["CardHover"];
            foreach (var b in Ui.FindAll<Border>(Root))
            {
                if (b.Style == card || b.Style == hover) Frost.AddTarget(b);
            }
            Frost.Refresh();
        }
        private void ApplyAccent(string hex)
        {
            Color c;
            if (!TryColor(hex, out c)) c = Color.FromRgb(0x1F, 0x5A, 0xE0);
            if (_personalized && _wallpaperDark)
            {
                double lum = (0.299 * c.R + 0.587 * c.G + 0.114 * c.B) / 255.0;
                if (lum < 0.62)
                {
                    double k = Math.Min(3.2, 0.62 / Math.Max(0.18, lum));
                    c = Color.FromRgb(
                        (byte)Math.Min(255, c.R * k + 26),
                        (byte)Math.Min(255, c.G * k + 26),
                        (byte)Math.Min(255, c.B * k + 26));
                }
            }
            var accent = new SolidColorBrush(c);
            accent.Freeze();
            var soft = new SolidColorBrush(Color.FromArgb(28, c.R, c.G, c.B));
            soft.Freeze();
            var line = new SolidColorBrush(Color.FromArgb(70, c.R, c.G, c.B));
            line.Freeze();
            Application.Current.Resources["AccentBrush"] = accent;
            Application.Current.Resources["AccentSoftBrush"] = soft;
            Application.Current.Resources["AccentLineBrush"] = line;
        }

        private static bool TryColor(string hex, out Color color)
        {
            color = Colors.Black;
            if (string.IsNullOrEmpty(hex)) return false;
            try
            {
                color = (Color)ColorConverter.ConvertFromString(hex);
                return true;
            }
            catch { return false; }
        }

        // ================================================================ 原生报告阅读
        public async void OpenReport(string file, string title)
        {
            if (string.IsNullOrEmpty(file)) return;
            _readerFile = file;
            ReaderTitle.Text = string.IsNullOrEmpty(title) ? "报告" : title;
            Anim.OverlayIn(ReaderOverlay, ReaderPanel);
            ReaderHost.Document = ReportRenderer.Message("正在打开报告…");
            var resp = await CallService("report_doc", new Dictionary<string, object>
            {
                { "file", file }
            }, 25000);
            if (!UiClient.IsOk(resp))
            {
                ReaderHost.Document = ReportRenderer.Error("这份报告打不开：" + UiClient.ErrorOf(resp));
                return;
            }
            var result = UiClient.Result(resp);
            if (result == null || !Json.Bool(result, "ok", true))
            {
                string err = result != null ? Json.Str(result, "error", "读不出来") : "读不出来";
                ReaderHost.Document = ReportRenderer.Error("这份报告打不开：" + err);
                return;
            }
            string docTitle = Json.Str(result, "title");
            if (!string.IsNullOrEmpty(docTitle)) ReaderTitle.Text = docTitle;
            ReaderHost.Document = ReportRenderer.Build(Json.DictList(result, "blocks"));
            Anim.FadeSlideIn(ReaderHost, 240, 0, 6);
        }

        private void ReaderClose_Click(object sender, RoutedEventArgs e)
        {
            CloseReader();
        }

        private void ReaderBrowser_Click(object sender, RoutedEventArgs e)
        {
            OpenExternal("browser", HtmlSiblingOf(_readerFile));
        }

        /// <summary>报告是 HTML+MD 两份；浏览器打开时优先 html。</summary>
        public static string HtmlSiblingOf(string file)
        {
            if (string.IsNullOrEmpty(file)) return file;
            if (file.EndsWith(".md", StringComparison.OrdinalIgnoreCase))
            {
                string html = Path.ChangeExtension(file, ".html");
                if (File.Exists(html)) return html;
            }
            return file;
        }

        private void ReaderFolder_Click(object sender, RoutedEventArgs e)
        {
            OpenExternal("report_folder");
        }

        private void CloseReader()
        {
            if (ReaderOverlay.Visibility != Visibility.Visible) return;
            Anim.OverlayOut(ReaderOverlay, ReaderPanel, null);
        }

        private void OnPreviewKeyDown(object sender, KeyEventArgs e)
        {
            if (e.Key == Key.Escape)
            {
                if (ReaderOverlay.Visibility == Visibility.Visible)
                {
                    CloseReader();
                    e.Handled = true;
                }
            }
        }

        // ================================================================ 截图 / 拖动
        private void ScheduleShot()
        {
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(300) };
            timer.Tick += (s, e) => { timer.Stop(); MaybeFinishShot(); };
            timer.Start();
        }

        private void MaybeFinishShot()
        {
            if (_shotDone || string.IsNullOrEmpty(AppEnv.ShotPath)) return;
            App.Boot("shot: maybe, hasSchema=" + _data.Config.ContainsKey("schema")
                + " path=" + AppEnv.ShotPath);
            if (!_data.Config.ContainsKey("schema")) return;
            _shotDone = true;
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(AppEnv.ShotDelayMs) };
            timer.Tick += (s, e) =>
            {
                timer.Stop();
                if (AppEnv.ShotReader && _data.Reports.Count > 0 && ReaderOverlay.Visibility != Visibility.Visible)
                {
                    var r = _data.Reports[0];
                    OpenReport(Json.Str(r, "file"), Json.Str(r, "channel_name"));
                    var t2 = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(900) };
                    t2.Tick += (s2, e2) =>
                    {
                        t2.Stop();
                        try { CaptureShot(AppEnv.ShotPath); } catch (Exception ex) { AppEnv.Log("截图失败：" + ex); }
                        Close();
                    };
                    t2.Start();
                    return;
                }
                try { App.Boot("shot: capturing"); CaptureShot(AppEnv.ShotPath); App.Boot("shot: saved"); }
                catch (Exception ex) { App.Boot("shot failed: " + ex); AppEnv.Log("截图失败：" + ex); }
                Close();
            };
            timer.Start();
        }

        private void CaptureShot(string path)
        {
            if (!string.IsNullOrEmpty(AppEnv.ShotPage) && AppEnv.ShotPage != _currentPage)
                Navigate(AppEnv.ShotPage);
            UpdateLayout();
            if (AppEnv.ShotScroll != 0)
            {
                ApplyShotScroll(AppEnv.ShotScroll);
                UpdateLayout();
            }
            DpiScale dpi = VisualTreeHelper.GetDpi(this);
            int w = (int)Math.Round(ActualWidth * dpi.DpiScaleX);
            int h = (int)Math.Round(ActualHeight * dpi.DpiScaleY);
            var rtb = new RenderTargetBitmap(w, h, 96 * dpi.DpiScaleX, 96 * dpi.DpiScaleY,
                PixelFormats.Pbgra32);
            rtb.Render(Root);
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(rtb));
            using (var fs = File.Create(path)) enc.Save(fs);
            AppEnv.Mark("screenshot saved");
        }

        /// <summary>截图调试用：把当前页能滚的那块滚到指定偏移，顺便让毛玻璃刷新到正确位置。</summary>
        private void ApplyShotScroll(double offset)
        {
            if (PageHost.Children.Count == 0) return;
            var root = PageHost.Children[PageHost.Children.Count - 1] as DependencyObject;
            if (root == null) return;
            UpdateLayout();
            var target = root as ScrollViewer;
            if (target == null || target.ScrollableHeight <= 0)
            {
                target = null;
                double best = 0;
                foreach (var sv in Ui.FindAll<ScrollViewer>(root))
                {
                    if (sv.ScrollableHeight > best)
                    {
                        best = sv.ScrollableHeight;
                        target = sv;
                    }
                }
            }
            if (target == null) return;
            target.ScrollToVerticalOffset(offset);
            target.UpdateLayout();
            UpdateLayout();
        }

        // ================================================================ WM_GETMINMAXINFO
        private const int WM_GETMINMAXINFO = 0x0024;
        private const int MONITOR_DEFAULTTONEAREST = 2;

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct POINT { public int X; public int Y; }

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct MINMAXINFO
        {
            public POINT ptReserved;
            public POINT ptMaxSize;
            public POINT ptMaxPosition;
            public POINT ptMinTrackSize;
            public POINT ptMaxTrackSize;
        }

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct MONITORINFO
        {
            public int cbSize;
            public RECT rcMonitor;
            public RECT rcWork;
            public uint dwFlags;
        }

        [System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
        private struct RECT { public int Left; public int Top; public int Right; public int Bottom; }

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern IntPtr MonitorFromWindow(IntPtr hwnd, int flags);

        [System.Runtime.InteropServices.DllImport("user32.dll")]
        private static extern bool GetMonitorInfo(IntPtr monitor, ref MONITORINFO info);

        private IntPtr WndProc(IntPtr hwnd, int msg, IntPtr wParam, IntPtr lParam,
                               ref bool handled)
        {
            if (msg == WM_GETMINMAXINFO)
            {
                var info = (MINMAXINFO)System.Runtime.InteropServices.Marshal.PtrToStructure(
                    lParam, typeof(MINMAXINFO));
                double sx = 1, sy = 1;
                try { DpiScale d = VisualTreeHelper.GetDpi(this); sx = d.DpiScaleX; sy = d.DpiScaleY; }
                catch { }
                info.ptMinTrackSize.X = (int)Math.Round(MinWidth * sx);
                info.ptMinTrackSize.Y = (int)Math.Round(MinHeight * sy);
                IntPtr monitor = MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST);
                var mi = new MONITORINFO { cbSize = System.Runtime.InteropServices.Marshal.SizeOf(typeof(MONITORINFO)) };
                if (GetMonitorInfo(monitor, ref mi))
                {
                    info.ptMaxPosition.X = mi.rcWork.Left - mi.rcMonitor.Left;
                    info.ptMaxPosition.Y = mi.rcWork.Top - mi.rcMonitor.Top;
                    info.ptMaxSize.X = mi.rcWork.Right - mi.rcWork.Left;
                    info.ptMaxSize.Y = mi.rcWork.Bottom - mi.rcWork.Top;
                    System.Runtime.InteropServices.Marshal.StructureToPtr(info, lParam, false);
                }
                handled = true;
            }
            return IntPtr.Zero;
        }

        protected override void OnClosing(CancelEventArgs e)
        {
            _pollTimer.Stop();
            _saveTimer.Stop();
            _refreshTimer.Stop();
            if (_pendingSave.Count > 0)
            {
                FlushSaveBlocking(1800);
            }
            base.OnClosing(e);
        }
    }
}

























