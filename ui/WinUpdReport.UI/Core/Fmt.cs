using System;
using System.Globalization;

namespace WinUpd
{
    public static class Fmt
    {
        public static string Mmdd(string iso)
        {
            if (string.IsNullOrEmpty(iso)) return "";
            DateTime dt;
            string s = iso.Length >= 10 ? iso.Substring(0, 10) : iso;
            if (DateTime.TryParse(s, CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out dt))
                return dt.ToString("MM-dd");
            return iso;
        }

        public static string Hhmm(string iso)
        {
            if (string.IsNullOrEmpty(iso)) return "";
            DateTime dt;
            if (DateTime.TryParse(iso, CultureInfo.InvariantCulture,
                    DateTimeStyles.None, out dt))
                return dt.ToString("HH:mm");
            return "";
        }

        public static string CompactName(string name)
        {
            if (string.IsNullOrEmpty(name)) return "";
            string s = name;
            if (s.StartsWith("Windows 11 ")) s = s.Substring("Windows 11 ".Length);
            else if (s.StartsWith("Windows 10 ")) s = s.Substring("Windows 10 ".Length);
            return s.Trim();
        }

        public static string Truncate(string s, int max)
        {
            if (string.IsNullOrEmpty(s)) return "";
            s = s.Replace("\r", " ").Replace("\n", " ");
            if (s.Length <= max) return s;
            return s.Substring(0, max) + "…";
        }
    }
}
