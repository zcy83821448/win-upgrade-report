using System;
using System.Collections.Generic;
using System.IO;
using System.Windows;

namespace WinUpd
{
    /// <summary>界面当前的完整数据快照（bootstrap 的解析结果）。</summary>
    public sealed class AppData
    {
        public Dictionary<string, object> Config = new Dictionary<string, object>();
        public Dictionary<string, object> State = new Dictionary<string, object>();
        public Dictionary<string, object> App = new Dictionary<string, object>();
        public Dictionary<string, object> Watch = new Dictionary<string, object>();
        public Dictionary<string, object> Personalize = new Dictionary<string, object>();
        public Dictionary<string, object> Startup = new Dictionary<string, object>();
        public List<Dictionary<string, object>> Channels = new List<Dictionary<string, object>>();
        public List<Dictionary<string, object>> Reports = new List<Dictionary<string, object>>();
        public List<Dictionary<string, object>> TrayStyles = new List<Dictionary<string, object>>();
        public List<string> DetailOptions = new List<string>();
        public string TaskText = "";
        public string Now = "";
        public string LogPath = "";
        public string BaseDir = "";

        public bool WatchOnline
        {
            get { return Json.Bool(Watch, "online", false); }
        }

        /// <summary>配置里"应该开着后台监控"（只是意愿，不代表真的在跑）。</summary>
        public bool WatchEnabled
        {
            get { return Json.Bool(Config, "watch_enabled", false); }
        }

        /// <summary>
        /// 后台监控的一句话状态：以"水位"（哨兵心跳 online）为准。
        /// 以前用配置里的开关判断，哨兵崩了以后界面会永远显示"正在启动…"，
        /// 按钮写成"停止"、点下去其实是在启动。
        /// </summary>
        public string WatchStatusText
        {
            get
            {
                if (WatchOnline) return "后台正在运行";
                return WatchEnabled ? "后台监控没在运行" : "后台监控已关闭";
            }
        }

        /// <summary>按钮文案跟着真实状态走（和 gui.toggle_watch 的判断一致）。</summary>
        public string WatchToggleLabel
        {
            get { return WatchOnline ? "停止后台监控" : "开启后台监控"; }
        }

        public Dictionary<string, object> FindChannel(string id)
        {
            foreach (var c in Channels)
                if (Json.Str(c, "id") == id) return c;
            return null;
        }

        public Dictionary<string, object> ChannelState(string id)
        {
            var states = Json.Dict(State, "channels");
            if (states == null) return null;
            return Json.Dict(states, id);
        }

        public string ChannelName(string id)
        {
            var c = FindChannel(id);
            return c != null ? Json.Str(c, "name") : id;
        }

        public static AppData FromBootstrap(Dictionary<string, object> r)
        {
            var d = new AppData();
            if (r == null) return d;
            d.Config = Json.Dict(r, "config") ?? new Dictionary<string, object>();
            d.State = Json.Dict(r, "state") ?? new Dictionary<string, object>();
            d.App = Json.Dict(r, "app") ?? new Dictionary<string, object>();
            d.Watch = Json.Dict(r, "watch") ?? new Dictionary<string, object>();
            d.Personalize = Json.Dict(r, "personalize") ?? new Dictionary<string, object>();
            d.Startup = Json.Dict(r, "startup") ?? new Dictionary<string, object>();
            d.Channels = Json.DictList(r, "channels");
            d.Reports = Json.DictList(r, "reports");
            d.TrayStyles = Json.DictList(r, "tray_styles");
            d.DetailOptions = Json.StrList(r, "detail_options");
            d.TaskText = Json.Str(r, "task_text");
            d.Now = Json.Str(r, "now");
            d.LogPath = Json.Str(d.App, "log_path");
            d.BaseDir = Json.Str(d.App, "base_dir");
            return d;
        }

        public AppData Clone()
        {
            var d = new AppData
            {
                Config = new Dictionary<string, object>(Config),
                State = State,
                App = App,
                Watch = Watch,
                Personalize = Personalize,
                Startup = Startup,
                Channels = Channels,
                Reports = Reports,
                TrayStyles = TrayStyles,
                DetailOptions = DetailOptions,
                TaskText = TaskText,
                Now = Now,
                LogPath = LogPath,
                BaseDir = BaseDir
            };
            return d;
        }
    }

    public sealed class PollUpdate
    {
        public Dictionary<string, object> Raw = new Dictionary<string, object>();
        public Dictionary<string, object> Watch;
        public Dictionary<string, object> Live;
        public Dictionary<string, object> Startup;
        public List<Dictionary<string, object>> Events = new List<Dictionary<string, object>>();
        public string TaskText = "";
        public string Now = "";
        public bool WindowMaximized;

        public static PollUpdate From(Dictionary<string, object> r)
        {
            var u = new PollUpdate();
            if (r == null) return u;
            var res = Json.Dict(r, "result") ?? r;
            u.Raw = res;
            u.Watch = Json.Dict(res, "watch");
            u.Live = Json.Dict(res, "live");
            u.Startup = Json.Dict(res, "startup");
            u.Events = Json.DictList(res, "events");
            u.TaskText = Json.Str(res, "task_text");
            u.Now = Json.Str(res, "now");
            var win = Json.Dict(res, "window");
            u.WindowMaximized = Json.Bool(win, "maximized", false);
            return u;
        }
    }

    public interface IPage
    {
        string Key { get; }
        string Title { get; }
        FrameworkElement Root { get; }
        void LoadData(AppData data);
        void ApplyPoll(PollUpdate poll);
    }
}

