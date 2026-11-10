namespace WinUpd
{
    /// <summary>
    /// 整套界面的度量标准。只认这一组数，任何页面都不许随手写 7、9、11、18 这类"感觉值"。
    ///
    /// 间距：斐波那契 4 / 6 / 10 / 16 / 26 / 42，相邻两项之比趋近 φ=1.618，
    ///       所以从 4 到 42 会自然形成疏密节奏，而不是均匀网格的机械感。
    /// 层次：页面标题 27 → 卡片标题 15 → 正文 13.5 → 辅助 12.5 → 标注 11.5，
    ///       每级相差约 φ 的 1/2 或 1 次幂，保证一眼能分出主次。
    /// 比例：并排两栏固定 1 : 1.618，内容最大宽度 880（约 44 个汉字，阅读舒适）。
    /// </summary>
    public static class D
    {
        public const double Phi = 1.6180339887;

        // ---- 间距梯度（斐波那契）----
        public const double S1 = 4;
        public const double S2 = 6;
        public const double S3 = 10;
        public const double S4 = 16;
        public const double S5 = 26;
        public const double S6 = 42;

        // ---- 页面骨架 ----
        public const double PagePadL = 42;
        public const double PagePadR = 34;
        public const double PagePadT = 24;
        public const double PagePadB = 42;
        public const double ContentMax = 880;
        public const double Sidebar = 232;
        public const double Titlebar = 44;

        // ---- 卡片 ----
        public const double CardPad = 26;
        public const double CardPadTight = 16;
        public const double CardGap = 16;
        public const double SectionGap = 42;

        // ---- 字号 ----
        public const double Micro = 11.5;
        public const double Small = 12.5;
        public const double Body = 13.5;
        public const double Subhead = 15;
        public const double H2 = 19;
        public const double H1 = 27;

        // ---- 圆角 ----
        public const double RadiusCard = 14;
        public const double RadiusCtrl = 8;
        public const double RadiusChip = 6;

        // ---- 两栏比例 ----
        public const double LeftRatio = 1;
        public const double RightRatio = Phi;
    }
}
