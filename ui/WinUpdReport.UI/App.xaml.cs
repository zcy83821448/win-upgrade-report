using System;
using System.Threading;
using System.Windows;
using System.Windows.Threading;

namespace WinUpd
{
    public partial class App : Application
    {
        public static UiClient Client;

        private Mutex _mutex;
        private EventWaitHandle _showEvent;
        private Thread _showThread;

        internal static void Boot(string text)
        {
            if (Environment.GetEnvironmentVariable("WINUPD_UI_DEBUG") != "1") return;
            string line = string.Format("{0:HH:mm:ss.fff} {1}\r\n", DateTime.Now, text);
            string[] dirs =
            {
                System.IO.Path.GetTempPath(),
                @"C:\Windows\Temp",
                System.IO.Path.GetDirectoryName(
                    System.Reflection.Assembly.GetExecutingAssembly().Location) ?? "."
            };
            foreach (string dir in dirs)
            {
                try
                {
                    System.IO.File.AppendAllText(
                        System.IO.Path.Combine(dir, "winupd_ui_boot.log"), line);
                }
                catch { }
            }
        }

        static App()
        {
            Boot("App static ctor");
        }

        public App()
        {
            Boot("App ctor");
        }
        protected override void OnStartup(StartupEventArgs e)
        {
            Boot("OnStartup enter");
            AppEnv.Init(e.Args);
            Boot("AppEnv.Init done, dataDir=" + AppEnv.DataDir);
            AppEnv.Mark("App.OnStartup");
            base.OnStartup(e);
            Boot("base.OnStartup done");

            DispatcherUnhandledException += OnDispatcherException;
            AppDomain.CurrentDomain.UnhandledException += (s, args) =>
            {
                Boot("未处理异常：" + args.ExceptionObject);
                AppEnv.Log("未处理异常：\r\n" + args.ExceptionObject);
            };

            bool created;
            _mutex = new Mutex(true, @"Local\WinUpdReportGui", out created);
            Boot("mutex created=" + created);
            if (!created)
            {
                // 已经有一个界面开着：只把它叫到前台，然后静默退出。
                try
                {
                    using (var ev = EventWaitHandle.OpenExisting(@"Local\WinUpdReportGuiShow"))
                        ev.Set();
                }
                catch { }
                Shutdown();
                return;
            }

            _showEvent = new EventWaitHandle(false, EventResetMode.AutoReset,
                @"Local\WinUpdReportGuiShow");
            _showThread = new Thread(ShowWatcher);
            _showThread.IsBackground = true;
            _showThread.Name = "show-watcher";
            _showThread.Start();

            if (!AppEnv.NoService)
            {
                Client = new UiClient();
                Client.Start();
            }

            Boot("creating MainWindow");
            MainWindow win;
            try { win = new MainWindow(Client); }
            catch (Exception ex) { Boot("MainWindow ctor failed: " + ex); throw; }
            MainWindow = win;
            Boot("before Show");
            win.Show();
            Boot("MainWindow shown");
            AppEnv.Mark("MainWindow.Show returned");
        }

        private void ShowWatcher()
        {
            while (true)
            {
                try
                {
                    if (_showEvent.WaitOne(1000))
                    {
                        Dispatcher.BeginInvoke(new Action(() =>
                        {
                            var win = MainWindow;
                            if (win == null) return;
                            if (win.WindowState == WindowState.Minimized)
                                win.WindowState = WindowState.Normal;
                            win.Activate();
                            win.Topmost = true;
                            win.Topmost = false;
                            win.Focus();
                        }));
                    }
                }
                catch { return; }
            }
        }

        private DateTime _lastUiErrorShown = DateTime.MinValue;

        private void OnDispatcherException(object sender, DispatcherUnhandledExceptionEventArgs e)
        {
            AppEnv.Log("界面异常：\r\n" + e.Exception);
            // 兜底：一处异常不能让整个界面死掉，所以仍然 Handled。
            // 但绝不能"默默吃掉"——以前界面出错时用户只看到半截页面、什么都没有提示。
            // 这里节流地弹一个错误提示（5 秒内只弹一次，避免异常连发时刷屏）。
            e.Handled = true;
            try
            {
                if ((DateTime.Now - _lastUiErrorShown).TotalSeconds < 5) return;
                _lastUiErrorShown = DateTime.Now;
                // Application.MainWindow 的静态类型是 Window，取到自家类型才能弹 toast
                var win = this.MainWindow as WinUpd.MainWindow;
                if (win == null) return;
                string msg = e.Exception != null ? e.Exception.Message : "";
                if (string.IsNullOrEmpty(msg)) msg = "未知错误";
                if (msg.Length > 110) msg = msg.Substring(0, 110) + "…";
                win.ToastErr("界面出了点小状况：" + msg + "（详情见 logs\\ui_error.log）");
            }
            catch { }
        }

        protected override void OnExit(ExitEventArgs e)
        {
            try { if (Client != null) Client.Dispose(); } catch { }
            try { if (_mutex != null) _mutex.ReleaseMutex(); } catch { }
            try { if (_mutex != null) _mutex.Dispose(); } catch { }
            try { if (_showEvent != null) _showEvent.Dispose(); } catch { }
            base.OnExit(e);
        }
    }
}






