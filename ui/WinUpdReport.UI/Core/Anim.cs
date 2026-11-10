using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace WinUpd
{
    /// <summary>
    /// 三次贝塞尔缓动，参数和 CSS cubic-bezier 完全一致。
    /// 这样界面里的动效可以按"设计稿语言"描述：标准 (0.2,0,0,1)、减速 (0.05,0.7,0.1,1)……
    /// </summary>
    public sealed class BezierEase : EasingFunctionBase
    {
        private readonly double _x1, _y1, _x2, _y2;

        public BezierEase(double x1, double y1, double x2, double y2)
        {
            _x1 = x1; _y1 = y1; _x2 = x2; _y2 = y2;
        }

        protected override Freezable CreateInstanceCore()
        {
            return new BezierEase(_x1, _y1, _x2, _y2);
        }

        protected override double EaseInCore(double t)
        {
            double u = t;
            for (int i = 0; i < 10; i++)
            {
                double x = Cubic(_x1, _x2, u) - t;
                if (Math.Abs(x) < 1e-5) break;
                double dx = CubicD(_x1, _x2, u);
                if (Math.Abs(dx) < 1e-6) break;
                u -= x / dx;
                if (u < 0) u = 0;
                if (u > 1) u = 1;
            }
            return Cubic(_y1, _y2, u);
        }

        private static double Cubic(double a, double b, double u)
        {
            double v = 1 - u;
            return 3 * v * v * u * a + 3 * v * u * u * b + u * u * u;
        }

        private static double CubicD(double a, double b, double u)
        {
            double v = 1 - u;
            return 3 * v * v * a + 6 * v * u * (b - a) + 3 * u * u * (1 - b);
        }
    }

    /// <summary>
    /// 统一的动效语言。原则：
    /// 1) 直接操作的反馈要快（90–150ms），空间变化（翻页、导航）才用 220–340ms；
    /// 2) 同一类动作永远用同一条缓动曲线，用户能"预判"界面怎么动；
    /// 3) 只有明确的"物体"（指示条、卡槽、滑块）才允许轻微回弹，文字一律不做缩放/位移。
    /// </summary>
    public static class Anim
    {
        public static bool Enabled = true;

        // 时长令牌
        public const int Instant = 90;
        public const int Fast = 150;
        public const int Base = 220;
        public const int Slow = 300;
        public const int Enter = 340;

        public static IEasingFunction Standard { get { return new BezierEase(0.2, 0, 0, 1); } }
        public static IEasingFunction Decelerate { get { return new BezierEase(0.05, 0.7, 0.1, 1); } }
        public static IEasingFunction Accelerate { get { return new BezierEase(0.3, 0, 0.8, 0.16); } }
        public static IEasingFunction Soft { get { return new CubicEase { EasingMode = EasingMode.EaseOut }; } }

        /// <summary>带回弹的缓动，只给"物体"用（开关拇指、指示条），不给文字用。</summary>
        public static IEasingFunction Spring
        {
            get { return new BackEase { Amplitude = 0.3, EasingMode = EasingMode.EaseOut }; }
        }

        public static void Animate(IAnimatable target, DependencyProperty prop,
            double from, double to, int ms, IEasingFunction ease = null, int delayMs = 0,
            bool forever = false, bool autoReverse = false)
        {
            if (target == null) return;
            if (!Enabled && !forever)
            {
                var d = target as DependencyObject;
                if (d != null)
                {
                    target.BeginAnimation(prop, null);
                    d.SetValue(prop, to);
                }
                return;
            }
            var anim = new DoubleAnimation(from, to, TimeSpan.FromMilliseconds(ms))
            {
                EasingFunction = ease ?? Standard,
                BeginTime = TimeSpan.FromMilliseconds(delayMs)
            };
            if (forever)
            {
                anim.RepeatBehavior = RepeatBehavior.Forever;
                anim.AutoReverse = autoReverse;
            }
            target.BeginAnimation(prop, anim);
        }

        public static void Fade(UIElement el, double from, double to, int ms)
        {
            if (el == null) return;
            Animate(el, UIElement.OpacityProperty, from, to, ms, Standard);
        }

        /// <summary>淡入 + 轻微上浮。只用于整块内容，不用于行内文字。</summary>
        public static void FadeSlideIn(FrameworkElement el, int ms = 260,
            int delayMs = 0, double fromY = 8)
        {
            if (el == null) return;
            el.Opacity = 0;
            var tt = new TranslateTransform(0, fromY);
            el.RenderTransform = tt;
            Animate(el, UIElement.OpacityProperty, 0, 1, ms, Decelerate, delayMs);
            Animate(tt, TranslateTransform.YProperty, fromY, 0, ms + 60, Standard, delayMs);
        }

        /// <summary>页面里的卡片依次入场；同时最多 8 块，间隔 22ms，不让人等。</summary>
        public static void StaggerIn(Panel panel, int startMs = 0, int stepMs = 22,
            double fromY = 8)
        {
            if (panel == null) return;
            int i = 0;
            foreach (UIElement child in panel.Children)
            {
                var fe = child as FrameworkElement;
                if (fe == null) continue;
                FadeSlideIn(fe, 280, startMs + i * stepMs, fromY);
                i++;
                if (i >= 8) break;
            }
        }

        /// <summary>翻页入场：direction=1 从下往上来（往后翻），-1 从上往下走（往前翻），0 只淡入。</summary>
        public static void PageIn(FrameworkElement el, int direction)
        {
            if (el == null) return;
            double d = direction == 0 ? 0 : 14 * Math.Sign(direction);
            el.Opacity = 0;
            var tt = new TranslateTransform(0, d);
            el.RenderTransform = tt;
            Animate(el, UIElement.OpacityProperty, 0, 1, Base, Decelerate);
            if (d != 0)
                Animate(tt, TranslateTransform.YProperty, d, 0, Enter, Standard);
        }

        /// <summary>翻页退场：朝相反方向让位，比入场快，注意力始终在新页上。</summary>
        public static void PageOut(FrameworkElement el, int direction)
        {
            if (el == null) return;
            double d = direction == 0 ? 0 : -10 * Math.Sign(direction);
            var tt = new TranslateTransform(0, 0);
            el.RenderTransform = tt;
            Animate(el, UIElement.OpacityProperty, 1, 0, 130, Accelerate);
            if (d != 0)
                Animate(tt, TranslateTransform.YProperty, 0, d, Fast, Accelerate);
        }

        public static void ToastIn(FrameworkElement el)
        {
            if (el == null) return;
            el.Opacity = 0;
            var tt = new TranslateTransform(22, 0);
            el.RenderTransform = tt;
            Animate(el, UIElement.OpacityProperty, 0, 1, Fast, Decelerate);
            Animate(tt, TranslateTransform.XProperty, 22, 0, Slow, Spring);
        }

        public static void ToastOut(FrameworkElement el, Action done)
        {
            if (el == null) { if (done != null) done(); return; }
            var tt = el.RenderTransform as TranslateTransform;
            if (tt == null) { tt = new TranslateTransform(); el.RenderTransform = tt; }
            Animate(el, UIElement.OpacityProperty, 1, 0, Fast, Accelerate);
            var slide = new DoubleAnimation(0, 14, TimeSpan.FromMilliseconds(Fast))
            {
                EasingFunction = Accelerate
            };
            slide.Completed += (s, e) => { if (done != null) done(); };
            tt.BeginAnimation(TranslateTransform.XProperty, slide);
        }

        /// <summary>状态点呼吸。</summary>
        public static void Pulse(UIElement el, double min = 0.4, int ms = 1600)
        {
            if (el == null) return;
            el.BeginAnimation(UIElement.OpacityProperty,
                new DoubleAnimation(1, min, TimeSpan.FromMilliseconds(ms))
                {
                    EasingFunction = Standard,
                    RepeatBehavior = RepeatBehavior.Forever,
                    AutoReverse = true
                });
        }

        /// <summary>窗口首次出现：只淡入 + 6px 上浮，不做缩放，避免首帧文字发虚。</summary>
        public static void WindowIn(FrameworkElement root)
        {
            if (root == null) return;
            root.Opacity = 0;
            var tt = new TranslateTransform(0, 6);
            root.RenderTransform = tt;
            Animate(root, UIElement.OpacityProperty, 0, 1, Base, Decelerate);
            Animate(tt, TranslateTransform.YProperty, 6, 0, Slow, Standard);
        }

        /// <summary>底部活动条：从下方滑入，不改变页面布局（不推挤内容）。</summary>
        public static void ActivityIn(FrameworkElement bar)
        {
            if (bar == null) return;
            bar.Visibility = Visibility.Visible;
            bar.Opacity = 0;
            var tt = bar.RenderTransform as TranslateTransform;
            if (tt == null) { tt = new TranslateTransform(); bar.RenderTransform = tt; }
            tt.Y = 12;
            Animate(bar, UIElement.OpacityProperty, 0, 1, Fast, Decelerate);
            Animate(tt, TranslateTransform.YProperty, 12, 0, Base, Standard);
        }

        public static void ActivityOut(FrameworkElement bar, Action done)
        {
            if (bar == null) { if (done != null) done(); return; }
            var tt = bar.RenderTransform as TranslateTransform;
            if (tt == null) { tt = new TranslateTransform(); bar.RenderTransform = tt; }
            Animate(bar, UIElement.OpacityProperty, 1, 0, Fast, Accelerate);
            var slide = new DoubleAnimation(0, 10, TimeSpan.FromMilliseconds(Fast))
            {
                EasingFunction = Accelerate
            };
            slide.Completed += (s, e) =>
            {
                bar.Visibility = Visibility.Collapsed;
                if (done != null) done();
            };
            tt.BeginAnimation(TranslateTransform.YProperty, slide);
        }

        /// <summary>浮层（报告阅读器）出现/消失。</summary>
        public static void OverlayIn(UIElement scrim, FrameworkElement panel)
        {
            if (scrim != null)
            {
                scrim.Visibility = Visibility.Visible;
                scrim.Opacity = 0;
                Animate(scrim, UIElement.OpacityProperty, 0, 1, Base, Standard);
            }
            if (panel != null)
            {
                var tt = new TranslateTransform(0, 16);
                panel.RenderTransform = tt;
                Animate(panel, UIElement.OpacityProperty, 0, 1, Base, Decelerate);
                Animate(tt, TranslateTransform.YProperty, 16, 0, Slow, Standard);
            }
        }

        public static void OverlayOut(UIElement scrim, FrameworkElement panel, Action done)
        {
            if (scrim != null) Animate(scrim, UIElement.OpacityProperty, 1, 0, Fast, Accelerate);
            if (panel != null)
            {
                var tt = panel.RenderTransform as TranslateTransform;
                if (tt == null) { tt = new TranslateTransform(); panel.RenderTransform = tt; }
                Animate(panel, UIElement.OpacityProperty, 1, 0, Fast, Accelerate);
                var slide = new DoubleAnimation(0, 10, TimeSpan.FromMilliseconds(Fast))
                { EasingFunction = Accelerate };
                slide.Completed += (s, e) =>
                {
                    if (scrim != null) scrim.Visibility = Visibility.Collapsed;
                    if (done != null) done();
                };
                tt.BeginAnimation(TranslateTransform.YProperty, slide);
            }
            else if (done != null) done();
        }
    }
}
