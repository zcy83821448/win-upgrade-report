using System;
using System.Collections.Generic;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;

namespace WinUpd
{
    /// <summary>
    /// 毛玻璃底层：壁纸本体保持清晰，只把壁纸预先模糊一份，
    /// 再按每张卡片/标题栏的**屏幕矩形**裁出来垫在它们下面。
    ///
    /// 卡片滚走/翻页时，卡片位置的裁切会跟着重算（由外部在滚动/翻页帧里刷新），
    /// 但壁纸本身永远是清晰的那张，不会把整张图都糊掉。
    /// </summary>
    public sealed class FrostLayer : FrameworkElement
    {
        private readonly List<FrameworkElement> _targets = new List<FrameworkElement>();
        private BitmapSource _blurred;
        private double _corner = 14;

        public FrostLayer()
        {
            IsHitTestVisible = false;
            SnapsToDevicePixels = true;
            HorizontalAlignment = HorizontalAlignment.Stretch;
            VerticalAlignment = VerticalAlignment.Stretch;
            RenderOptions.SetBitmapScalingMode(this, BitmapScalingMode.LowQuality);
        }

        public bool HasBackdrop { get { return _blurred != null; } }

        public void ClearTargets()
        {
            _targets.Clear();
        }

        public void AddTarget(FrameworkElement el)
        {
            if (el == null || _targets.Contains(el)) return;
            _targets.Add(el);
        }

        public void SetCorner(double corner)
        {
            _corner = corner;
        }

        public void SetBackdrop(BitmapSource blurred)
        {
            _blurred = blurred;
            InvalidateVisual();
        }

        public void Refresh()
        {
            if (_blurred != null) InvalidateVisual();
        }

        protected override void OnRender(DrawingContext dc)
        {
            if (_blurred == null || ActualWidth < 1 || ActualHeight < 1) return;
            Visual root = Parent as Visual;
            if (root == null) return;
            var imageRect = new Rect(0, 0, ActualWidth, ActualHeight);

            foreach (var target in _targets)
            {
                if (target == null || !target.IsVisible) continue;
                // 翻页时页面会整体淡出/淡入：玻璃补丁必须跟页面用同一个透明度，
                // 否则卡片已经变透明了，它底下的模糊色块还在，看起来就是"颜色没跟上"。
                double alpha = EffectiveOpacity(target, root);
                if (alpha < 0.01) continue;

                Rect r;
                try
                {
                    // 目标（卡片/标题栏）和 FrostLayer 是兄弟节点，祖先要取它们的共同父级（Root），
                    // 不能用 TransformToAncestor(this)——那样会抛异常导致整层什么都不画。
                    Point p = target.TransformToAncestor(root).Transform(new Point(0, 0));
                    r = new Rect(p, target.RenderSize);
                }
                catch { continue; }
                if (r.Width < 1 || r.Height < 1) continue;
                if (r.Right < 0 || r.Bottom < 0 || r.Left > ActualWidth || r.Top > ActualHeight)
                    continue;
                double corner = Math.Min(_corner, Math.Min(r.Width, r.Height) / 2);
                Geometry clip = new RectangleGeometry(r, corner, corner);

                // 卡片如果在某个 ScrollViewer 里，滚动时会被裁到滚动区可视边界；
                // 毛玻璃也必须按同一块可视区裁，否则卡片滚出边界后色块会漏到页头空白里。
                var sv = FindScrollOwner(target);
                if (sv != null)
                {
                    try
                    {
                        Point sp = sv.TransformToAncestor(root).Transform(new Point(0, 0));
                        var viewport = new Rect(sp, sv.RenderSize);
                        if (viewport.Width < 1 || viewport.Height < 1) continue;
                        clip = new CombinedGeometry(GeometryCombineMode.Intersect, clip,
                            new RectangleGeometry(viewport));
                    }
                    catch { }
                }
                clip.Freeze();

                if (alpha < 0.999) dc.PushOpacity(alpha);
                dc.PushClip(clip);
                dc.DrawImage(_blurred, imageRect);
                dc.Pop();
                if (alpha < 0.999) dc.Pop();
            }
        }

        /// <summary>沿视觉树把祖先的 Opacity 乘起来（翻页淡入淡出挂在页面根节点上）。</summary>
        private static double EffectiveOpacity(DependencyObject target, Visual root)
        {
            double a = 1.0;
            DependencyObject cur = target;
            while (cur != null && !ReferenceEquals(cur, root))
            {
                var ui = cur as UIElement;
                if (ui != null) a *= ui.Opacity;
                cur = VisualTreeHelper.GetParent(cur);
            }
            return a;
        }

        /// <summary>找卡片所在的最近一个 ScrollViewer（用来取滚动可视区）。</summary>
        private static ScrollViewer FindScrollOwner(DependencyObject el)
        {
            DependencyObject cur = el;
            while (cur != null)
            {
                cur = VisualTreeHelper.GetParent(cur);
                var sv = cur as ScrollViewer;
                if (sv != null) return sv;
            }
            return null;
        }
    }
}
