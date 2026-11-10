using System;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace WinUpd
{
    /// <summary>从图片取平均色，并调整到适合白字按钮的深度（与旧界面算法同目标）。</summary>
    public static class AccentUtil
    {
        public static Color Average(BitmapSource source)
        {
            try
            {
                var converted = new FormatConvertedBitmap(source, PixelFormats.Bgra32, null, 0);
                int w = converted.PixelWidth, h = converted.PixelHeight;
                int stride = w * 4;
                byte[] pixels = new byte[stride * h];
                converted.CopyPixels(pixels, stride, 0);
                long r = 0, g = 0, b = 0, n = 0;
                int step = Math.Max(1, Math.Max(w, h) / 96);
                for (int y = 0; y < h; y += step)
                {
                    int row = y * stride;
                    for (int x = 0; x < w; x += step)
                    {
                        int i = row + x * 4;
                        b += pixels[i];
                        g += pixels[i + 1];
                        r += pixels[i + 2];
                        n++;
                    }
                }
                if (n == 0) return Color.FromRgb(0x1F, 0x5A, 0xE0);
                return Color.FromRgb((byte)(r / n), (byte)(g / n), (byte)(b / n));
            }
            catch
            {
                return Color.FromRgb(0x1F, 0x5A, 0xE0);
            }
        }

        public static Color AdjustForReadability(Color c)
        {
            double lum = 0.299 * c.R + 0.587 * c.G + 0.114 * c.B;
            // 白字按钮：把平均色压到 95~135 的亮度区间
            double target = lum > 135 ? 118 : (lum < 85 ? 110 : lum);
            double k = target / Math.Max(1.0, lum);
            int r = (int)Math.Round(c.R * k);
            int g = (int)Math.Round(c.G * k);
            int b = (int)Math.Round(c.B * k);
            r = Math.Min(255, Math.Max(0, r));
            g = Math.Min(255, Math.Max(0, g));
            b = Math.Min(255, Math.Max(0, b));
            return Color.FromRgb((byte)r, (byte)g, (byte)b);
        }

        public static string ToHex(Color c)
        {
            return string.Format("#{0:X2}{1:X2}{2:X2}", c.R, c.G, c.B);
        }

        public static string EncodePngDataUrl(BitmapSource bmp)
        {
            var enc = new PngBitmapEncoder();
            enc.Frames.Add(BitmapFrame.Create(bmp));
            using (var ms = new System.IO.MemoryStream())
            {
                enc.Save(ms);
                return "data:image/png;base64," + Convert.ToBase64String(ms.ToArray());
            }
        }

        /// <summary>
        /// 背景图用 JPEG 回传（比 PNG 小一个数量级，管道和保存都更快、更不容易卡住）。
        /// 有透明通道也没关系：背景图本来就是铺满窗口的照片类图片。
        /// </summary>
        public static string EncodeJpegDataUrl(BitmapSource bmp, int quality = 90)
        {
            BitmapSource src = bmp;
            if (bmp.Format != PixelFormats.Bgr24 && bmp.Format != PixelFormats.Bgr32)
                src = new FormatConvertedBitmap(bmp, PixelFormats.Bgr24, null, 0);
            var enc = new JpegBitmapEncoder { QualityLevel = quality };
            enc.Frames.Add(BitmapFrame.Create(src));
            using (var ms = new System.IO.MemoryStream())
            {
                enc.Save(ms);
                return "data:image/jpeg;base64," + Convert.ToBase64String(ms.ToArray());
            }
        }
    }
}
