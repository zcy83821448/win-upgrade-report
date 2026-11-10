using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;

namespace WinUpd
{
    /// <summary>原生裁切背景图：拖动方框选择显示区域。</summary>
    public sealed class CropWindow : Window
    {
        private readonly BitmapSource _source;
        private readonly Action<BitmapSource, Color> _done;
        private readonly Image _image;
        private readonly Canvas _stage;
        private readonly Border _box;
        private readonly Border[] _handles = new Border[4];
        private Rect _crop;
        private double _dispW, _dispH, _scale = 1;
        private Point _dragStart;
        private Rect _dragRect;
        private string _dragMode = "";

        public CropWindow(BitmapSource source, Action<BitmapSource, Color> done)
        {
            _source = source;
            _done = done;
            Title = "裁切背景图";
            Width = 920;
            Height = 680;
            WindowStartupLocation = WindowStartupLocation.CenterOwner;
            WindowStyle = WindowStyle.SingleBorderWindow;
            Background = new SolidColorBrush(Color.FromRgb(0x17, 0x18, 0x1B));
            FontFamily = (FontFamily)Application.Current.Resources["UiFont"];

            var grid = new Grid { Margin = new Thickness(20) };
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });

            var head = new Grid { Margin = new Thickness(0, 0, 0, 12) };
            head.Children.Add(new TextBlock
            {
                Text = "裁切背景图",
                Foreground = Brushes.White,
                FontSize = 16,
                FontWeight = FontWeights.SemiBold
            });
            var hint = new TextBlock
            {
                Text = "拖动方框选择要显示的区域；背景会自动铺满整个窗口。",
                Foreground = new SolidColorBrush(Color.FromRgb(0xB8, 0xB4, 0xAC)),
                FontSize = 12.5,
                HorizontalAlignment = HorizontalAlignment.Right,
                VerticalAlignment = VerticalAlignment.Center
            };
            head.Children.Add(hint);
            grid.Children.Add(head);

            var stageHost = new Grid
            {
                Background = new SolidColorBrush(Color.FromRgb(0x0F, 0x10, 0x12)),
                ClipToBounds = true
            };
            _image = new Image { Stretch = Stretch.Fill, SnapsToDevicePixels = true };
            _stage = new Canvas
            {
                Background = Brushes.Transparent,
                HorizontalAlignment = HorizontalAlignment.Center,
                VerticalAlignment = VerticalAlignment.Center
            };
            _stage.Children.Add(_image);
            stageHost.Children.Add(_stage);
            Grid.SetRow(stageHost, 1);
            grid.Children.Add(stageHost);

            _box = new Border
            {
                BorderBrush = new SolidColorBrush(Color.FromRgb(0x4A, 0x86, 0xFF)),
                BorderThickness = new Thickness(2),
                Background = new SolidColorBrush(Color.FromArgb(28, 74, 134, 255)),
                Cursor = Cursors.SizeAll
            };
            _box.MouseLeftButtonDown += (s, e) => StartDrag("move", e);
            _stage.Children.Add(_box);
            for (int i = 0; i < 4; i++)
            {
                var h = new Border
                {
                    Width = 14,
                    Height = 14,
                    Background = Brushes.White,
                    BorderBrush = new SolidColorBrush(Color.FromRgb(0x4A, 0x86, 0xFF)),
                    BorderThickness = new Thickness(2),
                    CornerRadius = new CornerRadius(3),
                    Cursor = i == 0 || i == 3 ? Cursors.SizeNWSE : Cursors.SizeNESW
                };
                int idx = i;
                h.MouseLeftButtonDown += (s, e) =>
                {
                    StartDrag(idx == 0 ? "nw" : idx == 1 ? "ne" : idx == 2 ? "sw" : "se", e);
                };
                _handles[i] = h;
                _stage.Children.Add(h);
            }

            var foot = new Grid { Margin = new Thickness(0, 14, 0, 0) };
            var left = new TextBlock
            {
                Text = "提示：深色图片会自动把界面文字调亮，浅色图片保持深色。",
                Foreground = new SolidColorBrush(Color.FromRgb(0xB8, 0xB4, 0xAC)),
                FontSize = 12.5,
                VerticalAlignment = VerticalAlignment.Center
            };
            foot.Children.Add(left);
            var actions = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                HorizontalAlignment = HorizontalAlignment.Right
            };
            actions.Children.Add(Btn("全图", false, ResetCrop));
            actions.Children.Add(Btn("取消", false, Close));
            var ok = Btn("使用这张", true, Confirm);
            actions.Children.Add(ok);
            foot.Children.Add(actions);
            grid.Children.Add(foot);
            Grid.SetRow(foot, 2);
            Content = grid;

            Loaded += (s, e) => LayoutImage();
            SizeChanged += (s, e) => LayoutImage();
        }

        private static Button Btn(string text, bool primary, Action click)
        {
            var b = new Button
            {
                Content = text,
                Style = (Style)Application.Current.Resources[primary ? "BtnPrimary" : "BtnSecondary"],
                Margin = new Thickness(8, 0, 0, 0),
                Padding = new Thickness(13, 6, 13, 6)
            };
            b.Click += (s, e) => click();
            return b;
        }

        private void LayoutImage()
        {
            double hostW = _stage.ActualWidth > 0 ? _stage.ActualWidth : ActualWidth - 40;
            double hostH = _stage.ActualHeight > 0 ? _stage.ActualHeight : ActualHeight - 180;
            if (hostW <= 10 || hostH <= 10) return;
            double iw = _source.PixelWidth, ih = _source.PixelHeight;
            _scale = Math.Min(hostW / iw, hostH / ih);
            _dispW = Math.Max(60, Math.Round(iw * _scale));
            _dispH = Math.Max(60, Math.Round(ih * _scale));
            bool sizeChanged = Math.Abs(_stage.Width - _dispW) > 1
                || Math.Abs(_stage.Height - _dispH) > 1;
            _image.Width = _dispW;
            _image.Height = _dispH;
            _image.Source = _source;
            _stage.Width = _dispW;
            _stage.Height = _dispH;
            if (_crop.Width <= 0 || sizeChanged)
                _crop = new Rect(0, 0, _dispW, _dispH);
            PlaceCrop();
        }

        private void PlaceCrop()
        {
            Canvas.SetLeft(_box, _crop.X);
            Canvas.SetTop(_box, _crop.Y);
            _box.Width = Math.Max(1, _crop.Width);
            _box.Height = Math.Max(1, _crop.Height);
            double[][] pos =
            {
                new double[] { _crop.Left - 7, _crop.Top - 7 },
                new double[] { _crop.Right - 7, _crop.Top - 7 },
                new double[] { _crop.Left - 7, _crop.Bottom - 7 },
                new double[] { _crop.Right - 7, _crop.Bottom - 7 }
            };
            for (int i = 0; i < 4; i++)
            {
                Canvas.SetLeft(_handles[i], pos[i][0]);
                Canvas.SetTop(_handles[i], pos[i][1]);
            }
        }

        private void ResetCrop()
        {
            _crop = new Rect(0, 0, _dispW, _dispH);
            PlaceCrop();
        }

        private void StartDrag(string mode, MouseButtonEventArgs e)
        {
            _dragMode = mode;
            _dragStart = e.GetPosition(_stage);
            _dragRect = _crop;
            _box.CaptureMouse();
            e.Handled = true;
        }

        protected override void OnMouseMove(MouseEventArgs e)
        {
            base.OnMouseMove(e);
            if (!_box.IsMouseCaptured) return;
            Point p = e.GetPosition(_stage);
            double dx = p.X - _dragStart.X;
            double dy = p.Y - _dragStart.Y;
            double min = 32;
            Rect r = _dragRect;
            double x = r.X, y = r.Y, w = r.Width, h = r.Height;
            if (_dragMode == "move")
            {
                x = Clamp(r.X + dx, 0, _dispW - r.Width);
                y = Clamp(r.Y + dy, 0, _dispH - r.Height);
            }
            else
            {
                if (_dragMode.IndexOf('w') >= 0)
                {
                    double nx = Clamp(r.X + dx, 0, r.X + r.Width - min);
                    w = r.X + r.Width - nx;
                    x = nx;
                }
                if (_dragMode.IndexOf('e') >= 0) w = Clamp(r.Width + dx, min, _dispW - r.X);
                if (_dragMode.IndexOf('n') >= 0)
                {
                    double ny = Clamp(r.Y + dy, 0, r.Y + r.Height - min);
                    h = r.Y + r.Height - ny;
                    y = ny;
                }
                if (_dragMode.IndexOf('s') >= 0) h = Clamp(r.Height + dy, min, _dispH - r.Y);
            }
            _crop = new Rect(x, y, w, h);
            PlaceCrop();
        }

        protected override void OnMouseUp(MouseButtonEventArgs e)
        {
            base.OnMouseUp(e);
            if (_box.IsMouseCaptured) _box.ReleaseMouseCapture();
        }

        private static double Clamp(double v, double lo, double hi)
        {
            if (hi < lo) return lo;
            return v < lo ? lo : (v > hi ? hi : v);
        }

        private void Confirm()
        {
            try
            {
                if (_scale <= 0) return;
                int sx = (int)Math.Round(_crop.X / _scale);
                int sy = (int)Math.Round(_crop.Y / _scale);
                int sw = Math.Max(1, (int)Math.Round(_crop.Width / _scale));
                int sh = Math.Max(1, (int)Math.Round(_crop.Height / _scale));
                if (sx < 0) sx = 0;
                if (sy < 0) sy = 0;
                if (sx + sw > _source.PixelWidth) sw = _source.PixelWidth - sx;
                if (sy + sh > _source.PixelHeight) sh = _source.PixelHeight - sy;
                if (sw <= 0 || sh <= 0) return;
                var cropped = new CroppedBitmap(_source, new Int32Rect(sx, sy, sw, sh));
                BitmapSource result = cropped;
                int maxDim = 1920;
                if (Math.Max(sw, sh) > maxDim)
                {
                    double k = (double)maxDim / Math.Max(sw, sh);
                    result = new TransformedBitmap(cropped, new ScaleTransform(k, k));
                }
                Color accent = AccentUtil.Average(result);
                if (_done != null) _done(result, accent);
                Close();
            }
            catch (Exception e)
            {
                AppEnv.Log("裁切失败：" + e);
                try
                {
                    MessageBox.Show(this, "裁切这张图失败：\n" + e.Message,
                        "背景图", MessageBoxButton.OK, MessageBoxImage.Warning);
                }
                catch { }
            }
        }
    }
}

