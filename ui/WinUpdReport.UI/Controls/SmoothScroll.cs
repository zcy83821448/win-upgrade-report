using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Media;

namespace WinUpd
{
    /// <summary>
    /// 鼠标滚轮平滑滚动（跟手优先）。
    ///
    /// 关键点：每收到一格滚轮，先把约 45% 的距离**立刻**滚过去（保证"跟手"），
    /// 剩下的距离由每渲染帧的指数逼近（时间常数约 45ms）顺完。
    /// 连续滚动时不再"重新开始一段动画"，而是不断抬高目标、以固定时间常数追——
    /// 所以滚轮滚多远，画面就同步跟多远，不会出现"等滚轮停了才滚过去"。
    ///
    /// 其余：
    ///  - 直接改 ScrollViewer 的真实偏移，滚动条/裁剪/嵌套滚动都是原生行为，方向不会反；
    ///  - 用户一拖滚动条/点轨道立刻停下，且不跳到旧目标（不抢）；
    ///  - 鼠标所在层滚到头后让给外层滚动区；
    ///  - Ctrl / Shift 不接管。
    /// </summary>
    public static class SmoothScroll
    {
        private sealed class State
        {
            public ScrollViewer Owner;
            public double Target;
        }

        private static readonly Dictionary<ScrollViewer, State> Map =
            new Dictionary<ScrollViewer, State>();
        private static readonly List<State> Active = new List<State>();

        private static bool _hooked;
        private static double _lastFrame;
        private static readonly Stopwatch Clock = Stopwatch.StartNew();

        private const double ImmediateFactor = 0.45; // 每个滚轮事件立刻走掉的比例
        private const double Tau = 0.045;            // 剩余距离的跟随时间常数（秒）

        /// <summary>平滑滚动期间每一渲染帧（主窗口用来让卡片玻璃跟手）。</summary>
        public static event Action FrameTick;

        /// <summary>当前是否正在追滚轮目标（主窗口用来跳过重复的毛玻璃刷新）。</summary>
        public static bool IsAnimating { get { return Active.Count > 0; } }

        public static void Attach(UIElement root)
        {
            root.PreviewMouseWheel += OnPreviewWheel;
        }

        private static void OnPreviewWheel(object sender, MouseWheelEventArgs e)
        {
            if (e.Delta == 0 || !Anim.Enabled) return;
            if ((Keyboard.Modifiers & (ModifierKeys.Control | ModifierKeys.Shift)) != 0) return;
            int lines = SystemParameters.WheelScrollLines;
            if (lines == 0) return;

            int direction = e.Delta > 0 ? -1 : 1;
            var sv = PickScroller(e.OriginalSource as DependencyObject, direction);
            if (sv == null) return;

            State st = GetState(sv);
            double step = lines < 0 ? sv.ViewportHeight * 0.9 : Math.Max(44, lines * 22);
            double notches = Math.Abs(e.Delta) / 120.0;
            double max = Math.Max(0, sv.ScrollableHeight);
            bool active = Active.Contains(st);
            double current = active ? st.Target : sv.VerticalOffset;
            double next = current + direction * step * notches;
            if (next < 0) next = 0;
            if (next > max) next = max;
            if (Math.Abs(next - current) < 0.5 && !active) return;

            st.Target = next;

            // 先吃掉一大半，保证滚轮一动手画面就跟着动（这是"跟手"的关键）
            double offset = sv.VerticalOffset + (next - current) * ImmediateFactor;
            if (offset < 0) offset = 0;
            if (offset > max) offset = max;
            sv.ScrollToVerticalOffset(offset);
            if (!active) Active.Add(st);
            Hook();
            e.Handled = true;
        }

        private static readonly DependencyProperty WiredProperty =
            DependencyProperty.RegisterAttached("Wired", typeof(bool),
                typeof(SmoothScroll), new PropertyMetadata(false));

        private static State GetState(ScrollViewer sv)
        {
            State st;
            if (Map.TryGetValue(sv, out st)) return st;
            // 页面重建会丢掉旧的 ScrollViewer，但它们一直被 Map 强引用着（还带着事件
            // 处理器），开久了就是慢性内存增长。攒到一定数量就顺手清一遍。
            if (Map.Count >= 16) Prune();
            st = new State { Owner = sv };
            Map[sv] = st;
            // 事件只挂一次（状态存在控件自己的附加属性上）：被 Prune 掉以后再滚回来时
            // 不会被重复挂一遍。处理器里按当前状态查，不捕获某一次的 State。
            if (!(bool)sv.GetValue(WiredProperty))
            {
                sv.SetValue(WiredProperty, true);
                // 用户一碰滚动条（拖拇指 / 点轨道）就停下，保持当前偏移不抢
                sv.AddHandler(Thumb.DragStartedEvent,
                    new DragStartedEventHandler((s, e) => StopCurrent(sv)), true);
                sv.PreviewMouseDown += (s, e) =>
                {
                    if (FindScrollBar(e.OriginalSource as DependencyObject) != null)
                        StopCurrent(sv);
                };
            }
            return st;
        }

        private static void StopCurrent(ScrollViewer sv)
        {
            State st;
            if (sv != null && Map.TryGetValue(sv, out st)) Stop(st);
        }

        /// <summary>扔掉已经不在任何窗口里的滚动区（页面被重建后留下的那些）。</summary>
        private static void Prune()
        {
            List<ScrollViewer> dead = null;
            foreach (var kv in Map)
            {
                ScrollViewer sv = kv.Key;
                if (sv == null || PresentationSource.FromVisual(sv) == null)
                {
                    if (dead == null) dead = new List<ScrollViewer>();
                    dead.Add(sv);
                }
            }
            if (dead == null) return;
            foreach (ScrollViewer sv in dead)
            {
                State st;
                if (Map.TryGetValue(sv, out st))
                {
                    Active.Remove(st);
                    Map.Remove(sv);
                }
            }
            if (Active.Count == 0) Unhook();
        }

        private static ScrollBar FindScrollBar(DependencyObject d)
        {
            while (d != null)
            {
                var sb = d as ScrollBar;
                if (sb != null) return sb;
                d = ParentOf(d);
            }
            return null;
        }

        /// <summary>视觉/内容元素都能安全往上走（FlowDocument 不是 Visual，直接 GetParent 会抛）。</summary>
        private static DependencyObject ParentOf(DependencyObject d)
        {
            if (d is Visual || d is System.Windows.Media.Media3D.Visual3D)
                return VisualTreeHelper.GetParent(d);
            var fce = d as FrameworkContentElement;
            if (fce != null) return fce.Parent;
            var ce = d as ContentElement;
            if (ce != null) return ContentOperations.GetParent(ce);
            return null;
        }

        private static void Hook()
        {
            if (_hooked) return;
            _hooked = true;
            _lastFrame = 0;
            CompositionTarget.Rendering += OnFrame;
        }

        private static void Unhook()
        {
            if (!_hooked) return;
            _hooked = false;
            CompositionTarget.Rendering -= OnFrame;
        }

        private static void OnFrame(object sender, EventArgs e)
        {
            double now = Clock.Elapsed.TotalSeconds;
            double dt = _lastFrame <= 0 ? 0.016 : now - _lastFrame;
            _lastFrame = now;
            if (dt < 0.004) dt = 0.004;
            if (dt > 0.05) dt = 0.05;
            double alpha = 1.0 - Math.Exp(-dt / Tau);

            State[] states = Active.ToArray();
            foreach (State st in states)
            {
                if (!Active.Contains(st)) continue;
                Step(st, alpha);
            }
            if (FrameTick != null) FrameTick();
            if (Active.Count == 0) Unhook();
        }

        private static void Step(State st, double alpha)
        {
            ScrollViewer sv = st.Owner;
            if (!sv.IsVisible) { Stop(st); return; }

            double max = Math.Max(0, sv.ScrollableHeight);
            double target = st.Target < 0 ? 0 : (st.Target > max ? max : st.Target);
            double current = sv.VerticalOffset;
            double diff = target - current;
            if (Math.Abs(diff) < 0.4)
            {
                sv.ScrollToVerticalOffset(target);
                Stop(st);
                return;
            }
            double off = current + diff * alpha;
            if (off < 0) off = 0;
            if (off > max) off = max;
            sv.ScrollToVerticalOffset(off);
        }

        private static void Stop(State st)
        {
            if (!Active.Remove(st)) return;
            if (FrameTick != null) FrameTick();
            if (Active.Count == 0) Unhook();
        }

        /// <summary>
        /// 从鼠标下的元素往祖先找：优先滚鼠标所在的那一层；
        /// 那一层往这个方向已经到头，就让给外层的滚动区。
        /// </summary>
        private static ScrollViewer PickScroller(DependencyObject source, int direction)
        {
            DependencyObject cur = source;
            while (cur != null)
            {
                var sv = cur as ScrollViewer;
                if (sv != null && sv.IsVisible && sv.ScrollableHeight > 0.5)
                {
                    State st;
                    double pos = Map.TryGetValue(sv, out st) && Active.Contains(st)
                        ? st.Target : sv.VerticalOffset;
                    if (direction > 0 && pos < sv.ScrollableHeight - 0.5) return sv;
                    if (direction < 0 && pos > 0.5) return sv;
                }
                cur = ParentOf(cur);
            }
            return null;
        }
    }
}
