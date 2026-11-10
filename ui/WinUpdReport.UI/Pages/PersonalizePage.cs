using System;
using System.Collections.Generic;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using Microsoft.Win32;

namespace WinUpd
{
    /// <summary>
    /// 个性化：上面是背景图（所见即所得），下面是效果和强调色。
    /// 滑杆一拖就生效，眼睛盯着预览就能判断，不用来回切换页面。
    /// </summary>
    public sealed class PersonalizePage : IPage
    {
        private readonly MainWindow _shell;
        private readonly StackPanel _root = new StackPanel();
        private readonly ScrollViewer _scroller;
        private bool _loading;
        private Slider _blur;
        private Slider _card;
        private Slider _scrim;
        private TextBlock _blurVal;
        private TextBlock _cardVal;
        private TextBlock _scrimVal;
        private Border _swatch;
        private TextBlock _accentHex;
        private string _bgPath = "";
        private string _accent = "";

        public string Key { get { return "personalize"; } }
        public string Title { get { return "个性化"; } }
        public FrameworkElement Root { get { return _scroller; } }

        public PersonalizePage(MainWindow shell)
        {
            _shell = shell;
            _scroller = Ui.Scroller(_root);
        }

        public void LoadData(AppData data)
        {
            _loading = true;
            _root.Children.Clear();
            var p = data.Personalize ?? new Dictionary<string, object>();
            _bgPath = Json.Str(p, "bg_path");
            if (string.IsNullOrEmpty(_bgPath))
            {
                string rel = Json.Str(data.Config, "personalize_bg");
                if (!string.IsNullOrEmpty(rel))
                    _bgPath = Path.IsPathRooted(rel) ? rel : Path.Combine(AppEnv.DataDir, rel);
            }
            bool has = !string.IsNullOrEmpty(_bgPath) && File.Exists(_bgPath);
            _accent = Json.Str(p, "accent");

            _root.Children.Add(Ui.PageHeader("外观与行为", "个性化",
                "换一张背景图，再调磨砂玻璃的浓度；深色图片会自动换成浅色文字。"));

            _root.Children.Add(Ui.Section("背景图", has ? "已启用" : "未设置", BackgroundCard(has)));

            var left = Ui.Section("毛玻璃效果", has ? "拖动时实时生效" : "上传背景图后生效", EffectsCard(p));
            var right = new StackPanel();
            right.Children.Add(Ui.Section("强调色", has ? "跟着图片走" : "上传后自动取色", AccentCard(has)));
            right.Children.Add(Ui.Section("说明", null, NoteCard(), 0));
            _root.Children.Add(Ui.TwoColumn(left, right));

            _loading = false;
            _shell.PreviewPersonalize(Json.Int(p, "blur", 15),
                Json.Int(p, "card_alpha", 70), Json.Int(p, "scrim_alpha", 0));
        }

        public void ApplyPoll(PollUpdate poll) { }

        // ---------------------------------------------------------------- 背景图
        private FrameworkElement BackgroundCard(bool has)
        {
            var grid = new Grid();
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(300) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });

            var previewBorder = new Border
            {
                Width = 300,
                Height = 186,
                CornerRadius = new CornerRadius(10),
                Background = (Brush)Application.Current.Resources["Surface2Brush"],
                BorderBrush = (Brush)Application.Current.Resources["LineBrush"],
                BorderThickness = new Thickness(1),
                ClipToBounds = true
            };
            if (has)
            {
                try
                {
                    var bmp = LoadBitmap(_bgPath);
                    if (bmp != null)
                        previewBorder.Background = new ImageBrush(bmp) { Stretch = Stretch.UniformToFill };
                }
                catch { }
            }
            else
            {
                var empty = Ui.T("还没有背景图", "FieldHint");
                empty.HorizontalAlignment = HorizontalAlignment.Center;
                empty.VerticalAlignment = VerticalAlignment.Center;
                previewBorder.Child = empty;
            }
            grid.Children.Add(previewBorder);
            // 图片本身也可以点：很多人第一反应是点预览图换图
            previewBorder.Cursor = Cursors.Hand;
            previewBorder.ToolTip = has ? "点击更换背景图" : "点击选择背景图";
            previewBorder.MouseLeftButtonUp += (s, e) => PickImage();

            var right = new StackPanel { Margin = new Thickness(D.S5, 0, 0, 0) };
            right.Children.Add(Ui.T(has ? "当前背景图" : "用一张自己的图片当底", null, D.Subhead, FontWeights.SemiBold));
            right.Children.Add(Ui.T("壁纸本体保持清晰；只有透过卡片/侧栏看到的那一块做了模糊，就是毛玻璃。", "RowHelp"));
            var actions = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, D.S4, 0, 0) };
            var pick = Ui.B(has ? "更换图片" : "上传图片并裁切", "BtnPrimary", PickImage);
            actions.Children.Add(pick);
            if (has)
            {
                var recrop = Ui.B("重新裁切", "BtnSecondary", () =>
                {
                    var bmp = LoadBitmap(_bgPath);
                    if (bmp == null) { _shell.ToastErr("背景图读不出来，重新选一张吧"); return; }
                    OpenCrop(bmp);
                });
                recrop.Margin = new Thickness(D.S3, 0, 0, 0);
                actions.Children.Add(recrop);
                var rm = Ui.B("移除背景", "BtnGhost", () => { });
                rm.Margin = new Thickness(D.S3, 0, 0, 0);
                rm.Click += (s, e) =>
                {
                    if (!_shell.ConfirmThen(rm, "再点一次移除")) return;
                    _shell.SendAction("clear_personal_image", new Dictionary<string, object>(),
                        "背景已移除", "正在移除背景…", 30000, r =>
                        {
                            _shell.InvalidatePersonalize();
                            _shell.RefreshSoon();
                        });
                };
                actions.Children.Add(rm);
            }
            right.Children.Add(actions);
            var note = Ui.T("图片会复制一份到程序目录，只在本机使用；发布版不包含你的图片。", "FieldHint");
            note.Margin = new Thickness(0, D.S4, 0, 0);
            note.MaxWidth = 480;
            right.Children.Add(note);
            Grid.SetColumn(right, 1);
            grid.Children.Add(right);
            return Ui.Card(grid);
        }

        // ---------------------------------------------------------------- 效果
        private FrameworkElement EffectsCard(Dictionary<string, object> p)
        {
            var sp = new StackPanel();
            _blur = AddSlider(sp, "模糊强度", "卡片背后那层图糊到什么程度，越大越像毛玻璃",
                Json.Int(p, "blur", 15), 0, 60, "px", out _blurVal, "personalize_blur");
            _card = AddSlider(sp, "卡片白纱", "卡片白色的浓度；太低文字会看不清",
                Json.Int(p, "card_alpha", 70), 40, 98, "%", out _cardVal, "personalize_card_alpha");
            _scrim = AddSlider(sp, "图片蒙层", "整张图上的蒙层；图片偏深、偏花时调高更好读",
                Json.Int(p, "scrim_alpha", 0), 0, 70, "%", out _scrimVal, "personalize_scrim_alpha");
            return Ui.Card(sp);
        }

        private Slider AddSlider(Panel host, string label, string help, int value,
            double min, double max, string unit, out TextBlock valueText,
            string cfgKey)
        {
            var block = new StackPanel { Margin = new Thickness(0, 0, 0, D.S5) };
            var head = new Grid();
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            head.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            head.Children.Add(Ui.T(label, "RowLabel"));
            valueText = Ui.T(value + unit, "MonoText");
            valueText.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(valueText, 1);
            head.Children.Add(valueText);
            block.Children.Add(head);
            block.Children.Add(Ui.T(help, "RowHelp"));
            var slider = new Slider
            {
                Minimum = min,
                Maximum = max,
                Value = value,
                IsSnapToTickEnabled = false,
                VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, D.S2, 0, 0)
            };
            block.Children.Add(slider);
            TextBlock vt = valueText;
            slider.ValueChanged += (s, e) =>
            {
                int v = (int)Math.Round(e.NewValue);
                vt.Text = v + unit;
                if (_loading) return;
                _shell.QueueSave(cfgKey, v);
                _shell.PreviewPersonalize(
                    (int)Math.Round(_blur != null ? _blur.Value : 15),
                    (int)Math.Round(_card != null ? _card.Value : 70),
                    (int)Math.Round(_scrim != null ? _scrim.Value : 0));
            };
            host.Children.Add(block);
            return slider;
        }

        // ---------------------------------------------------------------- 强调色
        private FrameworkElement AccentCard(bool has)
        {
            var sp = new StackPanel();
            var top = new Grid();
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(56) });
            top.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            _swatch = new Border
            {
                Width = 42,
                Height = 42,
                CornerRadius = new CornerRadius(10),
                VerticalAlignment = VerticalAlignment.Top
            };
            top.Children.Add(_swatch);
            var meta = new StackPanel();
            meta.Children.Add(Ui.T(has ? "来自图片的平均色" : "默认强调色", "RowLabel"));
            meta.Children.Add(Ui.T("取整张图的平均色，自动提亮到适合白字的深度。", "RowHelp"));
            _accentHex = Ui.T(string.IsNullOrEmpty(_accent) ? "#1F5AE0（默认墨蓝）" : _accent, "MonoText");
            _accentHex.Margin = new Thickness(0, D.S2, 0, 0);
            meta.Children.Add(_accentHex);
            Grid.SetColumn(meta, 1);
            top.Children.Add(meta);
            sp.Children.Add(top);
            ApplySwatch(_accent);

            sp.Children.Add(Ui.Rule(D.S3, D.S3));
            var demo = new StackPanel { Orientation = Orientation.Horizontal };
            var sample = Ui.B("示例按钮", "BtnPrimary", null);
            demo.Children.Add(sample);
            var tag = Ui.Tag("标签", "accent");
            tag.Margin = new Thickness(D.S3, 0, D.S3, 0);
            demo.Children.Add(tag);
            var link = Ui.Link("示例链接", null, true);
            demo.Children.Add(link);
            sp.Children.Add(demo);

            if (has)
            {
                var recompute = Ui.B("从图片重新取色", "BtnSecondary", () =>
                {
                    var bmp = LoadBitmap(_bgPath);
                    if (bmp == null) return;
                    Color avg = AccentUtil.AdjustForReadability(AccentUtil.Average(bmp));
                    string hex = AccentUtil.ToHex(avg);
                    _accent = hex;
                    ApplySwatch(hex);
                    _shell.ApplyAccentColor(hex);
                    _shell.QueueSave("personalize_accent", hex);
                    _shell.ToastOk("已按图片重新取色");
                });
                recompute.HorizontalAlignment = HorizontalAlignment.Left;
                recompute.Margin = new Thickness(0, D.S5, 0, 0);
                sp.Children.Add(recompute);
            }
            return Ui.Card(sp);
        }

        private void ApplySwatch(string hex)
        {
            if (_swatch == null) return;
            Color c;
            if (!TryColor(hex, out c)) c = Color.FromRgb(0x1F, 0x5A, 0xE0);
            _swatch.Background = new SolidColorBrush(c);
            if (_accentHex != null)
                _accentHex.Text = string.IsNullOrEmpty(hex) ? "#1F5AE0（默认墨蓝）" : hex;
        }

        private static bool TryColor(string hex, out Color color)
        {
            color = Colors.Black;
            if (string.IsNullOrEmpty(hex)) return false;
            try
            {
                color = (Color)ColorConverter.ConvertFromString(hex);
                return true;
            }
            catch { return false; }
        }

        // ---------------------------------------------------------------- 说明
        private FrameworkElement NoteCard()
        {
            var sp = new StackPanel();
            sp.Children.Add(Ui.T("这些设置只影响这台电脑上的界面。恢复默认会移除背景图，模糊、白纱、蒙层回到默认值。", "RowHelp"));            var btn = Ui.B("恢复默认外观", "BtnSecondary", () => { });
            btn.HorizontalAlignment = HorizontalAlignment.Left;
            btn.Margin = new Thickness(0, D.S4, 0, 0);
            btn.Click += (s, e) =>
            {
                if (!_shell.ConfirmThen(btn, "再点一次恢复")) return;
                _shell.SendAction("clear_personal_image", new Dictionary<string, object>(),
                    "已恢复默认外观", "正在恢复…", 30000, r =>
                    {
                        _shell.InvalidatePersonalize();
                        _shell.QueueSave("personalize_blur", 15);
                        _shell.QueueSave("personalize_card_alpha", 70);
                        _shell.QueueSave("personalize_scrim_alpha", 0);
                        _shell.RefreshSoon();
                    });
            };
            sp.Children.Add(btn);
            return Ui.Card(sp);
        }

        // ---------------------------------------------------------------- 图片
        private void PickImage()
        {
            var dlg = new OpenFileDialog
            {
                Title = "选择背景图片",
                Filter = "图片 (*.png;*.jpg;*.jpeg;*.bmp;*.gif)|*.png;*.jpg;*.jpeg;*.bmp;*.gif|所有文件 (*.*)|*.*"
            };
            if (dlg.ShowDialog(_shell) != true) return;
            try
            {
                var bmp = LoadBitmap(dlg.FileName);
                if (bmp == null) { _shell.ToastErr("这张图片读不出来，换一张试试"); return; }
                OpenCrop(bmp);
            }
            catch (Exception e)
            {
                _shell.ToastErr("这张图片读不出来：" + e.Message);
            }
        }

        private void OpenCrop(BitmapSource source)
        {
            var dlg = new CropWindow(source, (cropped, accent) =>
            {
                try
                {
                    _shell.SetActivity("正在处理背景图…");
                    string dataUrl;
                    try
                    {
                        // JPEG 比 PNG 小一个数量级：编码快、管道传得快、保存也不容易卡
                        dataUrl = AccentUtil.EncodeJpegDataUrl(cropped);
                    }
                    catch
                    {
                        dataUrl = AccentUtil.EncodePngDataUrl(cropped);
                    }
                    _shell.ClearActivity();
                    string hex = AccentUtil.ToHex(AccentUtil.AdjustForReadability(accent));
                    _accent = hex;
                    _shell.SendAction("save_personal_image", new Dictionary<string, object>
                    {
                        { "data_url", dataUrl },
                        { "accent", hex }
                    }, "背景已保存", "正在保存背景…", 60000, r =>
                    {
                        _shell.InvalidatePersonalize();
                        _shell.ApplyAccentColor(hex);
                        _shell.RefreshSoon();
                    });
                }
                catch (Exception e)
                {
                    _shell.ClearActivity();
                    _shell.ToastErr("保存背景失败：" + e.Message);
                }
            });
            dlg.Owner = _shell;
            dlg.ShowDialog();
        }

        private static BitmapSource LoadBitmap(string path)
        {
            if (string.IsNullOrEmpty(path) || !File.Exists(path)) return null;
            var bmp = new BitmapImage();
            bmp.BeginInit();
            bmp.CacheOption = BitmapCacheOption.OnLoad;
            bmp.UriSource = new Uri(path);
            bmp.EndInit();
            bmp.Freeze();
            return bmp;
        }
    }
}
