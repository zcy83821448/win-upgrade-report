using System;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Animation;

namespace WinUpd
{
    /// <summary>
    /// 分段选择器：选中项下面有一块白色"滑块"，切换时滑块平滑移到新位置并跟着文字宽度变化。
    /// 这样切换动作有连续的方向感，而不是每项自己闪一下背景。
    /// </summary>
    public sealed class SegmentedBox : Border
    {
        private readonly Grid _grid = new Grid();
        private readonly Border _thumb;
        private readonly StackPanel _items = new StackPanel { Orientation = Orientation.Horizontal };
        private readonly TranslateTransform _move = new TranslateTransform(0, 0);
        private readonly RadioButton[] _buttons;
        private string _value;
        private bool _ready;

        public SegmentedBox(string[] options, string value, Action<string> onChange)
        {
            Style = (Style)Application.Current.Resources["SegBox"];
            _value = value;

            _thumb = new Border
            {
                Style = (Style)Application.Current.Resources["SegThumb"],
                Width = 0,
                RenderTransform = _move
            };
            _grid.Children.Add(_thumb);

            _buttons = new RadioButton[options.Length];
            string group = "seg" + Guid.NewGuid().ToString("N");
            for (int i = 0; i < options.Length; i++)
            {
                string opt = options[i];
                var rb = new RadioButton
                {
                    Content = opt,
                    GroupName = group,
                    IsChecked = opt == value,
                    Style = (Style)Application.Current.Resources["SegItem"],
                    Tag = opt
                };
                rb.Checked += (s, e) =>
                {
                    _value = Convert.ToString(((RadioButton)s).Tag);
                    Place(true);
                    if (onChange != null) onChange(_value);
                };
                _buttons[i] = rb;
                _items.Children.Add(rb);
            }
            _grid.Children.Add(_items);
            Child = _grid;

            Loaded += (s, e) => { _ready = true; Place(false); };
            SizeChanged += (s, e) => Place(false);
        }

        /// <summary>外部改值（不触发回调）。</summary>
        public void SetValue(string value)
        {
            _value = value;
            foreach (var rb in _buttons)
            {
                if (Convert.ToString(rb.Tag) == value && rb.IsChecked != true)
                {
                    rb.IsChecked = true;
                    return;
                }
            }
        }

        private void Place(bool animate)
        {
            int index = -1;
            for (int i = 0; i < _buttons.Length; i++)
            {
                if (_buttons[i].IsChecked == true) { index = i; break; }
            }
            if (index < 0) index = 0;
            var rb = _buttons[index];
            if (!_ready || rb.ActualWidth <= 0)
            {
                Dispatcher.BeginInvoke(new Action(() =>
                {
                    if (IsLoaded) Place(false);
                }), System.Windows.Threading.DispatcherPriority.Loaded);
                return;
            }
            Point p = rb.TranslatePoint(new Point(0, 0), _grid);
            double w = rb.ActualWidth;
            if (!animate || !Anim.Enabled)
            {
                _move.BeginAnimation(TranslateTransform.XProperty, null);
                _move.X = p.X;
                _thumb.BeginAnimation(WidthProperty, null);
                _thumb.Width = w;
                return;
            }
            Anim.Animate(_move, TranslateTransform.XProperty, _move.X, p.X,
                Anim.Base, Anim.Standard);
            Anim.Animate(_thumb, WidthProperty, _thumb.ActualWidth, w,
                Anim.Base, Anim.Standard);
        }
    }
}
