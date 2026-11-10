using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;

namespace WinUpd
{
    /// <summary>
    /// 圆角卡片容器。
    ///
    /// WPF 的 Border.CornerRadius 只影响它自己画的背景/描边，**不会裁剪子元素**：
    /// 卡片里那种"贴边的一像素分割线"（表格行底边、列表项底边）会一直是直的，
    /// 到卡片底部圆角那里就冲出圆弧，看起来像一根线戳出卡片。
    /// 这里在每次排版后按真实尺寸给自身加一个圆角 Clip，子元素一并被裁进圆角里。
    /// </summary>
    public sealed class ClipBorder : Border
    {
        protected override Size ArrangeOverride(Size finalSize)
        {
            Size size = base.ArrangeOverride(finalSize);
            UpdateClip(size);
            return size;
        }

        private void UpdateClip(Size size)
        {
            if (size.Width <= 0.5 || size.Height <= 0.5)
            {
                Clip = null;
                return;
            }
            CornerRadius cr = CornerRadius;
            double radius = Math.Max(
                Math.Max(cr.TopLeft, cr.TopRight),
                Math.Max(cr.BottomLeft, cr.BottomRight));
            if (radius <= 0.5)
            {
                Clip = null;
                return;
            }
            radius = Math.Min(radius, Math.Min(size.Width, size.Height) / 2);
            var clip = new RectangleGeometry(
                new Rect(0, 0, size.Width, size.Height), radius, radius);
            clip.Freeze();
            Clip = clip;
        }
    }
}
