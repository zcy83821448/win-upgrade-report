using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;

namespace WinUpd
{
    /// <summary>
    /// 页面积木。所有页只从这里取组件，保证同样的东西长得一样：
    /// 页面标题区、区块、卡片、设置行、开关行、搜索框、分段选择、空状态。
    /// </summary>
    public static class Ui
    {
        public static readonly FontFamily IconFont =
            (FontFamily)new FontFamilyConverter().ConvertFromString("Segoe MDL2 Assets");

        // ================================================================ 文本
        public static TextBlock T(string text, string style = null, double size = 0,
                                  FontWeight? weight = null, Brush fg = null)
        {
            var tb = new TextBlock { Text = text ?? "" };
            if (!string.IsNullOrEmpty(style))
                tb.Style = (Style)Application.Current.Resources[style];
            if (size > 0) tb.FontSize = size;
            if (weight.HasValue) tb.FontWeight = weight.Value;
            if (fg != null) tb.Foreground = fg;
            return tb;
        }

        public static TextBlock Glyph(string glyph, double size = 15, Brush fg = null,
                                      double width = 0)
        {
            var tb = new TextBlock
            {
                Text = glyph,
                FontFamily = IconFont,
                FontSize = size,
                VerticalAlignment = VerticalAlignment.Center
            };
            if (width > 0) tb.Width = width;
            if (fg != null) tb.Foreground = fg;
            return tb;
        }

        private static Brush R(string key)
        {
            return (Brush)Application.Current.Resources[key];
        }

        // ================================================================ 骨架
        /// <summary>
        /// 页面统一外壳：上下左右用同一套留白，内容最宽 880 并居中。
        /// 宽度按"窗口实际宽度 - 左右留白 - 滚动条"硬算，保证每页左边缘在同一根竖线上，
        /// 不会因为内容多少而左右漂移。
        /// </summary>
        public static ScrollViewer Scroller(UIElement content)
        {
            var body = new Grid { HorizontalAlignment = HorizontalAlignment.Center };
            body.Children.Add(content);
            body.Margin = new Thickness(D.PagePadL, D.PagePadT, D.PagePadR, D.PagePadB);

            var sv = new ScrollViewer
            {
                Style = (Style)Application.Current.Resources["SlimScroll"],
                VerticalScrollBarVisibility = ScrollBarVisibility.Auto,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
                Content = body
            };
            ScrollViewer.SetPanningMode(sv, PanningMode.VerticalOnly);

            Action fit = () =>
            {
                double raw = sv.ActualWidth;
                if (double.IsNaN(raw) || raw < 100) raw = 968;
                double w = Math.Min(D.ContentMax, Math.Max(240, raw - D.PagePadL - D.PagePadR - 20));
                if (double.IsNaN(body.Width) || Math.Abs(body.Width - w) > 0.5)
                    body.Width = w;
            };
            sv.SizeChanged += (s, e) => fit();
            sv.Loaded += (s, e) =>
            {
                fit();
                sv.Dispatcher.BeginInvoke(new Action(fit),
                    System.Windows.Threading.DispatcherPriority.Loaded);
            };
            return sv;
        }

        /// <summary>
        /// 页面标题区：小标签 + 大标题 + 一句说明，右侧放本页主要动作。
        /// 标题区永远是内容的第一块，用户一眼知道"这是哪、能干什么"。
        /// </summary>
        public static FrameworkElement PageHeader(string overline, string title, string desc,
                                                  params UIElement[] actions)
        {
            var grid = new Grid { Margin = new Thickness(0, 0, 0, D.S5) };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });

            var left = new StackPanel();
            if (!string.IsNullOrEmpty(overline))
                left.Children.Add(T(overline, "Overline"));
            left.Children.Add(T(title, "PageTitle"));
            if (!string.IsNullOrEmpty(desc))
                left.Children.Add(T(desc, "PageDesc"));
            grid.Children.Add(left);

            if (actions != null && actions.Length > 0)
            {
                var row = new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    VerticalAlignment = VerticalAlignment.Bottom,
                    Margin = new Thickness(D.S5, 0, 0, 3)
                };
                foreach (var a in actions)
                {
                    var fe = a as FrameworkElement;
                    if (fe != null && row.Children.Count > 0)
                        fe.Margin = new Thickness(D.S3, 0, 0, 0);
                    row.Children.Add(a);
                }
                Grid.SetColumn(row, 1);
                grid.Children.Add(row);
            }
            return grid;
        }

        /// <summary>
        /// 主栏 : 副栏 = 1.618 : 1 的两栏。左栏放主内容（设置项、报告列表），
        /// 右栏放预览/提示/次要动作，宽度天然分出主次，gap 用统一值。
        /// </summary>
        public static Grid TwoColumn(UIElement left, UIElement right,
                                     double gap = D.S5)
        {
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(D.Phi, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(gap) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.Children.Add(left);
            Grid.SetColumn(right, 2);
            g.Children.Add(right);
            return g;
        }

        // ================================================================ 卡片 / 区块
        public static Border Card(UIElement content, double pad = D.CardPad, bool hover = false,
                                  double marginBottom = 0)
        {
            // 用 ClipBorder 而不是普通 Border：圆角会把贴边的分割线/内容一起裁进去
            var b = new ClipBorder
            {
                Style = (Style)Application.Current.Resources[hover ? "CardHover" : "Card"],
                Padding = new Thickness(pad),
                Margin = new Thickness(0, 0, 0, marginBottom),
                Child = content
            };
            return b;
        }

        /// <summary>区块：15px 标题 + 可选右侧说明 + 内容，区块间距 42。</summary>
        public static FrameworkElement Section(string title, string right, UIElement content,
                                               double marginBottom = D.SectionGap)
        {
            var sp = new StackPanel { Margin = new Thickness(0, 0, 0, marginBottom) };
            if (!string.IsNullOrEmpty(title))
            {
                var head = new Grid { Margin = new Thickness(0, 0, 0, D.S3) };
                head.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                head.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
                var t = T(title, "SectionTitle");
                head.Children.Add(t);
                if (!string.IsNullOrEmpty(right))
                {
                    var r = T(right, "SectionRight");
                    Grid.SetColumn(r, 1);
                    head.Children.Add(r);
                }
                sp.Children.Add(head);
            }
            sp.Children.Add(content);
            return sp;
        }

        /// <summary>卡片内部的细分隔线，比卡片边框浅一档。</summary>
        public static Border Rule(double top = 0, double bottom = 0)
        {
            return new Border
            {
                Height = 1,
                Background = R("LineBrush"),
                Margin = new Thickness(0, top, 0, bottom)
            };
        }

        public static FrameworkElement Spacer(double h)
        {
            return new Border { Height = h };
        }

        // ================================================================ 设置行
        /// <summary>
        /// 标签在左、控件在右的标准设置行；标签自动换行，控件垂直居中。
        /// 窗口变窄（卡片内容宽度 &lt; 420）时自动改成上下排，避免说明文字被挤成一列单字。
        /// </summary>
        public static Grid Row(string label, string help, FrameworkElement control)
        {
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            g.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var left = new StackPanel();
            left.Children.Add(T(label, "RowLabel"));
            if (!string.IsNullOrEmpty(help)) left.Children.Add(T(help, "RowHelp"));
            g.Children.Add(left);
            if (control != null)
            {
                control.VerticalAlignment = VerticalAlignment.Center;
                control.Margin = new Thickness(D.S5, 0, 0, 0);
                Grid.SetColumn(control, 1);
                g.Children.Add(control);
            }
            g.Margin = new Thickness(0, D.S3, 0, D.S3);

            if (control != null)
            {
                bool stacked = false;
                Action apply = () =>
                {
                    bool want = g.ActualWidth > 0 && g.ActualWidth < 420;
                    if (want == stacked) return;
                    stacked = want;
                    if (want)
                    {
                        Grid.SetColumn(control, 0);
                        Grid.SetColumnSpan(control, 2);
                        Grid.SetRow(control, 1);
                        control.HorizontalAlignment = HorizontalAlignment.Left;
                        control.Margin = new Thickness(0, D.S3, 0, 0);
                    }
                    else
                    {
                        Grid.SetColumn(control, 1);
                        Grid.SetColumnSpan(control, 1);
                        Grid.SetRow(control, 0);
                        control.HorizontalAlignment = HorizontalAlignment.Stretch;
                        control.Margin = new Thickness(D.S5, 0, 0, 0);
                    }
                };
                g.SizeChanged += (s, e) => apply();
                g.Loaded += (s, e) => apply();
            }
            return g;
        }

        public static Grid SwitchRow(string label, string help, bool value,
                                     Action<bool> onChange, out ToggleButton toggle)
        {
            var sw = SwitchRaw(value, onChange);
            toggle = sw;
            var g = new Grid();
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            g.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var left = new StackPanel();
            left.Children.Add(T(label, "RowLabel"));
            if (!string.IsNullOrEmpty(help)) left.Children.Add(T(help, "RowHelp"));
            g.Children.Add(left);
            sw.VerticalAlignment = VerticalAlignment.Center;
            sw.Margin = new Thickness(D.S5, 0, 0, 0);
            Grid.SetColumn(sw, 1);
            g.Children.Add(sw);
            g.Margin = new Thickness(0, D.S3, 0, D.S3);
            return g;
        }

        /// <summary>两行文字的"标签+说明"块，用于自定义行。</summary>
        public static StackPanel Labeled(string label, string help)
        {
            var sp = new StackPanel();
            sp.Children.Add(T(label, "RowLabel"));
            if (!string.IsNullOrEmpty(help)) sp.Children.Add(T(help, "RowHelp"));
            return sp;
        }

        // ================================================================ 控件
        public static ToggleButton SwitchRaw(bool value, Action<bool> onChange)
        {
            var tb = new ToggleButton
            {
                Style = (Style)Application.Current.Resources["Switch"],
                IsChecked = value
            };
            tb.Checked += (s, e) => { if (onChange != null) onChange(true); };
            tb.Unchecked += (s, e) => { if (onChange != null) onChange(false); };
            return tb;
        }

        /// <summary>带放大镜图标的搜索框；图标和占位文本都不吃点击。</summary>
        public static Grid SearchBox(string placeholder, Action<string> changed,
                                     double width = 300)
        {
            var grid = new Grid { Width = width };
            var tb = new TextBox { Style = (Style)Application.Current.Resources["InputBox"] };
            tb.Padding = new Thickness(30, 6, 9, 6);
            tb.FontSize = 12.5;
            grid.Children.Add(tb);
            var icon = Glyph("\uE721", 12, R("Ink3Brush"));
            icon.HorizontalAlignment = HorizontalAlignment.Left;
            icon.Margin = new Thickness(10, 0, 0, 0);
            icon.IsHitTestVisible = false;
            grid.Children.Add(icon);
            var ph = T(placeholder, "FieldHint");
            ph.Margin = new Thickness(31, 0, 8, 0);
            ph.VerticalAlignment = VerticalAlignment.Center;
            ph.IsHitTestVisible = false;
            ph.TextTrimming = TextTrimming.CharacterEllipsis;
            grid.Children.Add(ph);
            tb.TextChanged += (s, e) =>
            {
                ph.Visibility = tb.Text.Length > 0 ? Visibility.Collapsed : Visibility.Visible;
                if (changed != null) changed(tb.Text);
            };
            return grid;
        }

        public static Button B(string text, string style, Action click,
                               double fontSize = 0, Thickness? pad = null)
        {
            var b = new Button
            {
                Content = text,
                Style = (Style)Application.Current.Resources[style]
            };
            if (fontSize > 0) b.FontSize = fontSize;
            if (pad.HasValue) b.Padding = pad.Value;
            if (click != null) b.Click += (s, e) => click();
            return b;
        }

        public static Button IconButton(string glyph, string tooltip, Action click,
                                        double size = 13)
        {
            var b = new Button
            {
                Content = Glyph(glyph, size),
                Style = (Style)Application.Current.Resources["IconBtn"],
                ToolTip = tooltip
            };
            if (click != null) b.Click += (s, e) => click();
            return b;
        }

        public static Button Link(string text, Action click, bool accent = false,
                                  bool danger = false)
        {
            var b = new Button
            {
                Content = text,
                Style = (Style)Application.Current.Resources[
                    danger ? "LinkDanger" : (accent ? "LinkAccent" : "LinkBtn")]
            };
            if (click != null) b.Click += (s, e) => click();
            return b;
        }

        public static TextBox Input(string value, Action<string> changed = null,
                                    bool mono = false, bool live = false,
                                    double width = double.NaN)
        {
            var tb = new TextBox
            {
                Text = value ?? "",
                Style = (Style)Application.Current.Resources[mono ? "InputMono" : "InputBox"]
            };
            if (!double.IsNaN(width)) tb.Width = width;
            if (changed != null)
            {
                if (live)
                {
                    tb.TextChanged += (s, e) => changed(tb.Text);
                }
                else
                {
                    tb.LostFocus += (s, e) => changed(tb.Text);
                    tb.KeyDown += (s, e) =>
                    {
                        if (e.Key == System.Windows.Input.Key.Enter)
                        {
                            changed(tb.Text);
                            e.Handled = true;
                        }
                    };
                }
            }
            return tb;
        }

        /// <summary>数字输入：失焦/回车时夹紧范围并回调。</summary>
        public static FrameworkElement NumberBox(object value, double min, double max,
                                                bool isFloat, Action<double> onCommit,
                                                string unit, double width = 96)
        {
            double cur = 0;
            try { cur = Convert.ToDouble(value); } catch { }
            var tb = new TextBox
            {
                Text = isFloat ? cur.ToString("0.##") : Math.Round(cur).ToString("0"),
                Width = width,
                HorizontalContentAlignment = HorizontalAlignment.Right,
                Style = (Style)Application.Current.Resources["InputBox"]
            };
            Action commit = null;
            commit = () =>
            {
                double v;
                if (!double.TryParse(tb.Text.Trim(), out v))
                {
                    tb.Text = isFloat ? cur.ToString("0.##") : Math.Round(cur).ToString("0");
                    return;
                }
                if (v < min) v = min;
                if (v > max) v = max;
                tb.Text = isFloat ? v.ToString("0.##") : Math.Round(v).ToString("0");
                cur = v;
                if (onCommit != null) onCommit(v);
            };
            tb.LostFocus += (s, e) => commit();
            tb.KeyDown += (s, e) =>
            {
                if (e.Key == System.Windows.Input.Key.Enter)
                {
                    commit();
                    e.Handled = true;
                }
            };
            var sp = new StackPanel { Orientation = Orientation.Horizontal };
            sp.Children.Add(tb);
            if (!string.IsNullOrEmpty(unit))
            {
                var u = T(unit, null, 12.5, null, R("Ink2Brush"));
                u.Margin = new Thickness(7, 0, 0, 0);
                u.VerticalAlignment = VerticalAlignment.Center;
                sp.Children.Add(u);
            }
            return sp;
        }

        public static SegmentedBox Segmented(string[] options, string value,
                                             Action<string> onChange)
        {
            return new SegmentedBox(options, value, onChange);
        }

        public static Border Tag(string text, string kind)
        {
            var b = new Border
            {
                Style = (Style)Application.Current.Resources[
                    kind == "ok" ? "TagOk" : (kind == "accent" ? "TagAccent" : "TagQuiet")],
                Margin = new Thickness(0, 0, 6, 0)
            };
            Brush fg = R(kind == "ok" ? "OkBrush" : (kind == "accent" ? "AccentBrush" : "Ink2Brush"));
            b.Child = T(text, null, 11.5, null, fg);
            return b;
        }

        public static Ellipse Dot(bool ok, double size = 8)
        {
            return new Ellipse
            {
                Width = size,
                Height = size,
                Fill = R(ok ? "OkBrush" : "LineStrongBrush"),
                VerticalAlignment = VerticalAlignment.Center
            };
        }

        // ================================================================ 空状态
        public static StackPanel Empty(string title, string help, params UIElement[] actions)
        {
            var sp = new StackPanel
            {
                HorizontalAlignment = HorizontalAlignment.Center,
                Margin = new Thickness(0, D.S6, 0, D.S6)
            };
            var icon = Glyph("\uE7C3", 26, R("LineStrongBrush"));
            icon.HorizontalAlignment = HorizontalAlignment.Center;
            sp.Children.Add(icon);
            var t = T(title, null, 14, FontWeights.SemiBold);
            t.HorizontalAlignment = HorizontalAlignment.Center;
            t.Margin = new Thickness(0, D.S3, 0, 0);
            sp.Children.Add(t);
            if (!string.IsNullOrEmpty(help))
            {
                var h = T(help, "RowHelp");
                h.HorizontalAlignment = HorizontalAlignment.Center;
                h.TextAlignment = TextAlignment.Center;
                h.MaxWidth = 360;
                h.Margin = new Thickness(0, D.S2, 0, 0);
                sp.Children.Add(h);
            }
            if (actions != null && actions.Length > 0)
            {
                var row = new StackPanel
                {
                    Orientation = Orientation.Horizontal,
                    HorizontalAlignment = HorizontalAlignment.Center,
                    Margin = new Thickness(0, D.S4, 0, 0)
                };
                foreach (var a in actions)
                {
                    var fe = a as FrameworkElement;
                    if (fe != null && row.Children.Count > 0)
                        fe.Margin = new Thickness(D.S3, 0, 0, 0);
                    row.Children.Add(a);
                }
                sp.Children.Add(row);
            }
            return sp;
        }

        /// <summary>大数字 + 小标签，用于概览/详情的度量块。</summary>
        public static FrameworkElement Metric(string label, string value)
        {
            var sp = new StackPanel();
            sp.Children.Add(T(label, "MetricLabel"));
            sp.Children.Add(T(value, "MetricValue"));
            return sp;
        }

        // ================================================================ 视觉树
        public static T FindChild<T>(DependencyObject root) where T : DependencyObject
        {
            if (root == null) return null;
            int n = VisualTreeHelper.GetChildrenCount(root);
            for (int i = 0; i < n; i++)
            {
                var c = VisualTreeHelper.GetChild(root, i);
                var hit = c as T;
                if (hit != null) return hit;
                var deep = FindChild<T>(c);
                if (deep != null) return deep;
            }
            return null;
        }

        public static IEnumerable<T> FindAll<T>(DependencyObject root) where T : DependencyObject
        {
            var list = new List<T>();
            if (root == null) return list;
            int n = VisualTreeHelper.GetChildrenCount(root);
            for (int i = 0; i < n; i++)
            {
                var c = VisualTreeHelper.GetChild(root, i);
                var hit = c as T;
                if (hit != null) list.Add(hit);
                list.AddRange(FindAll<T>(c));
            }
            return list;
        }
    }
}
