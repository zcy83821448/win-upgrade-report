using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace WinUpd
{
    /// <summary>进程级环境：数据目录、管道名、启动参数、服务进程命令行。</summary>
    public static class AppEnv
    {
        public static string DataDir { get; private set; }
        public static string PipeName { get; private set; }
        public static string RepoDir { get; private set; }
        public static string InitialPage = "overview";
        public static string ShotPath = "";
        public static string ShotPage = "";
        public static int ShotDelayMs = 1200;
        public static double ShotScroll = 0;
        public static bool NoService = false;
        public static bool PlainMode = false;
        public static bool ShotReader = false;
        public static int WindowW = 1200;
        public static int WindowH = 800;
        public static bool Maximized = false;
        public static string[] Args = new string[0];

        private static string _explicitDataDir = "";
        private static string _explicitService = "";

        public static void Init(string[] argv)
        {
            Args = argv ?? new string[0];
            for (int i = 0; i < Args.Length; i++)
            {
                string a = Args[i];
                switch (a)
                {
                    case "--data-dir":
                        _explicitDataDir = Next(ref i);
                        break;
                    case "--service":
                        _explicitService = Next(ref i);
                        break;
                    case "--page":
                        InitialPage = Next(ref i);
                        break;
                    case "--shot":
                        ShotPath = Next(ref i);
                        break;
                    case "--shot-page":
                        ShotPage = Next(ref i);
                        break;
                    case "--shot-delay":
                        int d;
                        int.TryParse(Next(ref i), out d);
                        if (d > 0) ShotDelayMs = d;
                        break;
                    case "--shot-scroll":
                        double scroll;
                        double.TryParse(Next(ref i), out scroll);
                        ShotScroll = scroll;
                        break;
                    case "--no-service":
                        NoService = true;
                        break;
                    case "--plain":
                        PlainMode = true;
                        break;
                    case "--shot-reader":
                        ShotReader = true;
                        break;
                    case "--size":
                        string size = Next(ref i);
                        string[] parts = (size ?? "").Split('x');
                        int ww, hh;
                        if (parts.Length == 2 && int.TryParse(parts[0], out ww)
                            && int.TryParse(parts[1], out hh))
                        {
                            WindowW = ww;
                            WindowH = hh;
                        }
                        break;
                    case "--maximized":
                        Maximized = true;
                        break;
                }
            }
            RepoDir = FindRepoDir();
            DataDir = FindDataDir();
            PipeName = ComputePipeName();
            if (!string.IsNullOrEmpty(ShotPage)) InitialPage = ShotPage;
        }

        private static string Next(ref int i)
        {
            if (i + 1 < Args.Length) return Args[++i];
            return "";
        }

        public static bool Has(string flag)
        {
            return Args.Any(x => string.Equals(x, flag, StringComparison.OrdinalIgnoreCase));
        }

        private static string ExeDir
        {
            get { return Path.GetDirectoryName(
                System.Reflection.Assembly.GetExecutingAssembly().Location); }
        }

        private static string FindDataDir()
        {
            if (!string.IsNullOrEmpty(_explicitDataDir))
                return Path.GetFullPath(_explicitDataDir);
            string dir = ExeDir;
            for (int depth = 0; depth < 6 && !string.IsNullOrEmpty(dir); depth++)
            {
                if (File.Exists(Path.Combine(dir, "config.json")))
                    return dir;
                dir = Path.GetDirectoryName(dir);
            }
            return ExeDir;
        }

        private static string FindRepoDir()
        {
            string dir = ExeDir;
            for (int depth = 0; depth < 7 && !string.IsNullOrEmpty(dir); depth++)
            {
                if (File.Exists(Path.Combine(dir, "ui_service.py")))
                    return dir;
                dir = Path.GetDirectoryName(dir);
            }
            return null;
        }

        public static string ComputePipeName()
        {
            string user = Environment.UserName;
            string raw = user + "|" + DataDir;
            using (var sha1 = SHA1.Create())
            {
                byte[] hash = sha1.ComputeHash(Encoding.UTF8.GetBytes(raw));
                var sb = new StringBuilder(hash.Length * 2);
                foreach (byte b in hash) sb.Append(b.ToString("x2"));
                return "winupdreport-ui-" + sb.ToString(0, 10);
            }
        }

        public static ProcessStartInfo BuildServiceStartInfo()
        {
            var psi = new ProcessStartInfo();
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            psi.WorkingDirectory = DataDir;
            string pkgExe = Path.Combine(DataDir, "win升级报告.exe");
            if (!string.IsNullOrEmpty(_explicitService))
            {
                string svc = Path.GetFullPath(_explicitService);
                if (svc.EndsWith(".py", StringComparison.OrdinalIgnoreCase))
                {
                    psi.FileName = FindPython(true);
                    psi.Arguments = Quote(svc) + " --pipe " + Quote(PipeName)
                                    + " --data-dir " + Quote(DataDir);
                }
                else
                {
                    psi.FileName = svc;
                    psi.Arguments = "--ui-service --pipe " + Quote(PipeName);
                }
                return psi;
            }
            // 开发环境优先用源码服务（repo 里有 ui_service.py），发布版用同目录的 exe。
            string exePath = System.Reflection.Assembly.GetExecutingAssembly().Location;
            bool devBuild = exePath.IndexOf(@"\ui\WinUpdReport.UI\bin\",
                StringComparison.OrdinalIgnoreCase) >= 0;
            if (devBuild && !string.IsNullOrEmpty(RepoDir)
                && File.Exists(Path.Combine(RepoDir, "ui_service.py")))
            {
                psi.FileName = FindPython(true);
                psi.Arguments = Quote(Path.Combine(RepoDir, "ui_service.py"))
                                + " --pipe " + Quote(PipeName)
                                + " --data-dir " + Quote(DataDir);
                return psi;
            }
            if (File.Exists(pkgExe))
            {
                psi.FileName = pkgExe;
                psi.Arguments = "--ui-service --pipe " + Quote(PipeName);
                return psi;
            }
            throw new FileNotFoundException(
                "找不到后台服务程序（win升级报告.exe / ui_service.py）。");
        }

        public static string ServiceDescription()
        {
            try
            {
                ProcessStartInfo psi = BuildServiceStartInfo();
                return psi.FileName + " " + psi.Arguments;
            }
            catch (Exception e)
            {
                return "（未找到：" + e.Message + "）";
            }
        }

        private static string FindPython(bool preferWindowless)
        {
            string env = Environment.GetEnvironmentVariable("WINUPD_PYTHONW");
            if (!string.IsNullOrEmpty(env) && File.Exists(env)) return env;
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            string[] names = preferWindowless
                ? new[] { "pythonw.exe", "python.exe" }
                : new[] { "python.exe" };
            foreach (string n in names)
            {
                foreach (string part in path.Split(';'))
                {
                    if (string.IsNullOrWhiteSpace(part)) continue;
                    try
                    {
                        string cand = Path.Combine(part.Trim(), n);
                        if (File.Exists(cand)) return cand;
                    }
                    catch { }
                }
            }
            string known = @"D:\python\pythonw.exe";
            if (File.Exists(known)) return known;
            return preferWindowless ? "pythonw.exe" : "python.exe";
        }

        public static string Quote(string s)
        {
            if (s == null) s = "";
            return "\"" + s.Replace("\"", "\\\"") + "\"";
        }

        public static string LogPath
        {
            get { return Path.Combine(DataDir, "logs", "ui_error.log"); }
        }

        public static void Log(string text)
        {
            try
            {
                string dir = Path.GetDirectoryName(LogPath);
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                File.AppendAllText(LogPath,
                    string.Format("[{0:yyyy-MM-dd HH:mm:ss}] {1}\r\n",
                        DateTime.Now, text), Encoding.UTF8);
            }
            catch { }
        }

        private static readonly Stopwatch Clock = Stopwatch.StartNew();
        private static readonly DateTime StartedAt = DateTime.Now;

        /// <summary>启动耗时埋点：设环境变量 WINUPD_UI_TIMING=1 后写 logs/ui_timing.log。</summary>
        public static void Mark(string name)
        {
            if (Environment.GetEnvironmentVariable("WINUPD_UI_TIMING") != "1") return;
            try
            {
                double ms;
                try { ms = (DateTime.Now - Process.GetCurrentProcess().StartTime).TotalMilliseconds; }
                catch { ms = Clock.Elapsed.TotalMilliseconds; }
                string dir = Path.Combine(DataDir, "logs");
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);
                File.AppendAllText(Path.Combine(dir, "ui_timing.log"),
                    string.Format("{0,8:F0} ms  {1}\r\n", ms, name), Encoding.UTF8);
            }
            catch { }
        }
    }
}





