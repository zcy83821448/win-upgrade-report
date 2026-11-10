using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Documents;
using System.Windows.Media;

namespace WinUpd
{
    /// <summary>把服务端解析好的报告块渲染成原生 FlowDocument（无 WebView2）。</summary>
    public static class ReportRenderer
    {
        private static readonly Brush Ink = BrushOf("InkBrush");
        private static readonly Brush Ink2 = BrushOf("Ink2Brush");
        private static readonly Brush Ink3 = BrushOf("Ink3Brush");
        private static readonly Brush Line = BrushOf("LineBrush");
        private static readonly Brush Accent = BrushOf("AccentBrush");
        private static readonly Brush Soft = BrushOf("AccentSoftBrush");
        private static readonly FontFamily UiFont = (FontFamily)Application.Current.Resources["UiFont"];
        private static readonly FontFamily MonoFont = (FontFamily)Application.Current.Resources["MonoFont"];

        private static Brush BrushOf(string key)
        {
            return (Brush)Application.Current.Resources[key];
        }

        public static FlowDocument Message(string text)
        {
            var doc = Base();
            doc.Blocks.Add(Paragraph(text, 13, Ink2, new Thickness(6, 26, 0, 0)));
            return doc;
        }

        public static FlowDocument Error(string text)
        {
            var doc = Base();
            var p = Paragraph(text, 13, BrushOf("BadBrush"), new Thickness(6, 26, 0, 0));
            doc.Blocks.Add(p);
            return doc;
        }

        private static FlowDocument Base()
        {
            return new FlowDocument
            {
                PagePadding = new Thickness(0),
                FontFamily = UiFont,
                FontSize = 14,
                Foreground = Ink,
                LineHeight = 24,
                TextAlignment = TextAlignment.Left,
                ColumnWidth = double.PositiveInfinity
            };
        }

        public static FlowDocument Build(List<Dictionary<string, object>> blocks)
        {
            var doc = Base();
            if (blocks == null) return doc;
            foreach (var b in blocks)
            {
                string t = Json.Str(b, "t");
                switch (t)
                {
                    case "h":
                        AddHeading(doc, b);
                        break;
                    case "p":
                        var p = ParagraphSpans(Json.DictList(b, "spans"));
                        p.Margin = new Thickness(0, 8, 0, 0);
                        doc.Blocks.Add(p);
                        break;
                    case "ul":
                        doc.Blocks.Add(BuildList(b, false));
                        break;
                    case "ol":
                        doc.Blocks.Add(BuildList(b, true));
                        break;
                    case "quote":
                        var q = ParagraphSpans(Json.DictList(b, "spans"));
                        q.Background = Soft;
                        q.BorderBrush = Accent;
                        q.BorderThickness = new Thickness(3, 0, 0, 0);
                        q.Padding = new Thickness(12, 8, 12, 8);
                        q.Margin = new Thickness(0, 10, 0, 4);
                        doc.Blocks.Add(q);
                        break;
                    case "code":
                        doc.Blocks.Add(CodeBlock(Json.Str(b, "text")));
                        break;
                    case "hr":
                        var hr = new Paragraph
                        {
                            Margin = new Thickness(0, 18, 0, 18),
                            BorderBrush = Line,
                            BorderThickness = new Thickness(0, 0, 0, 1)
                        };
                        doc.Blocks.Add(hr);
                        break;
                    case "table":
                        doc.Blocks.Add(BuildTable(b));
                        break;
                }
            }
            return doc;
        }

        private static void AddHeading(FlowDocument doc, Dictionary<string, object> b)
        {
            int level = Json.Int(b, "level", 2);
            var p = ParagraphSpans(Json.DictList(b, "spans"));
            if (level <= 1)
            {
                p.FontSize = 23;
                p.FontWeight = FontWeights.SemiBold;
                p.Margin = new Thickness(0, 0, 0, 6);
            }
            else if (level == 2)
            {
                p.FontSize = 18;
                p.FontWeight = FontWeights.SemiBold;
                p.Margin = new Thickness(0, 22, 0, 8);
                p.BorderBrush = Line;
                p.BorderThickness = new Thickness(0, 0, 0, 1);
                p.Padding = new Thickness(0, 0, 0, 6);
            }
            else
            {
                p.FontSize = 15.5;
                p.FontWeight = FontWeights.SemiBold;
                p.Margin = new Thickness(0, 16, 0, 4);
            }
            doc.Blocks.Add(p);
        }

        private static List<Dictionary<string, object>> ParseSpans(object raw)
        {
            var list = new List<Dictionary<string, object>>();
            var en = raw as System.Collections.IEnumerable;
            if (en == null || raw is string) return list;
            foreach (object o in en)
            {
                var d = o as Dictionary<string, object>;
                if (d != null) list.Add(d);
            }
            return list;
        }

        private static List BuildList(Dictionary<string, object> b, bool ordered)
        {
            var list = new List
            {
                MarkerStyle = ordered ? TextMarkerStyle.Decimal : TextMarkerStyle.Disc,
                Margin = new Thickness(0, 8, 0, 0),
                Padding = new Thickness(24, 0, 0, 0)
            };
            var rawItems = Json.Get(b, "items") as System.Collections.IEnumerable;
            if (rawItems != null)
            {
                foreach (object item in rawItems)
                {
                    var p = ParagraphSpans(ParseSpans(item));
                    p.Margin = new Thickness(0, 3, 0, 0);
                    list.ListItems.Add(new ListItem(p));
                }
            }
            return list;
        }

        private static Block CodeBlock(string text)
        {
            var tb = new TextBox
            {
                Text = text ?? "",
                IsReadOnly = true,
                BorderThickness = new Thickness(0),
                Background = Brushes.Transparent,
                FontFamily = MonoFont,
                FontSize = 12.5,
                Foreground = Ink,
                TextWrapping = TextWrapping.NoWrap,
                HorizontalScrollBarVisibility = ScrollBarVisibility.Auto,
                VerticalScrollBarVisibility = ScrollBarVisibility.Disabled,
                Padding = new Thickness(0)
            };
            var border = new Border
            {
                Background = new SolidColorBrush(Color.FromRgb(0xF7, 0xF8, 0xFA)),
                BorderBrush = Line,
                BorderThickness = new Thickness(1),
                CornerRadius = new CornerRadius(9),
                Padding = new Thickness(14, 11, 14, 11),
                Margin = new Thickness(0, 10, 0, 2),
                Child = tb
            };
            var container = new BlockUIContainer(border);
            return container;
        }

        private static Table BuildTable(Dictionary<string, object> b)
        {
            var table = new Table
            {
                CellSpacing = 0,
                Margin = new Thickness(0, 12, 0, 6)
            };
            var headCells = new List<List<Dictionary<string, object>>>();
            var rawHead = Json.Get(b, "head") as System.Collections.IEnumerable;
            if (rawHead != null && !(rawHead is string))
            {
                foreach (object cell in rawHead)
                    headCells.Add(ParseSpans(cell));
            }
            int cols = Math.Max(1, headCells.Count);
            if (headCells.Count > 0)
            {
                var headerGroup = new TableRowGroup();
                var tr = new TableRow
                {
                    Background = new SolidColorBrush(Color.FromRgb(0xF7, 0xF8, 0xFA))
                };
                foreach (var cell in headCells)
                    tr.Cells.Add(TableCellEl(cell, true));
                headerGroup.Rows.Add(tr);
                table.RowGroups.Add(headerGroup);
            }
            var bodyGroup = new TableRowGroup();
            var rawRows = Json.Get(b, "rows") as System.Collections.IEnumerable;
            if (rawRows != null && !(rawRows is string))
            {
                foreach (object rawRow in rawRows)
                {
                    var rowEnum = rawRow as System.Collections.IEnumerable;
                    if (rowEnum == null) continue;
                    var tr = new TableRow();
                    foreach (object rawCell in rowEnum)
                    {
                        var cellSpans = ParseSpans(rawCell);
                        tr.Cells.Add(TableCellEl(cellSpans, false));
                    }
                    while (tr.Cells.Count < cols) tr.Cells.Add(TableCellEl(null, false));
                    bodyGroup.Rows.Add(tr);
                }
            }
            table.RowGroups.Add(bodyGroup);
            for (int i = 0; i < cols; i++)
                table.Columns.Add(new TableColumn());
            return table;
        }

        private static TableCell TableCellEl(List<Dictionary<string, object>> spans, bool header)
        {
            var p = ParagraphSpans(spans);
            p.FontSize = 13;
            if (header)
            {
                p.FontWeight = FontWeights.SemiBold;
                p.Foreground = Ink2;
            }
            var cell = new TableCell(p)
            {
                BorderBrush = Line,
                BorderThickness = new Thickness(1),
                Padding = new Thickness(9, 6, 9, 6)
            };
            return cell;
        }

        private static Paragraph Paragraph(string text, double size, Brush fg, Thickness margin)
        {
            var p = new Paragraph(new Run(text ?? ""))
            {
                FontSize = size,
                Foreground = fg,
                Margin = margin
            };
            return p;
        }

        private static Paragraph ParagraphSpans(List<Dictionary<string, object>> spans)
        {
            var p = new Paragraph();
            if (spans == null) return p;
            foreach (var span in spans)
            {
                string kind = Json.Str(span, "t");
                string text = Json.Str(span, "v");
                switch (kind)
                {
                    case "code":
                        p.Inlines.Add(new Run(text)
                        {
                            FontFamily = MonoFont,
                            FontSize = 12.5,
                            Background = new SolidColorBrush(Color.FromRgb(0xF0, 0xF2, 0xF5)),
                            Foreground = Ink
                        });
                        break;
                    case "b":
                        p.Inlines.Add(new Run(text) { FontWeight = FontWeights.SemiBold });
                        break;
                    case "i":
                        p.Inlines.Add(new Run(text) { FontStyle = FontStyles.Italic });
                        break;
                    case "s":
                        p.Inlines.Add(new Run(text) { TextDecorations = TextDecorations.Strikethrough });
                        break;
                    case "a":
                        string href = Json.Str(span, "href");
                        var link = new Hyperlink(new Run(text)) { Foreground = Accent };
                        if (!string.IsNullOrEmpty(href))
                        {
                            link.NavigateUri = SafeUri(href);
                            link.RequestNavigate += (s, e) =>
                            {
                                try { Process.Start(new ProcessStartInfo(href) { UseShellExecute = true }); }
                                catch { }
                            };
                        }
                        p.Inlines.Add(link);
                        break;
                    default:
                        p.Inlines.Add(new Run(text));
                        break;
                }
            }
            return p;
        }

        private static Uri SafeUri(string href)
        {
            Uri u;
            if (Uri.TryCreate(href, UriKind.Absolute, out u)) return u;
            return new Uri("https://example.invalid");
        }
    }
}

