using System;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace WinUpd
{
    internal static class Dwm
    {
        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr,
                                                        ref int value, int size);

        public static void RoundCorners(Window w)
        {
            try
            {
                var hwnd = new WindowInteropHelper(w).Handle;
                if (hwnd == IntPtr.Zero) return;
                int pref = 2; // DWMWCP_ROUND
                DwmSetWindowAttribute(hwnd, 33, ref pref, sizeof(int));
            }
            catch { }
        }
    }
}
