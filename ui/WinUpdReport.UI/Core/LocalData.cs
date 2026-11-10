using System;
using System.Collections.Generic;
using System.IO;
using System.Text;

namespace WinUpd
{
    /// <summary>首屏直读：不启动 Python 也能立刻显示真实数据（只读快照）。</summary>
    public sealed class AppSnapshot
    {
        public Dictionary<string, object> Config = new Dictionary<string, object>();
        public Dictionary<string, object> State = new Dictionary<string, object>();
        public string DataDir = "";
        public string Error = "";
    }

    public static class LocalData
    {
        public static AppSnapshot Load()
        {
            var snap = new AppSnapshot { DataDir = AppEnv.DataDir };
            try
            {
                snap.Config = ReadJson(Path.Combine(AppEnv.DataDir, "config.json"));
                snap.State = ReadJson(Path.Combine(AppEnv.DataDir, "state.json"));
            }
            catch (Exception e)
            {
                snap.Error = e.Message;
            }
            return snap;
        }

        public static Dictionary<string, object> ReadJson(string path)
        {
            if (!File.Exists(path)) return new Dictionary<string, object>();
            string text = File.ReadAllText(path, Encoding.UTF8);
            if (string.IsNullOrWhiteSpace(text)) return new Dictionary<string, object>();
            try
            {
                var d = Json.Deserialize(text);
                return d ?? new Dictionary<string, object>();
            }
            catch
            {
                return new Dictionary<string, object>();
            }
        }
    }
}
