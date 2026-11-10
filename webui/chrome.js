/* ============================================================
   窗口外壳逻辑（唯一来源）：最小化 / 最大化 / 关闭 / 八向缩放 / 拖动区双击
   设置窗口（app.js）和独立报告窗口（viewer.py 内联这同一份文件）共用。
   用法：
     WinUpdChrome.init({ onClose: fn })   // 省略 onClose 时调 window_close
     WinUpdChrome.setMaximized(bool)      // 轮询到窗口状态后同步 UI
   ============================================================ */
(function () {
  'use strict';

  function api() {
    return (window.pywebview && window.pywebview.api) || null;
  }

  function call(name, arg) {
    var a = api();
    if (!a || typeof a[name] !== 'function') return null;
    try {
      /* 无参方法必须真的不传参：pywebview 把 undefined 当成一个参数，
         Python 侧无参方法会 TypeError，按钮就"失灵了"。 */
      return arg === undefined ? a[name]() : a[name](arg);
    } catch (e) {
      return null;
    }
  }

  function callArgs(name, args) {
    var a = api();
    if (!a || typeof a[name] !== 'function') return null;
    try {
      return a[name].apply(a, args || []);
    } catch (e) {
      return null;
    }
  }

  /* 报告 iframe 里的链接：统一交给系统浏览器打开。
     不拦的话 WebView2 会按自己的方式开新窗口（甚至开出一个没有边框的怪窗口）。 */
  function wireFrame(frame) {
    if (!frame || frame.__winupdLinksWired) return;
    frame.__winupdLinksWired = true;
    frame.addEventListener('load', function () {
      var doc = null;
      try { doc = frame.contentDocument; } catch (e) { return; }
      if (!doc || doc.__winupdLinksHooked) return;
      doc.__winupdLinksHooked = true;
      doc.addEventListener('click', function (e) {
        var a = e.target && e.target.closest ? e.target.closest('a') : null;
        if (!a) return;
        var href = a.getAttribute('href') || '';
        if (!href || href.charAt(0) === '#') return;
        e.preventDefault();
        if (/^(https?:|file:)/i.test(href)) {
          callArgs('open_external', ['browser', href]);
        }
      }, true);
    });
  }

  function wireFrameLinks() {
    Array.prototype.forEach.call(document.querySelectorAll('iframe'), wireFrame);
  }

  function setMaximized(max) {
    var on = !!max;
    document.body.classList.toggle('is-maximized', on);
    var btn = document.getElementById('winMax');
    var use = btn ? btn.querySelector('use') : null;
    if (use) use.setAttribute('href', on ? '#i-win-restore' : '#i-win-max');
    if (btn) {
      btn.title = on ? '还原' : '最大化';
      btn.setAttribute('aria-label', on ? '还原' : '最大化');
    }
  }

  function toggleMax() {
    var r = call('window_toggle_max');
    if (r && r.then) {
      r.then(function (x) {
        if (x && typeof x.maximized === 'boolean') setMaximized(x.maximized);
      });
    }
  }

  function init(opts) {
    opts = opts || {};
    var min = document.getElementById('winMin');
    var max = document.getElementById('winMax');
    var closeBtn = document.getElementById('winClose');
    if (min) min.addEventListener('click', function () { call('window_minimize'); });
    if (max) max.addEventListener('click', toggleMax);
    if (closeBtn) {
      closeBtn.addEventListener('click', function () {
        if (typeof opts.onClose === 'function') {
          try { opts.onClose(); } catch (e) { call('window_close'); }
        } else {
          call('window_close');
        }
      });
    }

    /* 按钮上的按下不要触发窗口拖动 */
    Array.prototype.forEach.call(document.querySelectorAll('.wbtn'), function (btn) {
      btn.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    });

    /* 拖动标题栏双击 = 最大化/还原 */
    var drag = document.getElementById('titlebarDrag');
    if (drag) {
      drag.addEventListener('dblclick', function (e) {
        e.preventDefault();
        toggleMax();
      });
    }

    /* 八向缩放：mousedown 交给后端开一个跟随鼠标的线程 */
    Array.prototype.forEach.call(document.querySelectorAll('.rz'), function (rz) {
      rz.addEventListener('mousedown', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (document.body.classList.contains('is-maximized')) return;
        call('begin_resize', rz.dataset.edge);
      });
    });

    /* 失焦时标题栏变浅，和系统窗口一致 */
    var bar = document.getElementById('titlebar');
    function syncFocus() {
      if (bar) bar.classList.toggle('is-blurred', !document.hasFocus());
    }
    window.addEventListener('focus', syncFocus);
    window.addEventListener('blur', function () {
      if (bar) bar.classList.add('is-blurred');
    });
    syncFocus();

    /* 报告内容里的外链全部交给系统浏览器 */
    wireFrameLinks();
    try {
      var mo = new MutationObserver(wireFrameLinks);
      mo.observe(document.body, { childList: true, subtree: true });
    } catch (e) { /* 老 WebView2 不支持就只处理静态 iframe */ }
  }

  window.WinUpdChrome = {
    init: init,
    setMaximized: setMaximized,
    wireFrame: wireFrame,
    call: call,
    callArgs: callArgs,
    api: api
  };
})();
