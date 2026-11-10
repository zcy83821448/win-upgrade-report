using System;
using System.Windows;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace WinUpd
{
    /// <summary>预先缩小的壁纸底图（窗口大小/图片变化时才重建，模糊滑杆拖动时只重算模糊）。</summary>
    public sealed class BlurBase
    {
        public int Width;
        public int Height;
        public byte[] Pixels;
        public double DpiScale;
        internal double ToPixelFactor { get { return 1.0 / 3.0; } }
    }

    /// <summary>
    /// 壁纸模糊（纯 CPU box blur）。
    ///
    /// 现在整个窗口只有这一张模糊壁纸：不再是"每张卡片底下单独画一块"。
    /// 好处是滚动、翻页、卡片出现/消失都不需要任何跟随或重绘，
    /// 卡片本身就是半透明白纱，直接叠在固定的模糊背景上 —— 从结构上消除了
    /// "卡片走了、色块没跟上"和"逐帧重画拖低帧率"这两类问题。
    /// </summary>
    public static class WallpaperBlur
    {
        /// <summary>
        /// 直接从「屏幕上那张壁纸」抓一张快照当模糊底图。
        ///
        /// 这是最不容易错位的做法：不再自己算 UniformToFill/DPI/缩放，
        /// 而是把 Wallpaper 这个控件当前渲染出来的像素原样抓下来，
        /// 与用户看到的清晰壁纸逐像素同源；之后再降采样、box blur。
        /// </summary>
        public static BlurBase BuildBase(Visual wallpaperVisual, double widthDip,
            double heightDip, double dpiScale)
        {
            try
            {
                int w = Math.Max(2, (int)Math.Round(widthDip * dpiScale));
                int h = Math.Max(2, (int)Math.Round(heightDip * dpiScale));
                var rtb = new RenderTargetBitmap(w, h, 96 * dpiScale, 96 * dpiScale,
                    PixelFormats.Pbgra32);
                rtb.Render(wallpaperVisual);
                return Downsample(rtb, dpiScale);
            }
            catch
            {
                return null;
            }
        }

        private static BlurBase Downsample(BitmapSource full, double dpiScale)
        {
            int w = full.PixelWidth, h = full.PixelHeight;
            int factor = 3;
            int bw = Math.Max(2, w / factor);
            int bh = Math.Max(2, h / factor);
            var scaled = new TransformedBitmap(full,
                new ScaleTransform((double)bw / w, (double)bh / h));
            var converted = new FormatConvertedBitmap(scaled, PixelFormats.Bgra32, null, 0);
            var bas = new BlurBase
            {
                Width = bw,
                Height = bh,
                DpiScale = dpiScale,
                Pixels = new byte[bw * bh * 4]
            };
            converted.CopyPixels(bas.Pixels, bw * 4, 0);
            return bas;
        }

        public static BlurBase BuildBase(BitmapSource source, double widthDip,
            double heightDip, double dpiScale)
        {
            try
            {
                int w = Math.Max(2, (int)Math.Round(widthDip * dpiScale));
                int h = Math.Max(2, (int)Math.Round(heightDip * dpiScale));
                var visual = new DrawingVisual();
                using (var dc = visual.RenderOpen())
                {
                    // 注意：视觉里的坐标是 DIP，不是像素。
                    // 壁纸以 UniformToFill 铺窗口，这里必须用同样的 DIP 尺寸去画，
                    // 否则在 125% / 150% 缩放下模糊图和清晰壁纸会整体错位。
                    double srcDpiX = source.DpiX > 0 ? source.DpiX : 96.0;
                    double srcDpiY = source.DpiY > 0 ? source.DpiY : 96.0;
                    double sw = source.PixelWidth * 96.0 / srcDpiX;
                    double sh = source.PixelHeight * 96.0 / srcDpiY;
                    double scale = Math.Max(widthDip / sw, heightDip / sh);
                    double dw = sw * scale, dh = sh * scale;
                    dc.DrawImage(source, new Rect((widthDip - dw) / 2,
                        (heightDip - dh) / 2, dw, dh));
                }
                var rtb = new RenderTargetBitmap(w, h, 96 * dpiScale, 96 * dpiScale,
                    PixelFormats.Pbgra32);
                rtb.Render(visual);
                return Downsample(rtb, dpiScale);
            }
            catch
            {
                return null;
            }
        }

        public static BitmapSource BlurFrom(BlurBase bas, double blurDip)
        {
            try
            {
                if (bas == null) return null;
                int stride = bas.Width * 4;
                byte[] pixels = (byte[])bas.Pixels.Clone();
                int radius = (int)Math.Round(Math.Max(0, blurDip) * bas.DpiScale / 3.0);
                if (radius > 0)
                {
                    BoxBlur(pixels, bas.Width, bas.Height, stride, radius);
                    BoxBlur(pixels, bas.Width, bas.Height, stride, Math.Max(1, radius / 2));
                }
                var result = BitmapSource.Create(bas.Width, bas.Height,
                    96 * bas.DpiScale, 96 * bas.DpiScale, PixelFormats.Bgra32, null,
                    pixels, stride);
                result.Freeze();
                return result;
            }
            catch
            {
                return null;
            }
        }

        private static int Clamp(int v, int lo, int hi)
        {
            return v < lo ? lo : (v > hi ? hi : v);
        }

        private static void BoxBlur(byte[] pixels, int w, int h, int stride, int r)
        {
            if (r <= 0 || w < 3 || h < 3) return;
            var tmp = new byte[pixels.Length];
            int win = 2 * r + 1;
            // 横向
            for (int y = 0; y < h; y++)
            {
                int row = y * stride;
                for (int c = 0; c < 4; c++)
                {
                    int sum = 0;
                    for (int k = -r; k <= r; k++)
                        sum += pixels[row + Clamp(k, 0, w - 1) * 4 + c];
                    for (int x = 0; x < w; x++)
                    {
                        tmp[row + x * 4 + c] = (byte)Math.Min(255, sum / win);
                        sum += pixels[row + Clamp(x + r + 1, 0, w - 1) * 4 + c]
                             - pixels[row + Clamp(x - r, 0, w - 1) * 4 + c];
                    }
                }
            }
            // 纵向
            for (int x = 0; x < w; x++)
            {
                int col = x * 4;
                for (int c = 0; c < 4; c++)
                {
                    int sum = 0;
                    for (int k = -r; k <= r; k++)
                        sum += tmp[Clamp(k, 0, h - 1) * stride + col + c];
                    for (int y = 0; y < h; y++)
                    {
                        pixels[y * stride + col + c] = (byte)Math.Min(255, sum / win);
                        sum += tmp[Clamp(y + r + 1, 0, h - 1) * stride + col + c]
                             - tmp[Clamp(y - r, 0, h - 1) * stride + col + c];
                    }
                }
            }
        }
    }
}
