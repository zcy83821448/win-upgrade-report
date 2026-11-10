using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace WinUpd
{
    /// <summary>不依赖 System.Web 的极简 JSON（.NET Framework WPF 构建里引用 System.Web 会把 XAML 编译器搞挂）。</summary>
    public static class Json
    {
        // ============================================================ 解析
        public static Dictionary<string, object> Deserialize(string text)
        {
            object v = ParseValue(text, 0, out _);
            var d = v as Dictionary<string, object>;
            return d ?? new Dictionary<string, object>();
        }

        public static object ParseValue(string s, int i, out int next)
        {
            SkipWs(s, ref i);
            if (i >= s.Length) { next = i; return null; }
            char c = s[i];
            if (c == '{') return ParseObject(s, ref i, out next);
            if (c == '[') return ParseArray(s, ref i, out next);
            if (c == '"') return ParseString(s, ref i, out next);
            if (c == 't') { Expect(s, i, "true"); next = i + 4; return true; }
            if (c == 'f') { Expect(s, i, "false"); next = i + 5; return false; }
            if (c == 'n') { Expect(s, i, "null"); next = i + 4; return null; }
            return ParseNumber(s, ref i, out next);
        }

        private static void Expect(string s, int i, string word)
        {
            if (i + word.Length > s.Length
                || string.CompareOrdinal(s, i, word, 0, word.Length) != 0)
                throw new FormatException("JSON 格式错误");
        }

        private static void SkipWs(string s, ref int i)
        {
            while (i < s.Length)
            {
                char c = s[i];
                if (c == ' ' || c == '\t' || c == '\r' || c == '\n') i++;
                else break;
            }
        }

        private static Dictionary<string, object> ParseObject(string s, ref int i, out int next)
        {
            var d = new Dictionary<string, object>();
            i++; // {
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == '}') { next = i + 1; return d; }
            while (i < s.Length)
            {
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != '"') throw new FormatException("JSON 对象键错误");
                string key = ParseString(s, ref i, out _);
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("JSON 对象缺冒号");
                i++;
                object val = ParseValue(s, i, out i);
                d[key] = val;
                SkipWs(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == '}') { next = i + 1; return d; }
                throw new FormatException("JSON 对象格式错误");
            }
            next = i;
            return d;
        }

        private static List<object> ParseArray(string s, ref int i, out int next)
        {
            var list = new List<object>();
            i++; // [
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == ']') { next = i + 1; return list; }
            while (i < s.Length)
            {
                object val = ParseValue(s, i, out i);
                list.Add(val);
                SkipWs(s, ref i);
                if (i < s.Length && s[i] == ',') { i++; continue; }
                if (i < s.Length && s[i] == ']') { next = i + 1; return list; }
                throw new FormatException("JSON 数组格式错误");
            }
            next = i;
            return list;
        }

        private static string ParseString(string s, ref int i, out int next)
        {
            var sb = new StringBuilder();
            i++; // "
            while (i < s.Length)
            {
                char c = s[i++];
                if (c == '"') { next = i; return sb.ToString(); }
                if (c == '\\')
                {
                    if (i >= s.Length) break;
                    char e = s[i++];
                    switch (e)
                    {
                        case '"': sb.Append('"'); break;
                        case '\\': sb.Append('\\'); break;
                        case '/': sb.Append('/'); break;
                        case 'b': sb.Append('\b'); break;
                        case 'f': sb.Append('\f'); break;
                        case 'n': sb.Append('\n'); break;
                        case 'r': sb.Append('\r'); break;
                        case 't': sb.Append('\t'); break;
                        case 'u':
                            if (i + 4 <= s.Length)
                            {
                                string hex = s.Substring(i, 4);
                                i += 4;
                                int code;
                                if (int.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out code))
                                    sb.Append((char)code);
                            }
                            break;
                        default: sb.Append(e); break;
                    }
                }
                else
                {
                    sb.Append(c);
                }
            }
            next = i;
            return sb.ToString();
        }

        private static object ParseNumber(string s, ref int i, out int next)
        {
            int start = i;
            while (i < s.Length)
            {
                char c = s[i];
                if ((c >= '0' && c <= '9') || c == '-' || c == '+' || c == '.' || c == 'e' || c == 'E') i++;
                else break;
            }
            string num = s.Substring(start, i - start);
            next = i;
            double d;
            if (double.TryParse(num, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
            {
                if (d == Math.Floor(d) && Math.Abs(d) < 9e15)
                    return (long)d;
                return d;
            }
            return 0L;
        }

        // ============================================================ 序列化
        public static string Serialize(object obj)
        {
            var sb = new StringBuilder();
            WriteValue(sb, obj);
            return sb.ToString();
        }

        private static void WriteValue(StringBuilder sb, object v)
        {
            if (v == null) { sb.Append("null"); return; }
            string s = v as string;
            if (s != null) { WriteString(sb, s); return; }
            if (v is bool) { sb.Append((bool)v ? "true" : "false"); return; }
            if (v is int || v is long || v is short || v is byte)
            {
                sb.Append(Convert.ToString(v, CultureInfo.InvariantCulture));
                return;
            }
            if (v is float || v is double || v is decimal)
            {
                double d = Convert.ToDouble(v, CultureInfo.InvariantCulture);
                sb.Append(d.ToString("R", CultureInfo.InvariantCulture));
                return;
            }
            var dict = v as IDictionary<string, object>;
            if (dict != null)
            {
                sb.Append('{');
                bool first = true;
                foreach (var kv in dict)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    WriteString(sb, kv.Key);
                    sb.Append(':');
                    WriteValue(sb, kv.Value);
                }
                sb.Append('}');
                return;
            }
            var dict2 = v as IDictionary;
            if (dict2 != null)
            {
                sb.Append('{');
                bool first = true;
                foreach (DictionaryEntry kv in dict2)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    WriteString(sb, Convert.ToString(kv.Key));
                    sb.Append(':');
                    WriteValue(sb, kv.Value);
                }
                sb.Append('}');
                return;
            }
            var en = v as IEnumerable;
            if (en != null)
            {
                sb.Append('[');
                bool first = true;
                foreach (object o in en)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    WriteValue(sb, o);
                }
                sb.Append(']');
                return;
            }
            sb.Append('"');
            sb.Append(Convert.ToString(v).Replace("\\", "\\\\").Replace("\"", "\\\""));
            sb.Append('"');
        }

        private static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u" + ((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }

        // ============================================================ 取值
        public static string Str(IDictionary<string, object> d, string key,
                                 string fallback = "")
        {
            if (d == null) return fallback;
            object v;
            if (!d.TryGetValue(key, out v) || v == null) return fallback;
            return Convert.ToString(v, CultureInfo.InvariantCulture) ?? fallback;
        }

        public static int Int(IDictionary<string, object> d, string key, int fallback = 0)
        {
            if (d == null) return fallback;
            object v;
            if (!d.TryGetValue(key, out v) || v == null) return fallback;
            try { return Convert.ToInt32(v, CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        public static long Long(IDictionary<string, object> d, string key, long fallback = 0)
        {
            if (d == null) return fallback;
            object v;
            if (!d.TryGetValue(key, out v) || v == null) return fallback;
            try { return Convert.ToInt64(v, CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        public static double Dbl(IDictionary<string, object> d, string key,
                                 double fallback = 0)
        {
            if (d == null) return fallback;
            object v;
            if (!d.TryGetValue(key, out v) || v == null) return fallback;
            try { return Convert.ToDouble(v, CultureInfo.InvariantCulture); }
            catch { return fallback; }
        }

        public static bool Bool(IDictionary<string, object> d, string key,
                                bool fallback = false)
        {
            if (d == null) return fallback;
            object v;
            if (!d.TryGetValue(key, out v) || v == null) return fallback;
            if (v is bool) return (bool)v;
            string s = Convert.ToString(v, CultureInfo.InvariantCulture);
            return s == "1" || string.Equals(s, "true", StringComparison.OrdinalIgnoreCase);
        }

        public static Dictionary<string, object> Dict(IDictionary<string, object> d,
                                                      string key)
        {
            if (d == null) return null;
            object v;
            if (!d.TryGetValue(key, out v)) return null;
            return v as Dictionary<string, object>;
        }

        public static List<Dictionary<string, object>> DictList(IDictionary<string, object> d,
                                                                string key)
        {
            var outList = new List<Dictionary<string, object>>();
            if (d == null) return outList;
            object v;
            if (!d.TryGetValue(key, out v) || v == null) return outList;
            IEnumerable items = v as IEnumerable;
            if (items == null || v is string) return outList;
            foreach (object it in items)
            {
                var dd = it as Dictionary<string, object>;
                if (dd != null) outList.Add(dd);
            }
            return outList;
        }

        public static List<string> StrList(IDictionary<string, object> d, string key)
        {
            var list = new List<string>();
            if (d == null) return list;
            object v;
            if (!d.TryGetValue(key, out v) || v == null) return list;
            IEnumerable items = v as IEnumerable;
            if (items == null || v is string) return list;
            foreach (object it in items)
            {
                if (it != null) list.Add(Convert.ToString(it, CultureInfo.InvariantCulture));
            }
            return list;
        }

        public static object Get(IDictionary<string, object> d, string key)
        {
            if (d == null) return null;
            object v;
            return d.TryGetValue(key, out v) ? v : null;
        }

        public static void Set(IDictionary<string, object> d, string key, object value)
        {
            if (d == null) return;
            d[key] = value;
        }
    }
}
