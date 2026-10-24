/* ============================================================
   win升级报告 · 界面逻辑
   原生 JS / 无框架 / 无构建；数据全部来自 window.pywebview.api
   ============================================================ */
(function () {
  'use strict';

  /* ---------- 错误收集（预览自检用，不显示到界面） ---------- */
  window.__previewErrors = window.__previewErrors || [];
  function noteErr(err) {
    try {
      var text = (err && (err.stack || err.message)) || String(err);
      if (window.__previewErrors.length < 60) window.__previewErrors.push(text);
      if (window.console && console.error) console.error(err);
    } catch (e) { /* ignore */ }
  }
  window.addEventListener('error', function (e) { noteErr(e.error || e.message || 'window error'); });
  window.addEventListener('unhandledrejection', function (e) { noteErr(e.reason || 'unhandled rejection'); });

  /* ---------- 接口 ---------- */
  const API = (window.pywebview && window.pywebview.api) || window.__mockApi || null;
  function bridge() {
    return API || (window.pywebview && window.pywebview.api) || window.__mockApi || null;
  }

  const PAGE_TITLES = {
    overview: '概览', channels: '更新线', notify: '通知', settings: '设置',
    personalize: '个性化', startup: '自启与后台', reports: '报告', logs: '日志与诊断'
  };

  /* ---------- 状态 ---------- */
  const state = {
    booted: false, booting: false, page: '',
    app: {}, config: {}, appState: {}, watch: {}, startup: { enabled: false },
    channels: [], reports: [], trayStyles: [], detailOptions: ['简短', '标准', '详细'],
    taskText: '', now: '',
    chQ: '', chOnlyEnabled: false, selChannel: '',
    reportChannelFilter: '', reportSel: '', reportHtml: new Map(),
    selfcheck: null, liveLines: [], liveActive: false, liveRc: null,
    logText: '', logPath: '', logLoaded: false, logLoading: false, logAt: null,
    readerFile: '', readerOpen: false, readerTitle: '', readerToken: 0, pickerOpen: false,
    personalize: { bg_url: '', accent: '', lum: null, palette: null, blur: 15, card_alpha: 70, scrim_alpha: 0 },
    cropOpen: false, crop: null,
    foldAdvanced: false, startupTouchedAt: 0, pollTick: 0,
    maximized: false,
    chListHost: null, chDetailHost: null, checkHost: null,
    reportListHost: null, reportViewHost: null,
    activityOn: false, lastFocus: null, previewToken: 0,
    lastEnabledCount: null
  };

  let pendingPatch = {};
  let saveTimer = null;
  let savedTimer = null;
  let bootTimer = null;
  let pollTimer = null;
  let activityTimer = null;
  let lastToast = { text: '', at: 0 };
  let uid = 0;

  /* ============================================================
     基础工具
     ============================================================ */
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

  function el(tag, props) {
    const node = document.createElement(tag);
    if (props) {
      Object.keys(props).forEach(function (k) {
        const v = props[k];
        if (v === null || v === undefined || v === false) return;
        if (k === 'class') node.className = v;
        else if (k === 'text') node.textContent = v;
        else if (k === 'style') node.style.cssText = v;
        else if (k === 'dataset') Object.assign(node.dataset, v);
        else if (k.slice(0, 2) === 'on' && typeof v === 'function') node.addEventListener(k.slice(2).toLowerCase(), v);
        else if (k.indexOf('-') >= 0 || k === 'role') node.setAttribute(k, v === true ? '' : String(v));
        else if (k in node) node[k] = v;
        else node.setAttribute(k, String(v));
      });
    }
    const kids = Array.prototype.slice.call(arguments, 2);
    appendKids(node, kids);
    return node;
  }

  function appendKids(node, kids) {
    kids.forEach(function (kid) {
      if (kid === null || kid === undefined || kid === false) return;
      if (Array.isArray(kid)) { appendKids(node, kid); return; }
      node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    });
  }

  function svgIcon(name, cls) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'ico' + (cls ? ' ' + cls : ''));
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
    use.setAttribute('href', '#i-' + name);
    svg.appendChild(use);
    return svg;
  }

  function setText(node, text) {
    if (!node) return;
    const v = text === null || text === undefined ? '' : String(text);
    if (node.textContent !== v) node.textContent = v;
  }

  function setRefText(name, text) {
    $$('[data-ref="' + name + '"]').forEach(function (n) {
      const v = text === null || text === undefined ? '' : String(text);
      if (n.textContent === v) return;
      const had = n.textContent !== '';
      n.textContent = v;
      if (had && v) restartClass(n, 'is-updated', 560);
    });
  }

  function setRefDot(name, tone, live) {
    $$('[data-ref="' + name + '"]').forEach(function (n) {
      const next = 'dot dot-' + tone + (live ? ' is-live' : '');
      const current = String(n.className || '').replace(/\s*is-pulse\b/g, '').trim();
      if (current === next) return;
      const had = current.indexOf('dot-') >= 0;
      n.className = next;
      if (had) restartClass(n, 'is-pulse', 700);
    });
  }

  function setRefChecked(name, checked) {
    const v = checked ? 'true' : 'false';
    $$('[data-ref="' + name + '"]').forEach(function (n) {
      if (n.getAttribute('aria-checked') !== v) n.setAttribute('aria-checked', v);
    });
  }

  function setRefMeta(name, parts) {
    $$('[data-ref="' + name + '"]').forEach(function (n) {
      const key = parts.map(function (p) { return p.text; }).join('\u0001');
      if (n.dataset.metaKey === key) return;
      const had = !!n.dataset.metaKey;
      n.dataset.metaKey = key;
      n.textContent = '';
      parts.forEach(function (p, i) {
        const item = el('span', { class: 'm-item' + (p.strong ? ' m-strong' : ''), text: p.text });
        if (had && !motionOff()) {
          item.classList.add('meta-in');
          item.style.setProperty('--d', Math.min(i * 22, 110) + 'ms');
        }
        n.append(item);
      });
    });
  }

  /* ============================================================
     动效：节奏与层次
     按压反馈由 CSS 负责；这里只负责切页入场、折叠高度和数值 / 状态
     变化时的反馈。页面内部的数据刷新不再重播放动画，避免一直"闪"。
     ============================================================ */

  function motionOff() {
    try {
      return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (e) { return false; }
  }

  /** 重新触发一次 CSS 动画类（先摘掉、强制回流、再加回来）。 */
  function restartClass(node, cls, hold) {
    if (!node || node.nodeType !== 1 || motionOff()) return node;
    node.classList.remove(cls);
    void node.offsetWidth;
    node.classList.add(cls);
    if (hold) {
      const key = '_anim_' + cls;
      clearTimeout(node[key]);
      node[key] = setTimeout(function () {
        if (node.isConnected) node.classList.remove(cls);
      }, hold);
    }
    return node;
  }

  /** 这个节点上显示的数字变了一下：弹一下。 */
  function bumpEl(node) {
    return restartClass(node, 'is-bumped', 480);
  }

  function staggerChildren(nodes, cls, base, step, cap) {
    if (motionOff()) return;
    const max = cap === undefined ? 12 : cap;
    Array.prototype.forEach.call(nodes, function (node, i) {
      if (!node || node.nodeType !== 1) return;
      node.style.setProperty('--d', (base + Math.min(i, max) * step) + 'ms');
      node.classList.add(cls);
    });
  }

  /** 页面切换：只让容器做一层很轻的入场，内容不再逐块/逐行错峰。 */
  function playPageEnter(host) {
    if (!host || motionOff()) return;
    host.classList.remove('anim-page');
    void host.offsetWidth;
    host.classList.add('anim-page');
    clearTimeout(host._pageTimer);
    host._pageTimer = setTimeout(function () {
      if (host.isConnected) host.classList.remove('anim-page');
    }, 220);
  }

  /** 折叠 / 展开：真实高度过渡，收起后保留 hidden，便于无障碍和布局。 */
  function animateFold(body, open) {
    if (!body) return;
    clearTimeout(body._foldTimer);
    if (motionOff()) {
      body.hidden = !open;
      body.style.cssText = '';
      return;
    }
    body.hidden = false;
    body.style.overflow = 'hidden';
    const start = open ? 0 : body.getBoundingClientRect().height;
    body.style.height = start + 'px';
    body.style.opacity = open ? '0' : '1';
    void body.offsetHeight;
    const end = open ? body.scrollHeight : 0;
    body.style.transition = 'height 220ms var(--ease-out),opacity 160ms var(--ease-out)';
    body.style.height = end + 'px';
    body.style.opacity = open ? '1' : '0';
    body._foldTimer = setTimeout(function () {
      if (!body.isConnected) return;
      body.hidden = !open;
      body.style.cssText = '';
    }, 240);
  }

  function pad2(n) { return String(n).padStart(2, '0'); }
  function toDate(s) {
    if (!s) return null;
    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }
  function hhmm(s) {
    const d = toDate(s);
    return d ? pad2(d.getHours()) + ':' + pad2(d.getMinutes()) : '';
  }
  function mmdd(s) {
    const d = toDate(s);
    return d ? pad2(d.getMonth() + 1) + '-' + pad2(d.getDate()) : '';
  }
  function timeLabel(s) {
    const d = toDate(s);
    if (!d) return '';
    const now = new Date();
    const same = d.getFullYear() === now.getFullYear() && d.getMonth() === now.getMonth() && d.getDate() === now.getDate();
    return same ? hhmm(s) : mmdd(s) + ' ' + hhmm(s);
  }
  function isFuture(s) {
    const d = toDate(s);
    return !!d && d.getTime() > Date.now();
  }
  function shortName(name) {
    return String(name || '').replace(/（[^）]*）/g, '').replace(/\([^)]*\)/g, '').trim();
  }
  function compactName(name) {
    return shortName(name).replace(/^Windows\s*1[01]\s*/i, '').trim() || shortName(name);
  }
  function humanTaskText(text) {
    return String(text || '')
      .replace(/哨兵任务/g, '后台任务')
      .replace(/哨兵/g, '后台')
      .replace(/WinUpdReport_Watch/g, '后台监控');
  }
  function nowHHMM() {
    const d = new Date();
    return pad2(d.getHours()) + ':' + pad2(d.getMinutes());
  }
  function fileBase(p) {
    const s = String(p || '');
    const i = Math.max(s.lastIndexOf('\\'), s.lastIndexOf('/'));
    return i >= 0 ? s.slice(i + 1) : s;
  }
  function fileStem(p) {
    return fileBase(p).replace(/\.(md|html?)$/i, '');
  }
  function intervalMinutes() {
    const n = Number(state.config.watch_interval_minutes);
    return isFinite(n) && n > 0 ? n : 5;
  }
  function enabledChannels() {
    return (state.channels || []).filter(function (c) { return !!c.enabled; });
  }
  function findChannel(id) {
    return (state.channels || []).find(function (c) { return c.id === id; }) || null;
  }
  function findReport(file) {
    return (state.reports || []).find(function (r) { return r.file === file; }) || null;
  }
  function taskStateShort(t) {
    const s = String(t || '').toLowerCase();
    if (!s) return '正在查询…';
    if (s.indexOf('ready') >= 0) return '已就绪';
    if (s.indexOf('running') >= 0) return '正在运行';
    if (s.indexOf('disabled') >= 0) return '已停用';
    if (s.indexOf('不存在') >= 0 || s.indexOf('not found') >= 0 || s.indexOf('没有') >= 0) return '未安装';
    if (s.indexOf('取消') >= 0) return '已取消';
    return '未知';
  }

  /* ---------- 状态语言 ---------- */
  function watchStatusInfo() {
    const w = state.watch || {};
    const cfg = state.config || {};
    if (!w.online) return { tone: 'off', text: '后台监控已停止', live: false };
    const quietUntil = w.manual_until || cfg.silent_until || '';
    if (w.mode === 'game') return { tone: 'warn', text: '全屏中，先不打扰你', live: false };
    if (w.mode === 'paused') return { tone: 'warn', text: '已暂停', live: false };
    if (w.mode === 'stopped') return { tone: 'off', text: '后台监控已停止', live: false };
    if (quietUntil && isFuture(quietUntil)) return { tone: 'warn', text: '已静默到 ' + hhmm(quietUntil), live: false };
    return { tone: 'ok', text: '后台正在运行', live: true };
  }

  function statusTooltip(info) {
    if (info.tone === 'ok') return '后台正在运行 · 每 ' + intervalMinutes() + ' 分钟检查一次';
    if (info.tone === 'warn') return info.text + ' · 恢复后继续检查';
    return '后台监控没有在运行；到概览页点「开启后台监控」即可';
  }

  function titlebarState(info) {
    if (info.tone === 'ok') return info.text + ' · 每 ' + intervalMinutes() + ' 分钟';
    if (info.tone === 'off') return '监控已停止';
    return info.text;
  }

  function heroMetaParts() {
    const w = state.watch || {};
    const enabled = enabledChannels();
    const parts = [];
    if (w.online) {
      if (enabled.length) {
        const names = enabled.slice(0, 2).map(function (c) { return compactName(c.name); }).join('、');
        const more = enabled.length > 2 ? ' 等 ' + enabled.length + ' 条' : '';
        parts.push({ text: '正在盯 ' + names + more, strong: true });
      } else {
        parts.push({ text: '还没有启用更新线' });
      }
    } else if (enabled.length) {
      parts.push({ text: '有 ' + enabled.length + ' 条更新线已启用' });
    }
    parts.push({ text: '每 ' + intervalMinutes() + ' 分钟检查一次' });
    if (w.last_check) parts.push({ text: '上次检查 ' + timeLabel(w.last_check) });
    else if (state.appState && state.appState.last_check_date) parts.push({ text: '上次检查 ' + mmdd(state.appState.last_check_date) });
    else parts.push({ text: '还没检查过' });
    if (w.last_change && toDate(w.last_change)) parts.push({ text: '上次发现新版本 ' + mmdd(w.last_change) });
    return parts;
  }

  function startupMetaParts() {
    const w = state.watch || {};
    const modeText = { normal: '普通模式', game: '全屏中', paused: '已暂停', stopped: '已停止' }[w.mode] || '普通模式';
    const parts = [{ text: modeText }];
    parts.push({ text: '每 ' + intervalMinutes() + ' 分钟检查一次' });
    if (w.last_check) parts.push({ text: '上次检查 ' + timeLabel(w.last_check) });
    if (typeof w.checks === 'number' && w.checks > 0) {
      parts.push({ text: '已经检查 ' + w.checks + ' 次' });
    }
    if (typeof w.errors === 'number' && w.errors > 0) parts.push({ text: '出错 ' + w.errors + ' 次' });
    return parts;
  }

  function updateStatusWidgets() {
    if (!state.booted) return;
    const info = watchStatusInfo();
    const tb = $('#titlebar');
    if (tb) tb.title = statusTooltip(info);
    setRefDot('tbDot', info.tone, info.live);
    setRefText('tbStateText', titlebarState(info));

    setRefDot('heroDot', info.tone, info.live);
    setRefText('heroTitle', info.text);
    $$('[data-ref="heroCard"]').forEach(function (n) { n.classList.toggle('is-off', info.tone === 'off'); });
    updateRefMetaSafe('heroMeta', heroMetaParts());
    setRefText('heroToggleLabel', state.watch.online ? '停止后台监控' : '开启后台监控');
    setRefText('stToggleLabel', state.watch.online ? '停止后台监控' : '开启后台监控');

    setRefDot('stDot', info.tone, info.live);
    setRefText('stTitle', info.text);
    updateRefMetaSafe('stMeta', startupMetaParts());
    if (Date.now() - state.startupTouchedAt > 4000) {
      setRefChecked('stStartupSwitch', !!(state.startup && state.startup.enabled));
    }
    setRefText('stStartupState', state.startup && state.startup.enabled ? '已开启' : '未开启');
    setRefText('taskText', humanTaskText(state.taskText) || '正在查询…');
  }
  function updateRefMetaSafe(name, parts) {
    if (document.querySelector('[data-ref="' + name + '"]')) setRefMeta(name, parts);
  }

  /* ============================================================
     小部件
     ============================================================ */
  function cardEl() {
    const cls = Array.prototype.slice.call(arguments, 0).filter(function (x) { return typeof x === 'string'; }).join(' ');
    const kids = Array.prototype.slice.call(arguments, 0).filter(function (x) { return typeof x !== 'string'; });
    const node = el('div', { class: 'card' + (cls ? ' ' + cls : '') });
    appendKids(node, kids);
    return node;
  }

  function sectionEl(title, side, content) {
    const head = el('div', { class: 'sec-head' },
      el('h2', { class: 'sec-title', text: title }),
      side ? el('div', { class: 'sec-side' }, side) : null
    );
    const sec = el('section', { class: 'sec' }, head);
    appendKids(sec, [content]);
    return sec;
  }

  function tagEl(text, variant) {
    return el('span', { class: 'tag' + (variant ? ' ' + variant : ''), text: text });
  }

  function emptyEl(iconName, title, help, actionEl) {
    const node = el('div', { class: 'empty' }, svgIcon(iconName));
    node.append(el('div', { class: 'empty-title', text: title }));
    if (help) node.append(el('div', { class: 'empty-help', text: help }));
    if (actionEl) node.append(actionEl);
    return node;
  }

  function switchEl(checked, onChange, label) {
    const btn = el('button', {
      type: 'button', class: 'switch', role: 'switch',
      'aria-checked': checked ? 'true' : 'false',
      'aria-label': label || '开关'
    });
    btn.addEventListener('click', function () {
      if (btn.disabled) return;
      const next = btn.getAttribute('aria-checked') !== 'true';
      btn.setAttribute('aria-checked', next ? 'true' : 'false');
      onChange(next);
    });
    return btn;
  }

  function checkEl(checked, labelText, onChange) {
    const input = el('input', { type: 'checkbox', checked: !!checked });
    const wrap = el('label', { class: 'check' },
      input,
      el('span', { class: 'box' }, svgIcon('check')),
      el('span', { class: 'check-label', text: labelText })
    );
    input.addEventListener('change', function () { onChange(input.checked); });
    return wrap;
  }

  function numInput(opts) {
    const input = el('input', {
      class: 'input', type: 'number',
      value: opts.value === null || opts.value === undefined ? '' : String(opts.value),
      'data-field': opts.key, 'aria-label': opts.label || opts.key,
      min: opts.min, max: opts.max, step: opts.step,
      style: 'width:' + (opts.width || 92) + 'px'
    });
    const wrap = el('div', { class: 'num-wrap' }, input, el('span', { class: 'unit', text: opts.unit || '' }));
    input.addEventListener('change', function () {
      const raw = input.value.trim();
      if (raw === '') { input.value = String(state.config[opts.key]); return; }
      const n = Number(raw);
      if (!isFinite(n)) { input.value = String(state.config[opts.key]); return; }
      queueSave(opts.key, opts.float ? n : Math.round(n));
    });
    return wrap;
  }

  function textInput(opts) {
    const input = el('input', {
      class: 'input' + (opts.mono ? ' mono' : ''),
      type: opts.type || 'text',
      value: opts.value === null || opts.value === undefined ? '' : String(opts.value),
      'data-field': opts.key,
      placeholder: opts.placeholder || '',
      'aria-label': opts.label || opts.key,
      autocomplete: 'off', spellcheck: 'false',
      style: opts.width ? 'width:' + (typeof opts.width === 'number' ? opts.width + 'px' : opts.width) : ''
    });
    const commit = function () {
      const v = input.value;
      if (String(state.config[opts.key] === undefined ? '' : state.config[opts.key]) === v) return;
      queueSave(opts.key, v);
    };
    if (opts.live) {
      let t = null;
      input.addEventListener('input', function () {
        clearTimeout(t);
        t = setTimeout(commit, 700);
      });
    }
    input.addEventListener('change', commit);
    return input;
  }

  function segEl(options, value, onChange) {
    const seg = el('div', { class: 'seg', role: 'group' });
    options.forEach(function (opt) {
      const btn = el('button', {
        type: 'button', text: opt,
        'aria-pressed': opt === value ? 'true' : 'false'
      });
      btn.addEventListener('click', function () {
        if (btn.getAttribute('aria-pressed') === 'true') return;
        Array.prototype.slice.call(btn.parentElement.children).forEach(function (n) {
          n.setAttribute('aria-pressed', 'false');
        });
        btn.setAttribute('aria-pressed', 'true');
        onChange(opt);
      });
      seg.append(btn);
    });
    return seg;
  }

  function rowControl(label, help, ctl, extra) {
    const row = el('div', { class: 'row' + (extra && extra.disabled ? ' is-disabled' : '') },
      el('div', { class: 'row-main' },
        el('div', { class: 'row-label', text: label }),
        help ? el('div', { class: 'row-help', text: help }) : null
      ),
      el('div', { class: 'row-ctl' }, ctl)
    );
    return row;
  }

  function switchRow(label, help, checked, onChange, extra) {
    const sw = switchEl(checked, onChange, label);
    if (extra && extra.disabled) sw.disabled = true;
    const row = rowControl(label, help, sw, extra);
    row.dataset.switchRow = '1';
    return row;
  }

  function settingsRow(label, help, ctl, opts) {
    opts = opts || {};
    const row = el('div', { class: 'settings-row' + (opts.disabled ? ' is-disabled' : '') },
      el('div', { class: 'settings-main' },
        el('div', { class: 'row-label', text: label }),
        help ? el('div', { class: 'row-help', text: help }) : null
      ),
      el('div', { class: 'settings-ctl' + (opts.wide ? ' wide' : '') }, ctl)
    );
    return row;
  }

  function kvItem(label, value, opts) {
    opts = opts || {};
    const node = el('div', { class: 'kv' },
      el('div', { class: 'kv-label', text: label }),
      el('div', { class: 'kv-value' + (opts.mono ? ' mono' : ''), text: value, title: opts.title || value })
    );
    return node;
  }

  function confirmThen(btn, confirmText, fn) {
    if (btn.dataset.armed === '1') {
      btn.dataset.armed = '';
      btn.classList.remove('is-armed');
      setText(btn, btn.dataset.label || '');
      fn();
      return;
    }
    btn.dataset.label = btn.textContent;
    btn.dataset.armed = '1';
    setText(btn, confirmText);
    btn.classList.add('is-armed');
    clearTimeout(btn._armedTimer);
    btn._armedTimer = setTimeout(function () {
      if (!btn.isConnected) return;
      btn.dataset.armed = '';
      btn.classList.remove('is-armed');
      setText(btn, btn.dataset.label || '');
    }, 3200);
  }

  /* ============================================================
     提示：toast / 活动条 / 已保存
     ============================================================ */
  function toast(kind, text) {
    if (!text) return;
    const now = Date.now();
    if (lastToast.text === text && now - lastToast.at < 2200) return;
    lastToast = { text: text, at: now };
    const box = $('#toasts');
    if (!box) return;
    const iconName = kind === 'ok' ? 'check' : kind === 'error' ? 'alert' : kind === 'warn' ? 'alert' : 'info';
    const node = el('div', { class: 'toast', 'data-kind': kind || 'info', title: '点击关闭' },
      svgIcon(iconName),
      el('div', { class: 'toast-text', text: text })
    );
    node.addEventListener('click', function () { dismissToast(node); });
    box.append(node);
    while (box.children.length > 3) box.removeChild(box.firstElementChild);
    setTimeout(function () { dismissToast(node); }, kind === 'error' ? 4600 : 3200);
  }

  function dismissToast(node) {
    if (!node || !node.isConnected || node.dataset.out === '1') return;
    node.dataset.out = '1';
    node.classList.add('is-out');
    setTimeout(function () { if (node.isConnected) node.remove(); }, 180);
  }

  function dismissLastToast() {
    const box = $('#toasts');
    if (box && box.lastElementChild) dismissToast(box.lastElementChild);
  }

  function showActivity(text, timeout) {
    const bar = $('#activity');
    if (!bar) return;
    bar.hidden = false;
    state.activityOn = true;
    setText($('#activityText'), text || '正在处理…');
    bar.classList.remove('is-on');
    void bar.offsetWidth;
    bar.classList.add('is-on');
    document.documentElement.style.setProperty('--activity-h', '36px');
    clearTimeout(activityTimer);
    activityTimer = setTimeout(function () { hideActivity(); }, timeout || 25000);
  }

  function hideActivity() {
    clearTimeout(activityTimer);
    if (!state.activityOn) return;
    state.activityOn = false;
    const bar = $('#activity');
    if (bar) { bar.hidden = true; bar.classList.remove('is-on'); }
    document.documentElement.style.setProperty('--activity-h', '0px');
  }

  function savedHintOk() {
    const n = $('#savedHint');
    if (!n) return;
    n.classList.remove('is-bad', 'is-pop');
    n.textContent = '已保存 ' + nowHHMM();
    n.classList.add('is-on');
    restartClass(n, 'is-pop', 300);
    clearTimeout(savedTimer);
    savedTimer = setTimeout(function () { n.classList.remove('is-on'); }, 6000);
  }

  function savedHintFail(msg) {
    const n = $('#savedHint');
    if (!n) return;
    n.textContent = '保存失败' + (msg ? '：' + ((msg.length > 14) ? msg.slice(0, 14) + '…' : msg) : '');
    n.classList.add('is-on', 'is-bad');
    clearTimeout(savedTimer);
    savedTimer = setTimeout(function () { n.classList.remove('is-on'); }, 8000);
  }

  /* ============================================================
     自动保存
     ============================================================ */
  function queueSave(key, value) {
    pendingPatch[key] = value;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(flushSave, 400);
  }

  function markFieldError(key, msg) {
    $$('[data-field="' + key + '"]').forEach(function (inp) { inp.classList.toggle('is-invalid', !!msg); });
    const err = $('[data-err="' + key + '"]');
    if (err) {
      err.textContent = msg || '';
      err.hidden = !msg;
    }
  }

  async function flushSave() {
    const patch = pendingPatch;
    pendingPatch = {};
    const keys = Object.keys(patch);
    if (!keys.length) return;
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.save_config(patch);
      if (r && r.ok) {
        state.config = r.config || Object.assign({}, state.config, patch);
        keys.forEach(function (k) { markFieldError(k, ''); });
        savedHintOk();
        if (r.message) toast('ok', r.message);
        updateStatusWidgets();
      } else {
        const msg = (r && r.error) || '保存失败，检查一下再试';
        savedHintFail(msg);
        toast('error', msg);
        keys.forEach(function (k) { if (k === 'quiet_hours') markFieldError(k, msg); });
      }
    } catch (e) {
      noteErr(e);
      savedHintFail('保存失败');
    }
  }

  /* ============================================================
     接口调用
     ============================================================ */
  async function callApi(name, args, opts) {
    opts = opts || {};
    const a = bridge();
    if (!a) { toast('error', '后台还没准备好，稍等一下'); return null; }
    try {
      const r = await a[name].apply(a, args || []);
      if (r && r.ok === false) {
        toast('error', r.error || opts.failText || '没成功，再试一次');
        return r;
      }
      if (r && r.message) toast('ok', r.message);
      if (r && r.started && opts.busy) showActivity(opts.busy);
      return r;
    } catch (e) {
      noteErr(e);
      toast('error', (e && e.message) || '出错了，再试一次');
      return null;
    }
  }

  /* ============================================================
     导航
     ============================================================ */
  const PAGE_HOSTS = {};

  function go(page, force) {
    if (!state.booted) return;
    const host = PAGE_HOSTS[page];
    if (!host) return;
    if (page === state.page && !force) { $('#content').scrollTop = 0; return; }
    state.page = page;
    $$('.nav-item').forEach(function (n) {
      const on = n.dataset.page === page;
      n.classList.toggle('is-active', on);
      if (on) n.setAttribute('aria-current', 'page');
      else n.removeAttribute('aria-current');
    });
    setText($('#pageTitle'), PAGE_TITLES[page] || '');
    Object.keys(PAGE_HOSTS).forEach(function (k) { PAGE_HOSTS[k].hidden = k !== page; });
    host.hidden = false;
    renderPage(page);
    playPageEnter(host);
    $('#content').scrollTop = 0;
    if (page === 'logs') ensureLogLoaded();
    if (page === 'reports' && !reportsNarrow()) ensureReportPreview();
  }

  function renderPage(page) {
    const host = PAGE_HOSTS[page];
    if (!host) return;
    host.textContent = '';
    const fn = RENDERERS[page];
    if (fn) fn(host);
    updateStatusWidgets();
  }

  function refreshPage() {
    if (!state.booted || !state.page) return;
    renderPage(state.page);
  }

  /* ============================================================
     启动 / 轮询 / 事件
     ============================================================ */
  function start() {
    if (state.booting || state.booted) return;
    state.booting = true;
    bootTimer = setTimeout(function () {
      const b = $('#boot');
      if (b && !state.booted) b.classList.add('is-on');
    }, 200);
    bootstrap();
  }

  async function bootstrap() {
    const a = bridge();
    if (!a) {
      state.booting = false;
      fatal('连不上后台接口', '这是设置界面的内部错误。关掉窗口重新打开一次试试。');
      return;
    }
    let r = null;
    try {
      r = await a.bootstrap();
    } catch (e) {
      noteErr(e);
      state.booting = false;
      fatal('读取设置失败', '后台没有回应。关掉窗口重新打开一次试试。');
      return;
    }
    if (!r || r.ok === false) {
      state.booting = false;
      fatal('读取设置失败', (r && r.error) || '后台没有返回数据。关掉窗口重新打开一次试试。');
      return;
    }
    state.app = r.app || {};
    state.config = r.config || {};
    state.appState = r.state || {};
    state.watch = r.watch || { online: false };
    state.channels = r.channels || [];
    state.reports = r.reports || [];
    state.trayStyles = r.tray_styles || [];
    state.detailOptions = r.detail_options || state.detailOptions;
    state.personalize = Object.assign({
      bg_url: '', accent: '', lum: null, palette: null, blur: 15, card_alpha: 70, scrim_alpha: 0
    }, r.personalize || {});
    state.taskText = r.task_text || '';
    state.startup = r.startup || { enabled: false };
    state.now = r.now || '';
    state.logPath = state.app.log_path || '';
    if (!state.channels.length) state.reportSel = '';
    const firstEnabled = state.channels.find(function (c) { return c.enabled; });
    state.selChannel = firstEnabled ? firstEnabled.id : (state.channels[0] ? state.channels[0].id : '');
    state.reportSel = state.reports[0] ? state.reports[0].file : '';
    state.booted = true;
    state.booting = false;
    clearTimeout(bootTimer);
    setMaximizedUI(false);
    const boot = $('#boot');
    if (boot) boot.hidden = true;
    updateStatusWidgets();
    applyPersonalize();
    refreshPersonalMood();
    go('overview', true);
    pollOnce();
  }

  function fatal(title, text) {
    clearTimeout(bootTimer);
    const boot = $('#boot');
    if (boot) boot.hidden = true;
    const host = PAGE_HOSTS.overview;
    if (!host) return;
    $$('.page').forEach(function (p) { p.hidden = true; });
    host.hidden = false;
    host.textContent = '';
    host.append(el('div', { class: 'fatal' },
      el('div', { class: 'fatal-title', text: title }),
      el('div', { class: 'fatal-text', text: text }),
      el('button', {
        type: 'button', class: 'btn btn-secondary btn-sm', text: '重新加载',
        onclick: function () { window.location.reload(); }
      })
    ));
  }

  async function pollOnce() {
    clearTimeout(pollTimer);
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.poll();
      if (r && r.ok) applyPoll(r);
    } catch (e) {
      noteErr(e);
    }
    pollTimer = setTimeout(pollOnce, 1000);
  }

  function applyPoll(r) {
    state.now = r.now || state.now;
    if (r.watch) state.watch = r.watch;
    if (r.startup) state.startup = r.startup;
    if (r.window && typeof r.window.maximized === 'boolean') setMaximizedUI(r.window.maximized);
    if (typeof r.task_text === 'string') state.taskText = r.task_text;
    state.pollTick++;

    syncLive(r.live);
    updateStatusWidgets();
    if (Array.isArray(r.events)) r.events.forEach(handleEvent);

    if (state.page === 'logs' && state.pollTick % 4 === 0) loadLog(true);
  }

  function handleEvent(ev) {
    if (!ev || !ev.type) return;
    switch (ev.type) {
      case 'toast':
        toast(ev.kind || 'info', ev.text);
        break;
      case 'busy':
        if (ev.active) showActivity(ev.text || '正在处理…');
        else hideActivity();
        break;
      case 'done':
        hideActivity();
        if (ev.text) toast(ev.ok === false ? 'error' : (ev.kind === 'toast' ? 'info' : 'ok'), ev.text);
        if (ev.kind === 'check' || ev.kind === 'refresh') {
          refreshChannels();
          refreshReports();
        } else if (ev.kind === 'task_install' || ev.kind === 'task_remove') {
          refreshTaskInfo();
        } else if (ev.kind === 'api_test') {
          state.apiTestResult = ev.text || '';
          setRefText('apiTest', ev.text || '');
        }
        break;
      case 'selfcheck':
        state.selfcheck = ev;
        if (state.page === 'logs') renderCheckBlock();
        if (ev.summary) toast(ev.ok === false ? 'error' : 'info', ev.summary);
        break;
      case 'discover':
        if (Array.isArray(ev.channels)) applyChannels(ev.channels);
        break;
      case 'channels':
        if (Array.isArray(ev.channels)) applyChannels(ev.channels);
        break;
      case 'reports':
        if (Array.isArray(ev.reports)) applyReports(ev.reports);
        break;
      case 'task_info':
        if (typeof ev.text === 'string') {
          state.taskText = ev.text;
          updateStatusWidgets();
        }
        break;
      default:
        break;
    }
  }

  /* ---------- 数据 ---------- */
  function applyChannels(list) {
    state.channels = list;
    if (!findChannel(state.selChannel) && list.length) {
      const firstEnabled = list.find(function (c) { return c.enabled; });
      state.selChannel = firstEnabled ? firstEnabled.id : list[0].id;
    }
    if (state.page === 'overview' || state.page === 'channels') refreshPage();
    updateStatusWidgets();
  }

  function applyReports(list) {
    state.reports = list;
    if (!findReport(state.reportSel) && list.length) state.reportSel = list[0].file;
    if (state.page === 'overview' || state.page === 'reports') refreshPage();
  }

  async function refreshChannels() {
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.channels();
      if (r && r.ok && Array.isArray(r.channels)) applyChannels(r.channels);
    } catch (e) { noteErr(e); }
  }

  async function refreshReports() {
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.reports();
      if (r && r.ok && Array.isArray(r.reports)) applyReports(r.reports);
    } catch (e) { noteErr(e); }
  }

  async function refreshTaskInfo() {
    await callApi('refresh_task_info', [], { busy: '正在查询后台任务状态…' });
  }

  /* ---------- live 输出 ---------- */
  function syncLive(live) {
    const lines = (live && live.lines) || [];
    const active = !!(live && live.active);
    const rc = live ? live.rc : null;
    const had = state.liveLines.length > 0 || state.liveActive;
    const changed = lines.length !== state.liveLines.length ||
      (lines.length && lines[lines.length - 1] !== state.liveLines[state.liveLines.length - 1]);
    const presenceChanged = (lines.length > 0 || active) !== (state.liveLines.length > 0 || state.liveActive);
    state.liveLines = lines.slice();
    state.liveActive = active;
    state.liveRc = rc;
    if (state.page !== 'logs') return;
    if (presenceChanged) refreshPage();
    else if (changed) updateLivePre();
    else if (had !== (lines.length > 0 || active)) refreshPage();
  }

  /* ============================================================
     概览
     ============================================================ */
  function renderOverview(host) {
    const reports = state.reports || [];
    /* 首屏先给「最新报告」：用户打开这个窗口，最想知道的是这次更新了什么 */
    if (reports.length) host.append(ovLatestCardEl(reports[0]));

    host.append(heroCardEl());

    if (!state.watch.online) {
      const tasks = overviewTasks();
      /* 只有一步时不再单独占一张「还差几步」：上面的主按钮就是那一步 */
      if (tasks.length > 1) {
        const card = el('div', { class: 'card todo-card' });
        tasks.forEach(function (t, i) { card.append(todoRowEl(t, i)); });
        host.append(sectionEl('还差几步', null, card));
      }
    }

    const enabled = enabledChannels();
    const enabledNum = el('span', {
      class: 'num',
      text: enabled.length ? enabled.length + ' 条已启用' : '未启用'
    });
    host.append(sectionEl('更新线状态', enabledNum, ovChannelCardEl()));
    if (state.lastEnabledCount !== null && state.lastEnabledCount !== enabled.length) {
      bumpEl(enabledNum);
    }
    state.lastEnabledCount = enabled.length;

    const older = reports.slice(1, 5);
    const allBtn = el('button', {
      type: 'button', class: 'mini-btn', text: '全部报告',
      onclick: function () { go('reports'); }
    });
    if (older.length) {
      host.append(sectionEl('更早的报告', allBtn, ovReportsCardEl(older)));
    } else if (!reports.length) {
      host.append(sectionEl('最近报告', allBtn, ovReportsCardEl([])));
    }

    host.append(overviewFootEl());
  }

  function ovLatestCardEl(r) {
    const card = el('section', { class: 'card latest-card' });
    const main = el('div', { class: 'latest-main' },
      el('div', { class: 'latest-head' },
        tagEl('最新报告', 'tag-accent'),
        el('span', {
          class: 'latest-name',
          text: compactName(r.channel_name) || '更新报告',
          title: r.channel_name || ''
        }),
        el('span', {
          class: 'latest-meta mono',
          text: (r.build || '') + (r.build ? ' · ' : '') +
            (r.date ? mmdd(r.date) : mmdd(r.mtime))
        })
      ),
      el('div', {
        class: 'latest-sum',
        text: r.summary || '（这份报告没有一句话总结）',
        title: r.summary || ''
      })
    );
    const actions = el('div', { class: 'latest-actions' },
      el('button', {
        type: 'button', class: 'btn btn-primary btn-sm', text: '阅读报告',
        onclick: function () { openReader(r.file); }
      }),
      el('button', {
        type: 'button', class: 'btn btn-ghost btn-sm', text: '全部报告',
        onclick: function () { go('reports'); }
      })
    );
    card.append(main, actions);
    return card;
  }

  function heroCardEl() {
    const card = el('section', { class: 'card hero', 'data-ref': 'heroCard' });
    const main = el('div', { class: 'hero-main' },
      el('span', { class: 'dot dot-off', 'data-ref': 'heroDot' }),
      el('div', { class: 'hero-copy' },
        el('div', { class: 'hero-title', 'data-ref': 'heroTitle', text: '正在读取…' }),
        el('div', { class: 'hero-meta', 'data-ref': 'heroMeta' })
      )
    );
    const actions = el('div', { class: 'hero-actions' },
      el('button', {
        type: 'button', class: 'btn btn-primary', onclick: function () { toggleWatch(); }
      }, el('span', { 'data-ref': 'heroToggleLabel', text: '开启后台监控' })),
      el('button', {
        type: 'button', class: 'btn btn-secondary', text: '立刻检查',
        onclick: function () { checkNow(); }
      })
    );
    card.append(main, actions);
    return card;
  }

  function overviewTasks() {
    const cfg = state.config || {};
    const w = state.watch || {};
    const enabled = enabledChannels();
    const tasks = [];
    if (!cfg.api_key || !String(cfg.api_key).trim()) {
      tasks.push({
        label: '填一个 AI 的 Key',
        help: '不填的话，就算发现新版本也写不出中文报告',
        goText: '去设置',
        run: function () {
          go('settings');
          setTimeout(function () {
            const inp = $('[data-field="api_key"]');
            if (inp) inp.focus();
          }, 80);
        }
      });
    }
    if (!enabled.length) {
      tasks.push({
        label: '选一条要盯的更新线',
        help: '在「更新线」里打开一条，比如 Windows 11 Beta',
        goText: '去选线',
        run: function () { go('channels'); }
      });
    }
    if (!w.online) {
      tasks.push({
        label: '开启后台监控',
        help: '开启后按设置间隔自动检查，发现新版本会提醒你',
        goText: '开启',
        run: function () { toggleWatch(); }
      });
    }
    return tasks.slice(0, 3);
  }

  function todoRowEl(t, i) {
    return el('button', { type: 'button', class: 'todo-row', onclick: t.run },
      el('span', { class: 'todo-idx', text: pad2(i + 1) }),
      el('div', { class: 'todo-main' },
        el('div', { class: 'todo-label', text: t.label }),
        t.help ? el('div', { class: 'todo-help', text: t.help }) : null
      ),
      el('span', { class: 'todo-go' }, t.goText, svgIcon('chevron-right', 'ico-xs'))
    );
  }

  function ovChannelCardEl() {
    const enabled = enabledChannels();
    const card = el('div', { class: 'card mini-card' });
    if (!enabled.length) {
      card.append(emptyEl('channels', '还没有启用更新线', '在「更新线」里打开一条，后台就会开始盯它',
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '去更新线',
          onclick: function () { go('channels'); }
        })));
      return card;
    }
    card.append(el('div', { class: 'mini-head' },
      el('span', { text: '更新线' }),
      el('span', { text: '当前版本' }),
      el('span', { text: '上次检测' }),
      el('span', { text: '最近报告' })
    ));
    enabled.forEach(function (ch) {
      const st = ch.state || {};
      const nameCell = el('div', { class: 'mini-name-cell' },
        el('button', {
          type: 'button', class: 'mini-name', title: ch.name,
          onclick: function () { state.selChannel = ch.id; go('channels'); }
        }, el('span', { class: 'nm', text: ch.name })),
        tagEl(ch.source === 'flighthub' ? 'Flight Hub' : 'uupdump', 'tag-quiet')
      );
      const reportCell = st.last_report
        ? el('button', {
          type: 'button', class: 'mini-btn', text: '打开',
          onclick: function () { openReportFile(st.last_report); }
        })
        : el('span', { class: 'ink-3', text: '—' });
      card.append(el('div', { class: 'mini-row' },
        nameCell,
        el('span', { class: 'mini-cell mono', text: st.last_version || '—' }),
        el('span', { class: 'mini-cell', text: st.last_check_date ? mmdd(st.last_check_date) : '—' }),
        el('span', { class: 'mini-cell' }, reportCell)
      ));
    });
    return card;
  }

  function ovReportsCardEl(reports) {
    const card = el('div', { class: 'card recent-card' });
    if (!reports.length) {
      card.append(emptyEl('doc', '还没有报告', '检测到新版本后，这里会出现对应的中文解读',
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '打开报告文件夹',
          onclick: function () { openExternal('report_folder'); }
        })));
      return card;
    }
    reports.forEach(function (r) {
      card.append(el('button', {
        type: 'button', class: 'recent-row', title: r.file || '',
        onclick: function () { openReportFile(r.file); }
      },
        el('span', { class: 'recent-date', text: r.date ? mmdd(r.date) : mmdd(r.mtime) }),
        el('div', { class: 'recent-main' },
          el('div', { class: 'recent-top' },
            el('span', { class: 'recent-name', text: r.channel_name || '更新报告' }),
            el('span', { class: 'recent-build', text: r.build || '' })
          ),
          el('div', { class: 'recent-summary', text: r.summary || '（没有一句话总结）', title: r.summary || '' })
        ),
        svgIcon('chevron-right', 'ico-xs')
      ));
    });
    return card;
  }

  function overviewFootEl() {
    const app = state.app || {};
    const foot = el('div', { class: 'footline' });
    function sep() { foot.append(el('span', { class: 'f-sep', text: '·' })); }
    if (app.base_dir) {
      foot.append(el('button', {
        type: 'button', class: 'link-btn mono truncate', text: app.base_dir,
        title: app.base_dir + '（点击打开程序目录）',
        style: 'max-width:320px;font-size:11px',
        onclick: function () { openExternal('app_folder'); }
      }));
      sep();
    }
    foot.append(el('span', { class: 'f-item', text: '后台任务 ' + taskStateShort(state.taskText) }));
    sep();
    foot.append(el('span', {
      class: 'f-item',
      text: '开机自启 ' + (state.startup && state.startup.enabled ? '已开启' : '未开启')
    }));
    sep();
    foot.append(el('button', {
      type: 'button', class: 'link-btn', text: '自启设置',
      onclick: function () { go('startup'); }
    }));
    return foot;
  }

  /* ============================================================
     更新线
     ============================================================ */
  function renderChannels(host) {
    const grid = el('div', { class: 'split' });
    grid.append(channelListPanelEl(), channelDetailEl());
    host.append(grid);
    renderChannelList();
    renderChannelDetail();
  }

  function channelListPanelEl() {
    const search = el('input', {
      class: 'input', type: 'search', placeholder: '搜索名称、分类或标签',
      'aria-label': '搜索更新线', value: state.chQ || '',
      oninput: function (e) {
        state.chQ = e.target.value;
        renderChannelList();
      }
    });
    const searchRow = el('div', { class: 'search' }, svgIcon('search'), search);

    const onlyEnabled = checkEl(state.chOnlyEnabled, '仅看已启用', function (v) {
      state.chOnlyEnabled = v;
      renderChannelList();
    });

    const refreshBtn = el('button', {
      type: 'button', class: 'link-btn', title: '去 Flight Hub 看看有没有新的线',
      onclick: function () { discoverChannels(); }
    }, '刷新可选线');

    const listHost = el('div', { class: 'list-scroll', 'aria-live': 'polite' });
    state.chListHost = listHost;

    const addInput = el('input', {
      class: 'input', type: 'text',
      placeholder: '分类名或 uupdump 网址',
      'aria-label': '添加自定义更新线'
    });
    const addBtn = el('button', { type: 'button', class: 'btn btn-primary', text: '添加' });
    async function submitAdd() {
      const text = addInput.value.trim();
      if (!text) { addInput.focus(); return; }
      addBtn.disabled = true;
      const r = await callApi('add_channel', [text], { failText: '没加进去' });
      addBtn.disabled = false;
      if (r && r.ok) {
        addInput.value = '';
        if (Array.isArray(r.channels)) applyChannels(r.channels);
        if (r.message) toast('ok', r.message);
      } else if (r && r.message) {
        toast('error', r.message);
      }
    }
    addBtn.addEventListener('click', submitAdd);
    addInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submitAdd(); }
    });

    const panel = el('div', { class: 'panel list-panel' },
      el('div', { class: 'list-toolbar' }, searchRow,
        el('div', { class: 'list-tools' }, onlyEnabled, refreshBtn)),
      listHost,
      el('div', { class: 'list-add' },
        el('div', { class: 'add-row' }, addInput, addBtn),
        el('div', { class: 'field-hint', text: '输入分类名，例如 w11-26h2-experimental；也可以直接粘贴 uupdump 网址' })
      )
    );
    return panel;
  }

  function renderChannelList() {
    const host = state.chListHost;
    if (!host) return;
    host.textContent = '';
    const q = (state.chQ || '').trim().toLowerCase();
    const rows = (state.channels || []).filter(function (c) {
      if (state.chOnlyEnabled && !c.enabled) return false;
      if (!q) return true;
      return [c.name, c.folder, c.category, c.url, c.id]
        .filter(Boolean).join(' ').toLowerCase().indexOf(q) >= 0;
    });
    if (state.chCountEl) {
      setText(state.chCountEl, rows.length + ' / ' + (state.channels || []).length + ' 条');
    }
    if (!rows.length) {
      host.append(emptyEl('search', '没有匹配的更新线',
        q ? '换个词试试，或者清空搜索' : '打开下面的「添加」加一条自定义更新线',
        q ? el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '清空搜索',
          onclick: function () {
            state.chQ = '';
            refreshPage();
          }
        }) : null));
      return;
    }
    [{ key: 'flighthub', label: 'Flight Hub' }, { key: 'uupdump', label: 'uupdump' }].forEach(function (g) {
      const items = rows.filter(function (c) { return c.source === g.key; });
      if (!items.length) return;
      host.append(el('div', { class: 'group-label', text: g.label + ' · ' + items.length }));
      items.forEach(function (ch) { host.append(chRowEl(ch)); });
    });
  }

  function chRowEl(ch) {
    return el('button', {
      type: 'button',
      class: 'ch-row ' + (ch.enabled ? 'is-on' : 'is-off') + (ch.id === state.selChannel ? ' is-sel' : ''),
      title: ch.name,
      onclick: function () {
        state.selChannel = ch.id;
        renderChannelList();
        renderChannelDetail();
      }
    },
      el('span', { class: 'ch-dot' }),
      el('span', { class: 'ch-name', text: ch.name }),
      el('span', { class: 'ch-side' },
        ch.preset ? el('span', { class: 'ch-preset', text: '可选' }) : null,
        ch.arch === 'arm64' ? el('span', { class: 'ch-arch', text: 'arm64' }) : null
      )
    );
  }

  function channelDetailEl() {
    const panel = el('div', { class: 'panel detail-panel' });
    state.chDetailHost = panel;
    return panel;
  }

  function renderChannelDetail() {
    const host = state.chDetailHost;
    if (!host) return;
    const wasFilled = host.childElementCount > 0;
    host.textContent = '';
    const ch = findChannel(state.selChannel);
    if (!ch) {
      host.append(emptyEl('channels', '选一条更新线', '左边点一条，这里显示它的版本、检测记录和设置'));
      return;
    }
    const st = ch.state || {};
    const sourceLabel = ch.source === 'flighthub' ? 'Flight Hub' : 'uupdump';

    const head = el('div', { class: 'detail-head' },
      el('div', {},
        el('div', { class: 'detail-title', text: ch.name, title: ch.name }),
        el('div', { class: 'detail-tags' },
          tagEl(sourceLabel, 'tag-quiet'),
          ch.arch === 'arm64' ? tagEl('ARM64', 'tag-quiet') : null,
          ch.enabled ? tagEl('已启用', 'tag-ok') : tagEl('未启用', 'tag-quiet')
        )
      )
    );
    host.append(head);

    if (ch.preset) {
      host.append(el('div', { class: 'detail-preset-note', text: '这是刚发现的可选线，打开下面的开关才会开始检查。' }));
    }

    const enableSwitch = switchEl(!!ch.enabled, function (next) {
      setChannelEnabled(ch.id, next);
    }, '启用这条更新线');
    host.append(el('div', { class: 'switch-row' },
      el('div', { class: 'row-main' },
        el('div', { class: 'row-label', text: '启用这条更新线' }),
        el('div', { class: 'row-help', text: ch.enabled ? '后台会按间隔检查它；停用不会删掉已有报告' : '打开后，后台会开始检查它' })
      ),
      enableSwitch
    ));

    const stateSec = el('div', { class: 'detail-sec' });
    stateSec.append(el('div', { class: 'detail-sec-title' }, el('span', { text: '检测状态' })));
    const kv = el('div', { class: 'kv-grid' },
      kvItem('当前版本', st.last_version || '还没检测过', { mono: !!st.last_version }),
      kvItem('上次检测', st.last_check_date ? mmdd(st.last_check_date) : '—'),
      kvItem('报告数量', (ch.report_count || (st.reports || []).length || 0) + ' 份'),
      kvItem('忽略版本', (st.ignored || []).length + ' 个')
    );
    stateSec.append(kv);
    if (st.last_error) {
      stateSec.append(el('div', { class: 'detail-error' },
        svgIcon('alert', 'ico-sm'),
        el('div', {},
          el('div', { class: 'detail-error-text', text: st.last_error }),
          st.fail_count ? el('div', { class: 'detail-error-sub', text: '已经连续没查成 ' + st.fail_count + ' 次' }) : null
        )
      ));
    }
    host.append(stateSec);

    const archSec = el('div', { class: 'detail-sec' });
    archSec.append(el('div', { class: 'detail-sec-title' },
      el('span', { text: '版本架构' }),
      el('span', { class: 'ink-3', text: '选错会查不到更新' })
    ));
    archSec.append(segEl(['amd64', 'arm64'], ch.arch || 'amd64', function (v) {
      setChannelArch(ch.id, v);
    }));
    host.append(archSec);

    if ((st.ignored || []).length) {
      const ignoredSec = el('div', { class: 'detail-sec' });
      ignoredSec.append(el('div', { class: 'detail-sec-title' },
        el('span', { text: '已忽略的版本' }),
        el('button', {
          type: 'button', class: 'link-btn', text: '全部恢复',
          onclick: function () { clearIgnored(ch.id); }
        })
      ));
      const list = el('div', { class: 'ignored-list' });
      (st.ignored || []).forEach(function (v) {
        list.append(el('span', { class: 'ignored-chip', text: v }));
      });
      ignoredSec.append(list);
      ignoredSec.append(el('div', { class: 'field-hint', text: '这些版本不会再提醒你，报告也还在' }));
      host.append(ignoredSec);
    }

    if (ch.source === 'uupdump') {
      const urlSec = el('div', { class: 'detail-sec' });
      urlSec.append(el('div', { class: 'detail-sec-title' },
        el('span', { text: 'uupdump 分类' }),
        ch.url ? el('button', {
          type: 'button', class: 'link-btn', text: '在浏览器打开',
          onclick: function () { openExternal('browser', ch.url); }
        }) : null
      ));
      if (ch.category) urlSec.append(el('div', { class: 'kv-value mono', text: ch.category, title: ch.category, style: 'font-size:12.5px;margin-bottom:7px' }));
      if (ch.url) urlSec.append(el('div', { class: 'detail-url', text: ch.url, title: ch.url }));
      host.append(urlSec);
    }

    const reports = st.reports || [];
    const repSec = el('div', { class: 'detail-sec' });
    repSec.append(el('div', { class: 'detail-sec-title' }, el('span', { text: '这条线的报告' })));
    if (!reports.length) {
      repSec.append(el('div', { class: 'field-hint', text: '还没有报告。第一次检测到新版本后，会写一份中文解读放在这里。' }));
    } else {
      const list = el('div', { class: 'detail-reports' });
      reports.slice(0, 6).forEach(function (r) {
        list.append(el('button', {
          type: 'button', class: 'detail-report-row', title: r.summary || r.file || '',
          onclick: function () { openReportFile(r.file); }
        },
          el('span', { class: 'dr-date', text: r.date ? mmdd(r.date) : '' }),
          el('span', { class: 'dr-build', text: r.build || '' }),
          svgIcon('chevron-right')
        ));
      });
      repSec.append(list);
    }
    host.append(repSec);

    const actions = el('div', { class: 'detail-actions' },
      el('button', {
        type: 'button', class: 'btn btn-primary btn-sm', onclick: function () { checkChannel(ch.id); }
      }, svgIcon('play'), '只检测这条线'),
      st.last_report ? el('button', {
        type: 'button', class: 'btn btn-secondary btn-sm', text: '打开最近报告',
        onclick: function () { openReportFile(st.last_report); }
      }) : null,
      el('button', {
        type: 'button', class: 'btn btn-ghost btn-sm', text: '打开报告文件夹',
        onclick: function () { openExternal('report_folder'); }
      })
    );
    host.append(actions);
    host.append(el('div', { class: 'field-hint', style: 'margin-top:12px', text: '检测过程会显示在「日志与诊断」页，完成后会自动更新这里的版本和报告' }));
    /* 切换不同更新线时，右边的详情分层出现，让"内容换了"这件事有方向感 */
    if (wasFilled) staggerChildren(host.children, 'anim-item', 0, 14, 6);
  }

  /* ============================================================
     通知
     ============================================================ */
  /* 「暂时静默」：自己填时长（分钟/小时），不再写死 2 小时 */
  function quietForControl() {
    const qty = el('input', {
      class: 'input', type: 'number', value: '2', min: '1', max: '168',
      step: '1', 'aria-label': '静默多久', style: 'width:64px'
    });
    const unit = el('select', { class: 'input', 'aria-label': '静默时长的单位', style: 'width:80px' },
      el('option', { value: '60', text: '小时' }),
      el('option', { value: '1', text: '分钟' })
    );
    const btn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm', text: '静默',
      onclick: function () {
        const n = Math.round(Number(qty.value));
        const mins = n * Number(unit.value);
        if (!isFinite(n) || n < 1 || !isFinite(mins)) {
          toast('error', '静默时长要填一个大于 0 的数字');
          return;
        }
        if (mins > 7 * 24 * 60) { toast('error', '最多静默 7 天'); return; }
        quietNow(mins);
      }
    });
    return el('div', { style: 'display:flex;align-items:center;gap:8px' }, qty, unit, btn);
  }

  function renderNotify(host) {
    const cfg = state.config || {};

    host.append(sectionEl('检查节奏', null, cardEl(
      rowControl('多久检查一次', '后台监控开着的时候，按这个间隔自动查一遍',
        numInput({ key: 'watch_interval_minutes', value: cfg.watch_interval_minutes, min: 1, max: 1440, unit: '分钟', width: 96, label: '检查间隔' })),
      rowControl('连续出错几次才提醒', '网络偶尔抽风不算；连续出错到这个次数才发通知',
        numInput({ key: 'notify_on_error_after', value: cfg.notify_on_error_after, min: 1, max: 99, unit: '次', width: 80, label: '连续出错次数' }))
    )));

    const notifyOn = cfg.notify !== false;
    const mergeRow = switchRow('多条线的更新合并成一条通知', '一次发现好几个新版本时，只发一条，不刷屏',
      cfg.merge_notifications !== false, function (v) { queueSave('merge_notifications', v); });
    if (!notifyOn) {
      mergeRow.classList.add('is-disabled');
      const sw = mergeRow.querySelector('.switch');
      if (sw) sw.disabled = true;
    }
    host.append(sectionEl('通知', null, cardEl(
      switchRow('发现新版本时提醒我', notifyOn ? '用 Windows 通知提醒，右下角会弹出来' : '关掉后只在界面的「报告」里攒着',
        notifyOn, function (v) {
          state.config.notify = v;
          queueSave('notify', v);
          refreshPage();
        }),
      mergeRow
    )));

    const quietActive = cfg.silent_until && isFuture(cfg.silent_until);
    const gameOn = cfg.game_mode_enabled !== false;
    const holdRow = rowControl('退出全屏后等多久恢复', '刚退出游戏时先缓一缓，免得立刻弹通知',
      numInput({ key: 'game_exit_hold_seconds', value: cfg.game_exit_hold_seconds, min: 0, max: 3600, unit: '秒', width: 88, label: '恢复等待秒数' }),
      { disabled: !gameOn });
    if (!gameOn) {
      const inp = holdRow.querySelector('input');
      if (inp) inp.disabled = true;
    }
    const ignoreChips = el('div', { class: 'chips' });
    const ignoreList = (cfg.game_ignore || []).filter(Boolean);
    if (!ignoreList.length) {
      ignoreChips.append(el('span', { class: 'field-hint', style: 'margin:0', text: '名单是空的' }));
    } else {
      ignoreList.forEach(function (name) {
        ignoreChips.append(el('span', { class: 'chip' },
          el('span', { text: name }),
          el('button', {
            type: 'button', class: 'link-btn', title: '从名单里移掉', 'aria-label': '移掉 ' + name,
            onclick: function () {
              const next = (state.config.game_ignore || []).filter(function (x) { return x !== name; });
              state.config.game_ignore = next;
              queueSave('game_ignore', next);
              refreshPage();
            }
          }, '✕')
        ));
      });
    }

    host.append(sectionEl('不打扰', null, cardEl(
      rowControl('免打扰时段', '这个时间段里不弹通知；留空表示不启用',
        el('div', {},
          textInput({
            key: 'quiet_hours', value: cfg.quiet_hours, placeholder: '23:00-07:00',
            width: 132, label: '免打扰时段'
          }),
          el('div', { class: 'field-err', 'data-err': 'quiet_hours', hidden: true })
        )),
      switchRow('全屏玩游戏时先不打扰我', '检测到你正全屏玩游戏，就先不检查、不弹通知',
        gameOn, function (v) {
          state.config.game_mode_enabled = v;
          queueSave('game_mode_enabled', v);
          refreshPage();
        }),
      holdRow,
      el('div', { class: 'row' },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-label', text: '忽略的游戏或程序' }),
          el('div', { class: 'row-help', text: '这些程序全屏时，同样先不打扰你' }),
          el('div', { class: 'chips', style: 'margin-top:8px' }, ignoreChips)
        ),
        el('div', { class: 'row-ctl' },
          el('button', {
            type: 'button', class: 'btn btn-secondary btn-sm', text: '选择程序…',
            onclick: function () { openIgnorePicker(); }
          })
        )
      ),
      el('div', { class: 'row' },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-label', text: '暂时静默' }),
          el('div', { class: 'row-help', text: quietActive
            ? '现在处于静默状态，' + hhmm(cfg.silent_until) + ' 之后恢复检查'
            : '临时不想被打扰时，自己填一个时长；到点自动恢复检查' })
        ),
        el('div', { class: 'row-ctl' },
          quietActive
            ? el('button', {
              type: 'button', class: 'btn btn-secondary btn-sm', text: '取消静默',
              onclick: function () { quietNow(); }
            })
            : quietForControl()
        )
      )
    )));

    const trayCard = el('div', { class: 'card' });
    const trayGrid = el('div', { class: 'tray-grid' });
    (state.trayStyles || []).forEach(function (t) {
      const btn = el('button', {
        type: 'button', class: 'tray-tile', 'aria-pressed': t.active ? 'true' : 'false',
        title: t.name, onclick: function () { setTrayStyle(t.id); }
      });
      if (t.preview) {
        btn.append(el('img', { src: t.preview, alt: '', draggable: 'false' }));
      } else {
        btn.append(el('span', { class: 'tray-ph', text: '·' }));
      }
      btn.append(el('span', { class: 'tray-name', text: t.name }));
      trayGrid.append(btn);
    });
    trayCard.append(trayGrid);
    trayCard.append(el('div', { class: 'field-hint', style: 'margin-top:10px', text: '这是右下角托盘里的样子；改完几秒内就会换过来' }));
    host.append(sectionEl('托盘图标',
      el('span', { class: 'num', text: (state.trayStyles || []).length + ' 款' }),
      trayCard));

    const options = state.detailOptions || ['简短', '标准', '详细'];
    const detailCard = el('div', { class: 'card' },
      el('div', { class: 'settings-row' },
        el('div', { class: 'settings-main' },
          el('div', { class: 'row-label', text: '报告写多详细' }),
          el('div', { class: 'row-help', text: '越详细，读起来越完整，写起来也越慢' })
        ),
        el('div', { class: 'settings-ctl' },
          segEl(options, cfg.detail || '标准', function (v) {
            state.config.detail = v;
            queueSave('detail', v);
          })
        )
      )
    );
    host.append(sectionEl('报告详细程度', null, detailCard));
  }

  /* ============================================================
     设置
     ============================================================ */
  function renderSettings(host) {
    const cfg = state.config || {};
    const hasKey = !!String(cfg.api_key || '').trim();

    const baseInput = textInput({
      key: 'api_base', value: cfg.api_base, mono: true, live: true, width: '100%',
      placeholder: 'https://api.deepseek.com', label: 'AI 服务地址'
    });
    const modelInput = textInput({
      key: 'model', value: cfg.model, mono: true, live: true, width: '100%',
      placeholder: 'deepseek-flash', label: '模型'
    });

    const keyInput = el('input', {
      class: 'input mono', type: 'password',
      value: cfg.api_key || '', 'data-field': 'api_key',
      placeholder: 'sk-…', 'aria-label': 'AI 的 Key', autocomplete: 'off', spellcheck: 'false'
    });
    keyInput.addEventListener('change', function () {
      const v = keyInput.value.trim();
      if (v === String(state.config.api_key || '')) return;
      state.config.api_key = v;
      queueSave('api_key', v);
    });
    const eyeBtn = el('button', {
      type: 'button', class: 'icon-btn', 'aria-label': '显示 Key', title: '显示 Key',
      style: 'width:26px;height:26px'
    }, svgIcon('eye', 'ico-sm'));
    eyeBtn.addEventListener('click', function () {
      const show = keyInput.type === 'password';
      keyInput.type = show ? 'text' : 'password';
      eyeBtn.title = show ? '隐藏 Key' : '显示 Key';
      eyeBtn.setAttribute('aria-label', eyeBtn.title);
      eyeBtn.textContent = '';
      eyeBtn.append(svgIcon(show ? 'eye-off' : 'eye', 'ico-sm'));
    });
    const testBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm', text: '测试',
      onclick: function () { testApi(); }
    });
    const keyWrap = el('div', { class: 'password-wrap' }, keyInput,
      el('div', { class: 'password-tools' }, eyeBtn));
    const keyLine = el('div', { class: 'inline-field' }, keyWrap, testBtn);

    const aiCard = el('div', { class: 'card' },
      settingsRow('AI 服务地址', '一般不用改', baseInput, { wide: true }),
      settingsRow('AI 的 Key', hasKey ? '只保存在本机的设置里' : '必填；不填的话，发现新版本也写不出中文报告',
        el('div', { style: 'width:100%' },
          keyLine,
          el('div', { class: 'field-hint', 'data-ref': 'apiTest', text: state.apiTestResult || '' })
        ), { wide: true }),
      settingsRow('用哪个模型', '比如 deepseek-flash', modelInput, { wide: true }),
      settingsRow('关闭思考，回答更快', '有些模型不支持思考模式，关掉也不影响使用',
        switchEl(cfg.disable_thinking !== false, function (v) {
          state.config.disable_thinking = v;
          queueSave('disable_thinking', v);
        }, '关闭思考'))
    );
    host.append(sectionEl('AI', null, aiCard));

    /* 高级选项（可折叠） */
    const advancedRows = el('div', {});
    advancedRows.append(
      settingsRow('最大输出长度', '每次让 AI 写多少字，太长会变慢',
        numInput({ key: 'max_tokens', value: cfg.max_tokens, min: 100, max: 8000, unit: '字', width: 92 }), { wide: true }),
      settingsRow('温度', '0 更稳，1 更活；写报告一般用 0.3',
        numInput({ key: 'temperature', value: cfg.temperature, min: 0, max: 2, step: 0.1, float: true, unit: '', width: 80 }), { wide: true }),
      settingsRow('单次请求超时', '网络慢的时候可以调大',
        numInput({ key: 'request_timeout', value: cfg.request_timeout, min: 10, max: 900, unit: '秒', width: 92 }), { wide: true }),
      settingsRow('失败重试', '请求失败后自动再试几次',
        numInput({ key: 'retries', value: cfg.retries, min: 0, max: 10, unit: '次', width: 80 }), { wide: true }),
      settingsRow('同时检测几条线', '网络好的话可以多一点',
        numInput({ key: 'max_workers', value: cfg.max_workers, min: 1, max: 16, unit: '条', width: 80 }), { wide: true }),
      settingsRow('报告最多读多少原文', '给 AI 的官方原文上限，太大容易超时',
        numInput({ key: 'max_context_chars', value: cfg.max_context_chars, min: 1000, max: 200000, unit: '字', width: 100 }), { wide: true }),
      settingsRow('保留最近几份报告', '更早的报告会被自动清理',
        numInput({ key: 'keep_reports', value: cfg.keep_reports, min: 10, max: 5000, unit: '份', width: 88 }), { wide: true }),
      settingsRow('代理地址', '留空表示不使用代理',
        textInput({ key: 'proxy', value: cfg.proxy, mono: true, live: true, width: '100%', placeholder: 'http://127.0.0.1:7890' }), { wide: true }),
      settingsRow('报告里附上官方原文', '会多贴一段英文原文，方便对照',
        switchEl(!!cfg.include_official_text, function (v) {
          state.config.include_official_text = v;
          queueSave('include_official_text', v);
        }, '附带官方原文')),
      settingsRow('点报告时直接用浏览器打开', '默认在界面里看；打开后也可以再用浏览器看',
        switchEl(!!cfg.open_report_on_click, function (v) {
          state.config.open_report_on_click = v;
          queueSave('open_report_on_click', v);
        }, '点报告时用浏览器打开'))
    );
    advancedRows.querySelectorAll('.settings-row').forEach(function (r) { r.style.padding = '9px 0'; });

    const foldInner = el('div', { class: 'fold-body-in' }, advancedRows);
    const foldBody = el('div', { class: 'fold-body' }, foldInner);
    foldBody.hidden = !state.foldAdvanced;
    const foldHead = el('button', {
      type: 'button', class: 'fold-head', 'aria-expanded': state.foldAdvanced ? 'true' : 'false'
    },
      el('div', { class: 'fold-head-main' },
        el('span', { class: 'fold-title', text: '高级选项' }),
        el('span', { class: 'fold-sub', text: '模型、超时、并发、报告保存' })
      ),
      svgIcon('chevron-down')
    );
    const foldCard = el('div', { class: 'card fold-card' + (state.foldAdvanced ? ' is-open' : '') },
      foldHead, foldBody);
    foldHead.addEventListener('click', function () {
      const open = !state.foldAdvanced;
      state.foldAdvanced = open;
      foldHead.setAttribute('aria-expanded', open ? 'true' : 'false');
      foldCard.classList.toggle('is-open', open);
      animateFold(foldBody, open);
      if (open) {
        setTimeout(function () {
          try {
            foldBody.scrollIntoView({ block: 'nearest', behavior: motionOff() ? 'auto' : 'smooth' });
          } catch (e) { /* 预览环境没有 smooth 也就算了 */ }
        }, 300);
      }
    });
    host.append(el('section', { class: 'sec' }, foldCard));

    const aboutCard = el('div', { class: 'card' },
      el('div', { class: 'settings-row' },
        el('div', { class: 'settings-main' },
          el('div', { class: 'row-label', text: '程序位置' }),
          el('div', { class: 'row-help mono truncate', text: state.app.exe || '—', title: state.app.exe || '' })
        ),
        el('div', { class: 'settings-ctl' },
          el('button', {
            type: 'button', class: 'btn btn-secondary btn-sm', text: '打开程序目录',
            onclick: function () { openExternal('app_folder'); }
          })
        )
      ),
      el('div', { class: 'settings-row' },
        el('div', { class: 'settings-main' },
          el('div', { class: 'row-label', text: '设置存在哪里' }),
          el('div', { class: 'row-help mono truncate', text: state.app.base_dir || '—', title: state.app.base_dir || '' })
        ),
        el('div', { class: 'settings-ctl' },
          el('button', {
            type: 'button', class: 'btn btn-secondary btn-sm', text: '打开设置目录',
            onclick: function () { openExternal('folder', state.app.base_dir || ''); }
          })
        )
      )
    );
    host.append(sectionEl('关于', null, aboutCard));
  }

  /* ============================================================
     自启与后台
     ============================================================ */
  function renderStartup(host) {
    const w = state.watch || {};
    const cfg = state.config || {};

    const statusCard = el('div', { class: 'card' },
      el('div', { class: 'status-line' },
        el('span', { class: 'dot dot-off', 'data-ref': 'stDot' }),
        el('div', { class: 'status-line-main' },
          el('div', { class: 'status-line-title', 'data-ref': 'stTitle', text: '正在读取…' }),
          el('div', { class: 'status-line-meta', 'data-ref': 'stMeta' })
        )
      ),
      el('div', { class: 'status-line-actions' },
        el('button', {
          type: 'button', class: 'btn btn-primary', onclick: function () { toggleWatch(); }
        }, el('span', { 'data-ref': 'stToggleLabel', text: '开启后台监控' })),
        el('button', {
          type: 'button', class: 'btn btn-secondary', text: '立刻检查',
          onclick: function () { checkNow(); }
        }),
        el('button', {
          type: 'button', class: 'btn btn-secondary', text: '测试通知',
          onclick: function () { testToast(); }
        })
      )
    );
    host.append(sectionEl('后台现在', null, statusCard));

    /* 办法一：登录自启 */
    const startupSwitch = switchEl(!!(state.startup && state.startup.enabled), function (next) {
      state.startupTouchedAt = Date.now();
      state.startup = Object.assign({}, state.startup, { enabled: next });
      updateStatusWidgets();
      toggleStartup();
    }, '登录后自动启动');
    startupSwitch.setAttribute('data-ref', 'stStartupSwitch');
    const startupCard = el('div', { class: 'card' },
      el('div', { class: 'row-help', style: 'margin:0 0 6px' , text: '登录 Windows 之后自动在右下角跑起来，不用管理员权限。' }),
      el('div', { class: 'switch-row' },
        el('div', { class: 'row-main' },
          el('div', { class: 'row-label', text: '登录后自动启动' }),
          el('div', { class: 'row-help' }, '现在：', el('span', { 'data-ref': 'stStartupState', text: '未开启' }))
        ),
        startupSwitch
      ),
      state.app.startup_link ? el('div', {
        class: 'field-hint mono truncate', style: 'margin-top:10px',
        text: state.app.startup_link, title: state.app.startup_link
      }) : null,
      el('div', { class: 'field-hint', style: 'margin-top:8px', text: '开启后，下次登录就会自动跑；想立刻用，点上面的「开启后台监控」' })
    );
    host.append(sectionEl('办法一 · 登录自启', el('span', { text: '不需要管理员' }), startupCard));

    /* 办法二：后台任务（计划任务） */
    const refreshTaskBtn = el('button', {
      type: 'button', class: 'link-btn', text: '刷新状态',
      onclick: function () { refreshTaskInfo(); }
    });
    const removeBtn = el('button', {
      type: 'button', class: 'btn btn-ghost btn-sm is-armed-hover', text: '移除'
    });
    removeBtn.addEventListener('click', function () {
      confirmThen(removeBtn, '再点一次移除', function () { removeTask(); });
    });
    const taskCard = el('div', { class: 'card' },
      el('div', { class: 'row-help', style: 'margin:0 0 6px', text: '想让它在登录前就开始检查，或者想更稳地一直待在后台，用这个办法。安装时会弹一次 Windows 管理员确认。' }),
      el('div', { class: 'detail-actions', style: 'margin-top:10px' },
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '安装后台任务',
          onclick: function () { installTask(); }
        }),
        removeBtn,
        refreshTaskBtn
      ),
      el('div', { class: 'task-box' },
        el('span', { class: 'task-text', 'data-ref': 'taskText', text: humanTaskText(state.taskText) || '正在查询…', title: humanTaskText(state.taskText) }),
        el('button', {
          type: 'button', class: 'icon-btn', title: '刷新状态', 'aria-label': '刷新后台任务状态',
          onclick: function () { refreshTaskInfo(); }
        }, svgIcon('refresh', 'ico-sm'))
      ),
      el('div', { class: 'field-hint', style: 'margin-top:8px', text: '如果管理员确认被取消了，可以改用上面的「登录自启」这个免管理员办法' })
    );
    host.append(sectionEl('办法二 · 后台任务', el('span', { text: '需要管理员' }), taskCard));

    /* 快捷方式与通知身份 */
    const shortCard = el('div', { class: 'card' },
      el('div', { class: 'button-grid' },
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { makeShortcut('desktop'); }
        }, svgIcon('download'), '创建桌面快捷方式'),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { makeShortcut('startmenu'); }
        }, svgIcon('plus'), '添加到开始菜单'),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { registerApp(); }
        }, svgIcon('bell'), '注册通知身份')
      ),
      el('div', { class: 'field-hint', style: 'margin-top:9px', text: '注册之后，通知里会显示程序的名字和图标；只需要做一次' })
    );
    host.append(sectionEl('快捷方式', null, shortCard));

    /* 诊断 */
    const diagCard = el('div', { class: 'card' },
      el('div', { class: 'button-grid' },
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { runSelfcheck(); }
        }, svgIcon('shield'), '体检并自动修复'),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { testToast(); }
        }, svgIcon('bell'), '发一条测试通知'),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { openExternal('log'); }
        }, svgIcon('terminal'), '打开日志文件'),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { openExternal('app_folder'); }
        }, svgIcon('folder'), '打开程序目录'),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm',
          onclick: function () { openExternal('report_folder'); }
        }, svgIcon('doc'), '打开报告目录')
      ),
      el('div', { class: 'field-hint', style: 'margin-top:9px', text: '体检会修好能修的问题，结果显示在「日志与诊断」里' }),

    );
    host.append(sectionEl('诊断工具', null, diagCard));
  }

  /* ============================================================
     报告
     ============================================================ */
  /** 窄窗口不再并排挤双栏：列表占满，点一份报告直接用阅读器打开。 */
  function reportsNarrow() {
    try {
      return !!(window.matchMedia && window.matchMedia('(max-width: 1080px)').matches);
    } catch (e) { return false; }
  }

  function renderReports(host) {
    const reports = state.reports || [];
    const channelsInReports = [];
    const seen = {};
    reports.forEach(function (r) {
      if (!r.channel_id || seen[r.channel_id]) return;
      seen[r.channel_id] = 1;
      channelsInReports.push({ id: r.channel_id, name: r.channel_name || r.channel_id });
    });

    const filter = el('select', {
      class: 'input', 'aria-label': '按更新线筛选报告',
      onchange: function (e) {
        state.reportChannelFilter = e.target.value;
        renderReportList();
      }
    }, el('option', { value: '', text: '全部更新线' }),
      channelsInReports.map(function (c) {
        return el('option', { value: c.id, text: c.name, selected: state.reportChannelFilter === c.id });
      }));

    const listHost = el('div', { class: 'report-list', 'aria-live': 'polite' });
    state.reportListHost = listHost;
    const left = el('div', { class: 'panel list-panel' },
      el('div', { class: 'filter-bar' }, filter),
      listHost
    );

    if (reportsNarrow()) {
      state.reportViewHost = null;
      host.append(el('div', { class: 'split cols-report single' }, left));
      renderReportList();
      return;
    }

    const viewHost = el('div', { class: 'panel panel-pad' });
    state.reportViewHost = viewHost;

    host.append(el('div', { class: 'split cols-report' }, left, viewHost));
    renderReportList();
    renderReportView();
  }

  function filteredReports() {
    return (state.reports || []).filter(function (r) {
      if (state.reportChannelFilter && r.channel_id !== state.reportChannelFilter) return false;
      return true;
    });
  }

  function renderReportList() {
    const host = state.reportListHost;
    if (!host) return;
    host.textContent = '';
    const reports = filteredReports();
    if (!reports.length) {
      host.append(emptyEl('doc', '还没有报告',
        (state.reports || []).length ? '这条更新线还没有写过报告' : '检测到新版本后，这里会出现对应的中文解读',
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '打开报告文件夹',
          onclick: function () { openExternal('report_folder'); }
        })));
      return;
    }
    reports.forEach(function (r) {
      host.append(el('button', {
        type: 'button', class: 'report-row' + (r.file === state.reportSel ? ' is-sel' : ''),
        title: r.file || '', onclick: function () {
          if (state.config && state.config.open_report_on_click) { openExternal('browser', r.file); return; }
          state.reportSel = r.file;
          renderReportList();
          if (reportsNarrow()) { openReader(r.file); return; }
          renderReportView();
          ensureReportPreview();
        }
      },
        el('div', { class: 'report-row-top' },
          el('span', { class: 'report-row-name', text: compactName(r.channel_name) || '更新报告', title: r.channel_name || '' }),
          el('span', { class: 'report-row-build', text: r.build || '' })
        ),
        el('div', { class: 'report-row-sub' },
          el('span', { class: 'report-row-date', text: r.date ? mmdd(r.date) : mmdd(r.mtime) }),
          el('span', { class: 'report-row-sum', text: r.summary || '（没有一句话总结）', title: r.summary || '' })
        )
      ));
    });
  }

  function renderReportView() {
    const host = state.reportViewHost;
    if (!host) return;
    const wasFilled = host.childElementCount > 0;
    host.textContent = '';
    const r = findReport(state.reportSel);
    if (!r) {
      host.append(emptyEl('doc', '选一份报告', '点一份报告开始阅读；也可以去「全部报告」翻历史',
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '打开报告文件夹',
          onclick: function () { openExternal('report_folder'); }
        })));
      return;
    }
    const view = el('div', { class: 'report-view' });
    const head = el('div', { class: 'report-view-head' },
      el('div', { class: 'report-view-title' },
        el('div', { class: 'report-view-name', text: compactName(r.channel_name) || '更新报告', title: (r.channel_name || '') + '\n' + (r.file || '') }),
        el('div', { class: 'report-view-meta' },
          el('span', { text: r.date ? mmdd(r.date) : mmdd(r.mtime) }),
          el('span', { class: 'm-sep', text: '·' }),
          el('span', { class: 'mono', text: r.build || '' })
        )
      ),
      el('div', { class: 'report-view-actions' },
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '阅读模式',
          onclick: function () { openReader(r.file); }
        }),
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '在浏览器打开',
          onclick: function () { openExternal('browser', r.file); }
        }),
        el('button', {
          type: 'button', class: 'icon-btn', title: '打开报告文件夹', 'aria-label': '打开报告文件夹',
          onclick: function () { openExternal('report_folder'); }
        }, svgIcon('folder'))
      )
    );
    view.append(head);

    const cached = state.reportHtml.get(r.file);
    if (cached && cached.html) {
      view.append(mountReportFrame(cached.html));
    } else if (cached && cached.error) {
      view.append(el('div', { class: 'report-frame-wrap' },
        emptyEl('alert', '这份报告打不开',
          cached.error + '；可以试试「在浏览器打开」',
          el('button', {
            type: 'button', class: 'btn btn-secondary btn-sm', text: '在浏览器打开',
            onclick: function () { openExternal('browser', r.file); }
          }))));
    } else {
      const wrap = el('div', { class: 'report-frame-wrap' },
        el('div', { class: 'frame-loading' }, el('span', { class: 'spinner' }), el('span', { text: '正在打开报告…' })));
      view.append(wrap);
      ensureReportPreview();
    }
    host.append(view);
    if (wasFilled) staggerChildren(view.children, 'anim-item', 0, 16, 4);
  }

  function mountReportFrame(html) {
    const wrap = el('div', { class: 'report-frame-wrap' });
    const frame = el('iframe', {
      class: 'report-frame', title: '报告内容',
      sandbox: 'allow-same-origin allow-popups'
    });
    const loading = el('div', { class: 'frame-loading' }, el('span', { class: 'spinner' }), el('span', { text: '正在打开报告…' }));
    frame.addEventListener('load', function () { loading.hidden = true; });
    frame.srcdoc = reportDoc(html);
    wrap.append(frame, loading);
    return wrap;
  }

  async function ensureReportPreview() {
    const r = findReport(state.reportSel);
    if (!r) return;
    if (state.reportHtml.has(r.file)) return;
    const token = ++state.previewToken;
    state.reportHtml.set(r.file, { loading: true });
    const a = bridge();
    if (!a) return;
    try {
      const res = await a.report_html(r.file);
      if (res && res.ok) state.reportHtml.set(r.file, { html: res.html || '', title: res.title || '' });
      else state.reportHtml.set(r.file, { error: (res && res.error) || '读不出来' });
    } catch (e) {
      noteErr(e);
      state.reportHtml.set(r.file, { error: '读不出来' });
    }
    if (token === state.previewToken && state.page === 'reports') renderReportView();
  }

  /* ============================================================
     日志与诊断
     ============================================================ */
  function renderLogs(host) {
    const showLive = state.liveLines.length > 0 || state.liveActive;
    if (showLive) {
      const liveHead = el('span', { class: 'live-head' },
        el('span', { class: 'dot ' + (state.liveActive ? 'dot-ok is-live' : 'dot-off') }),
        el('span', { text: state.liveActive ? '正在检测…' : '上次检测输出' })
      );
      const card = el('div', { class: 'card' });
      card.append(el('div', { class: 'log-toolbar' },
        liveHead,
        el('span', { class: 'list-count', 'data-ref': 'liveCount', text: state.liveLines.length + ' 行' })
      ));
      const pre = el('pre', { class: 'log-pre live-pre', 'data-ref': 'livePre', tabindex: '0' });
      card.append(pre);
      host.append(sectionEl('本次检测输出', el('span', { text: '实时' }), card));
    }

    const logCard = el('div', { class: 'card' });
    logCard.append(el('div', { class: 'log-toolbar' },
      el('div', { class: 'log-hint' },
        svgIcon('terminal', 'ico-sm'),
        el('span', { class: 'mono truncate', text: state.logPath || '日志文件', title: state.logPath || '', style: 'max-width:340px' })
      ),
      el('div', { class: 'log-actions' },
        el('button', {
          type: 'button', class: 'btn btn-ghost btn-sm', text: '刷新',
          onclick: function () { loadLog(false); }
        }),
        el('button', {
          type: 'button', class: 'btn btn-ghost btn-sm', text: '打开',
          onclick: function () { openExternal('log'); }
        }),
        (function () {
          const btn = el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '清空' });
          btn.addEventListener('click', function () {
            confirmThen(btn, '再点一次清空', function () { clearLog(); });
          });
          return btn;
        })()
      )
    ));
    const pre = el('pre', { class: 'log-pre', 'data-ref': 'logPre', tabindex: '0' });
    logCard.append(pre);
    host.append(sectionEl('程序日志', el('span', { text: '自动刷新' }), logCard));

    const checkCard = el('div', { class: 'card' });
    const checkHost = el('div', {});
    state.checkHost = checkHost;
    const runBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm', text: '运行体检',
      onclick: function () { runSelfcheck(); }
    });
    checkCard.append(el('div', { class: 'log-toolbar', style: 'margin-bottom:2px' },
      el('div', { class: 'log-hint', text: state.selfcheck ? '检查完会自动修好能修的问题' : '看看有没有哪里没弄好' }),
      el('div', { class: 'log-actions' }, runBtn)
    ), checkHost);
    host.append(sectionEl('体检结果', null, checkCard));

    updateLogPre();
    updateLivePre();
    renderCheckBlock();
    ensureLogLoaded();
  }

  function renderCheckBlock() {
    const host = state.checkHost;
    if (!host) return;
    host.textContent = '';
    const sc = state.selfcheck;
    if (!sc) {
      host.append(emptyEl('shield', '还没体检过', '运行一次体检，能自动修好大部分问题'));
      return;
    }
    const list = el('div', { class: 'check-list' });
    (sc.items || []).forEach(function (item) {
      const status = item.status || 'warn';
      const iconName = status === 'ok' ? 'check' : status === 'fixed' ? 'refresh' : status === 'fail' ? 'x' : 'alert';
      list.append(el('div', { class: 'check-item' },
        el('span', { class: 'check-badge ' + status }, svgIcon(iconName)),
        el('div', { class: 'check-main' },
          el('div', { class: 'check-name', text: item.name || '' }),
          item.msg ? el('div', { class: 'check-msg', text: item.msg }) : null
        )
      ));
    });
    host.append(list);
    staggerChildren(list.children, 'anim-row', 20, 22, 6);
    if (sc.summary) host.append(el('div', { class: 'check-summary', text: sc.summary }));
  }

  function updateLivePre() {
    const cnt = document.querySelector('[data-ref="liveCount"]');
    if (cnt) {
      const t = state.liveLines.length + ' 行';
      if (cnt.textContent !== t) { cnt.textContent = t; bumpEl(cnt); }
    }
    const pre = document.querySelector('[data-ref="livePre"]');
    if (!pre) return;
    const text = state.liveLines.length ? state.liveLines.join('\n') : '这次检测还没有输出';
    const empty = !state.liveLines.length;
    if (pre.dataset.value === text) return;
    const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 30;
    pre.dataset.value = text;
    pre.textContent = text;
    pre.classList.toggle('is-empty', empty);
    if (atBottom) pre.scrollTop = pre.scrollHeight;
  }

  function updateLogPre() {
    const pre = document.querySelector('[data-ref="logPre"]');
    if (!pre) return;
    let text;
    if (!state.logLoaded) text = '正在读取日志…';
    else if (!state.logText) text = '日志是空的';
    else text = state.logText;
    const empty = !state.logLoaded || !state.logText;
    if (pre.dataset.value === text) return;
    const atBottom = pre.scrollHeight - pre.scrollTop - pre.clientHeight < 30;
    pre.dataset.value = text;
    pre.textContent = text;
    pre.classList.toggle('is-empty', empty);
    if (atBottom || !state.logText) pre.scrollTop = pre.scrollHeight;
  }

  function ensureLogLoaded() {
    if (state.logLoaded || state.logLoading) return;
    loadLog(false);
  }

  async function loadLog(quiet) {
    if (state.logLoading) return;
    const a = bridge();
    if (!a) return;
    state.logLoading = true;
    try {
      const r = await a.read_log();
      if (r && r.ok) {
        state.logText = r.text || '';
        state.logPath = r.path || state.logPath;
        state.logLoaded = true;
        state.logAt = new Date();
      } else if (r) {
        state.logText = '读取日志失败：' + (r.error || '未知原因');
        state.logLoaded = true;
      }
    } catch (e) {
      noteErr(e);
      state.logText = '读取日志失败';
      state.logLoaded = true;
    }
    state.logLoading = false;
    if (state.page === 'logs') updateLogPre();
  }

  /* ============================================================
     动作
     ============================================================ */
  async function toggleWatch() {
    const online = !!(state.watch && state.watch.online);
    const r = await callApi('toggle_watch', [], {
      busy: online ? '正在停止后台监控…' : '正在开启后台监控…',
      failText: '没法切换后台监控'
    });
    if (r && r.ok) {
      if (typeof r.online === 'boolean') state.watch.online = r.online;
      updateStatusWidgets();
      refreshPage();
      if (r.message) toast('ok', r.message);
    }
  }

  async function checkNow() {
    await callApi('check_now', [], { busy: '正在检查更新…', failText: '没法立刻检查' });
  }

  async function checkChannel(id) {
    await callApi('check_channel', [id], { busy: '正在检测这条线…', failText: '没能开始检测' });
  }

  async function quietNow(minutes) {
    const args = (minutes === undefined || minutes === null) ? [] : [minutes];
    const r = await callApi('quiet_now', args, { failText: '没能切换静默' });
    if (r && r.ok) {
      if (r.config) state.config = r.config;
      if (r.message) toast('ok', r.message);
      refreshPage();
    }
  }

  /* ============================================================
     忽略名单：从当前桌面的窗口里选（不再只看前台窗口——点按钮时
     前台窗口就是设置窗口自己）
     ============================================================ */
  async function openIgnorePicker() {
    const r = await callApi('list_windows', [], { failText: '取不到窗口列表' });
    if (!r || !r.ok) return;
    showWindowPicker((r.windows || []).filter(function (w) { return !w.ignored; }));
  }

  function addIgnore(name) {
    name = String(name || '').trim();
    if (!name) return false;
    const cur = (state.config.game_ignore || []).slice();
    if (cur.some(function (x) { return String(x).toLowerCase() === name.toLowerCase(); })) {
      toast('info', name + ' 已经在忽略名单里了');
      return false;
    }
    cur.push(name);
    state.config.game_ignore = cur;
    queueSave('game_ignore', cur);
    toast('ok', '已把 ' + name + ' 加进忽略名单');
    refreshPage();
    return true;
  }

  function ensurePicker() {
    let root = $('#windowPicker');
    if (root) return root;
    root = el('div', { class: 'picker', id: 'windowPicker', hidden: true });
    const panel = el('div', {
      class: 'picker-panel', role: 'dialog', 'aria-modal': 'true',
      'aria-labelledby': 'pickerTitle', tabindex: '-1'
    },
      el('div', { class: 'picker-bar' },
        el('div', { class: 'picker-title', id: 'pickerTitle', text: '选择要忽略的程序' }),
        el('button', {
          type: 'button', class: 'icon-btn', title: '关闭（Esc）', 'aria-label': '关闭',
          onclick: function () { closePicker(); }
        }, svgIcon('x'))
      ),
      el('div', { class: 'picker-help', text: '下面是当前桌面上打开的窗口（最小化的也算）。点一行，就把那个程序加进忽略名单：以后它全屏时不再触发静默。' }),
      el('div', { class: 'picker-list', id: 'pickerList' }),
      el('div', { class: 'picker-empty', id: 'pickerEmpty', hidden: true, text: '没有可添加的窗口。' })
    );
    root.append(panel);
    root.addEventListener('click', function (e) { if (e.target === root) closePicker(); });
    document.body.append(root);
    return root;
  }

  function updatePickerEmpty(root) {
    root = root || $('#windowPicker');
    if (!root) return;
    const list = root.querySelector('#pickerList');
    const empty = root.querySelector('#pickerEmpty');
    if (empty) empty.hidden = !!(list && list.children.length);
  }

  function showWindowPicker(windows) {
    const root = ensurePicker();
    const panel = root.querySelector('.picker-panel');
    const list = root.querySelector('#pickerList');
    list.textContent = '';
    (windows || []).forEach(function (w) {
      const row = el('button', {
        type: 'button', class: 'picker-row', title: w.title || w.name || ''
      },
        el('div', { class: 'picker-row-main' },
          el('div', { class: 'picker-row-title', text: w.title || '（没有标题）' }),
          el('div', {
            class: 'picker-row-sub',
            text: (w.name || '') + (w.count > 1 ? ' · ' + w.count + ' 个窗口' : '')
          })
        ),
        el('span', { class: 'picker-add', text: '加入忽略' })
      );
      row.addEventListener('click', function () {
        if (addIgnore(w.name)) {
          row.remove();
          updatePickerEmpty(root);
        }
      });
      list.append(row);
    });
    updatePickerEmpty(root);
    root.hidden = false;
    state.pickerOpen = true;
    state.lastFocus = document.activeElement;
    if (panel && panel.focus) panel.focus();
  }

  function closePicker() {
    const root = $('#windowPicker');
    if (!root || root.hidden) return;
    root.hidden = true;
    state.pickerOpen = false;
    if (state.lastFocus && state.lastFocus.isConnected) {
      try { state.lastFocus.focus(); } catch (e) { /* 焦点回不去就算了 */ }
    }
  }

  async function testToast() {
    await callApi('test_toast', [], { busy: '正在发一条测试通知…' });
  }

  async function testApi() {
    setRefText('apiTest', '正在测试…');
    await callApi('test_api', [], { busy: '正在测试 AI 的 Key…' });
  }

  async function runSelfcheck() {
    await callApi('run_selfcheck', [], { busy: '正在体检并自动修复…' });
  }

  async function installTask() {
    await callApi('install_task', [], { busy: '正在请求管理员权限…', failText: '没能安装后台任务' });
  }

  async function removeTask() {
    await callApi('remove_task', [], { busy: '正在移除后台任务…', failText: '没能移除后台任务' });
  }

  async function toggleStartup() {
    const r = await callApi('toggle_startup', [], { busy: '正在设置开机自启…', failText: '没能改开机自启' });
    if (r && r.ok) {
      state.startupTouchedAt = Date.now();
      if (r.message) toast('ok', r.message);
    } else {
      state.startupTouchedAt = 0;
      updateStatusWidgets();
    }
  }

  async function registerApp() {
    const r = await callApi('register_app', [], { failText: '没能注册通知身份' });
    if (r && r.message) toast('ok', r.message);
  }

  async function makeShortcut(where) {
    const r = await callApi('make_shortcut', [where], { failText: '没能创建快捷方式' });
    if (r && r.message) toast('ok', r.message);
  }

  async function setTrayStyle(id) {
    const r = await callApi('set_tray_style', [id]);
    if (r && r.ok) {
      state.config.tray_style = id;
      state.trayStyles.forEach(function (t) { t.active = t.id === id; });
      if (r.message) toast('ok', r.message);
      refreshPage();
    }
  }

  async function setChannelEnabled(id, enabled) {
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.set_channel_enabled(id, !!enabled);
      if (r && r.ok) {
        if (Array.isArray(r.channels)) applyChannels(r.channels);
        else refreshChannels();
        if (r.message) toast('ok', r.message);
      } else {
        toast('error', (r && r.error) || '没能改这条更新线');
        refreshPage();
      }
    } catch (e) { noteErr(e); toast('error', '没能改这条更新线'); refreshPage(); }
  }

  async function setChannelArch(id, arch) {
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.set_channel_arch(id, arch);
      if (r && r.ok) {
        if (Array.isArray(r.channels)) applyChannels(r.channels);
        else refreshChannels();
        if (r.message) toast('ok', r.message);
      } else {
        toast('error', (r && r.error) || '没能改架构');
        refreshPage();
      }
    } catch (e) { noteErr(e); toast('error', '没能改架构'); refreshPage(); }
  }

  async function clearIgnored(id) {
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.clear_ignored(id);
      if (r && r.ok) {
        if (Array.isArray(r.channels)) applyChannels(r.channels);
        else refreshChannels();
        if (r.message) toast('ok', r.message);
      } else {
        toast('error', (r && r.error) || '没能恢复');
      }
    } catch (e) { noteErr(e); toast('error', '没能恢复'); }
  }

  async function discoverChannels() {
    await callApi('discover', [], { busy: '正在刷新可选线…', failText: '没能刷新可选线' });
  }

  async function clearLog() {
    const r = await callApi('clear_log', [], { failText: '没能清空日志' });
    if (r && r.ok) {
      state.logText = '';
      state.logLoaded = true;
      if (state.page === 'logs') updateLogPre();
    }
  }

  async function openExternal(kind, path) {
    const a = bridge();
    if (!a) return;
    try {
      const r = await a.open_external(kind, path || '');
      if (r && r.ok === false) toast('error', r.error || '打不开');
      else if (r && r.message) toast('info', r.message);
    } catch (e) { noteErr(e); toast('error', '打不开'); }
  }

  /* ============================================================
     报告阅读器
     ============================================================ */
  const EMBED_CSS = '<style id="dsh-embed">' +
    'html,body{background:#fff!important;margin:0!important;padding:0!important;color:#1C1B19}' +
    /* 字号与后端的应用内嵌字号保持一致（13.5px 正文 / 21px h1），这里只做兜底、不加 !important，
       后端注入的 !important 规则始终优先，避免两套字号打架 */
    'body{font-family:"Segoe UI Variable Text","Segoe UI","Microsoft YaHei UI","Microsoft YaHei",sans-serif;font-size:13.5px;line-height:1.7}' +
    'h1{font-size:21px;line-height:1.4;font-weight:600}' +
    'img{max-width:100%;height:auto}a{color:#1F5AE0}' +
    'main{box-shadow:none!important;border-radius:0!important;background:#fff!important;max-width:560px;margin:0 auto;padding:24px 28px}' +
    '::-webkit-scrollbar{width:10px}::-webkit-scrollbar-track{background:transparent}' +
    '::-webkit-scrollbar-thumb{background:#D8D3CA;border:3px solid #fff;background-clip:padding-box;border-radius:8px}' +
    '</style>';

  function reportDoc(html) {
    const head = '<base target="_blank">' + EMBED_CSS;
    const src = String(html || '');
    if (/<head[^>]*>/i.test(src)) return src.replace(/<head[^>]*>/i, function (m) { return m + head; });
    if (/<html[^>]*>/i.test(src)) return src.replace(/<html[^>]*>/i, function (m) { return m + '<head>' + head + '</head>'; });
    return head + src;
  }

  /* 「点报告」：按设置决定在界面里读，还是直接交给系统浏览器打开 */
  function openReportFile(file) {
    if (!file) return;
    if (state.config && state.config.open_report_on_click) {
      openExternal('browser', file);
      return;
    }
    openReader(file);
  }

  async function openReader(file) {
    if (!file) return;
    state.readerFile = file;
    state.lastFocus = document.activeElement;
    state.readerOpen = true;
    state.readerToken++;
    const reader = $('#reader');
    if (reader) reader.classList.remove('is-closing');
    const frame = $('#readerFrame');
    const loading = $('#readerLoading');
    const r = findReport(file);
    const niceTitle = r
      ? ((compactName(r.channel_name) || '更新报告') + (r.build ? ' · ' + r.build : ''))
      : fileStem(file);
    setText($('#readerTitle'), niceTitle);
    loading.hidden = false;
    frame.style.visibility = 'hidden';
    frame.srcdoc = '';
    reader.hidden = false;
    /* 焦点给面板本身：鼠标打开时不显示按钮上的蓝色焦点环，键盘 Tab 再进操作区 */
    const panel = reader.querySelector('.reader-panel');
    if (panel && panel.focus) panel.focus();
    const a = bridge();
    if (!a) return;
    try {
      const res = await a.report_html(file);
      if (!state.readerOpen || state.readerFile !== file) return;
      if (res && res.ok) {
        setText($('#readerTitle'), r ? niceTitle : (res.title || fileStem(file)));
        frame.srcdoc = reportDoc(res.html || '');
      } else {
        frame.srcdoc = reportDoc('<div style="padding:40px;font-family:Segoe UI,Microsoft YaHei UI,sans-serif;font-size:13px;color:#5F5B54">这份报告打不开：' +
          escapeHtml((res && res.error) || '读不出来') + '。可以试试右上角的「在浏览器打开」。</div>');
      }
    } catch (e) {
      noteErr(e);
      frame.srcdoc = reportDoc('<div style="padding:40px;font-family:Segoe UI,Microsoft YaHei UI,sans-serif;font-size:13px;color:#B3261E">报告打开失败了，可以试试右上角的「在浏览器打开」。</div>');
    }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function closeReader() {
    const reader = $('#reader');
    if (!reader || reader.hidden) return;
    state.readerOpen = false;
    const token = ++state.readerToken;
    const finish = function () {
      if (token !== state.readerToken) return;
      reader.hidden = true;
      reader.classList.remove('is-closing');
      const frame = $('#readerFrame');
      if (frame) frame.srcdoc = '';
      if (state.lastFocus && state.lastFocus.isConnected) state.lastFocus.focus();
    };
    if (motionOff()) { finish(); return; }
    reader.classList.add('is-closing');
    setTimeout(finish, 150);
  }

  /* ============================================================
     个性化：第一层清晰图片 / 第二层毛玻璃 / 第三层从图片取色
     ============================================================ */
  const PERSONAL_DEFAULTS = { blur: 15, card_alpha: 70, scrim_alpha: 0 };

  function clampNum(n, min, max) { return Math.min(max, Math.max(min, n)); }

  function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b);
    const l = (max + min) / 2;
    let h = 0, s = 0;
    if (max !== min) {
      const d = max - min;
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
      if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
      else if (max === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h /= 6;
    }
    return { h: h * 360, s: s, l: l };
  }

  function hslToHex(h, s, l) {
    h = (((h % 360) + 360) % 360) / 360;
    s = clampNum(s, 0, 1);
    l = clampNum(l, 0, 1);
    function hue2rgb(p, q, t) {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    }
    let r, g, b;
    if (s === 0) { r = g = b = l; }
    else {
      const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
      const p = 2 * l - q;
      r = hue2rgb(p, q, h + 1 / 3);
      g = hue2rgb(p, q, h);
      b = hue2rgb(p, q, h - 1 / 3);
    }
    function toHex(x) {
      const v = Math.round(clampNum(x, 0, 1) * 255).toString(16);
      return v.length === 1 ? '0' + v : v;
    }
    return '#' + toHex(r) + toHex(g) + toHex(b);
  }

  function hslToRgb(h, s, l) {
    const hex = hslToHex(h, s, l);
    return {
      r: parseInt(hex.slice(1, 3), 16),
      g: parseInt(hex.slice(3, 5), 16),
      b: parseInt(hex.slice(5, 7), 16)
    };
  }

  function hexToHsl(hex) {
    const s = String(hex || '').replace('#', '');
    if (!/^[0-9a-fA-F]{6}$/.test(s)) return null;
    const r = parseInt(s.slice(0, 2), 16);
    const g = parseInt(s.slice(2, 4), 16);
    const b = parseInt(s.slice(4, 6), 16);
    return rgbToHsl(r, g, b);
  }

  /* 取图片平均色 → 略提亮、给一点饱和 → 保证白字可读 */
  function accentFromDrawable(drawable) {
    const cv = document.createElement('canvas');
    cv.width = 48; cv.height = 48;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    let data;
    try {
      ctx.drawImage(drawable, 0, 0, 48, 48);
      data = ctx.getImageData(0, 0, 48, 48).data;
    } catch (e) {
      return '';
    }
    let r = 0, g = 0, b = 0, n = 0;
    for (let i = 0; i < data.length; i += 4) {
      r += data[i]; g += data[i + 1]; b += data[i + 2]; n++;
    }
    if (!n) return '';
    const hsl = rgbToHsl(r / n, g / n, b / n);
    let h = hsl.h, s = hsl.s, l = hsl.l;
    if (s < 0.10) {                 // 灰白图（黑白照、白墙）：退回墨蓝
      h = 222; s = 0.74; l = 0.48;
    } else {
      s = clampNum(s * 1.10 + 0.08, 0.45, 0.88);
      l = clampNum(l + 0.06, 0.46, 0.56);   // 提亮一点，同时保住白字对比度
    }
    return hslToHex(h, s, l);
  }

  function loadImage(src) {
    return new Promise(function (resolve, reject) {
      const img = new Image();
      img.onload = function () { resolve(img); };
      img.onerror = function () { reject(new Error('图片加载失败')); };
      img.src = src;
    });
  }

  /* 图片分析：
     - lum：整体亮度（决定深色/浅色主题）
     - r/g/b：全图平均色（强调色用）
     - vivid：鲜艳部分的平均色（卡片底色往这儿靠，比平均色更接近“壁纸给人的颜色”） */
  function imageStats(drawable) {
    const cv = document.createElement('canvas');
    cv.width = 32; cv.height = 32;
    const ctx = cv.getContext('2d', { willReadFrequently: true });
    let data;
    try {
      ctx.drawImage(drawable, 0, 0, 32, 32);
      data = ctx.getImageData(0, 0, 32, 32).data;
    } catch (e) {
      return null;
    }
    let r = 0, g = 0, b = 0, n = 0;
    let vr = 0, vg = 0, vb = 0, vn = 0;
    for (let i = 0; i < data.length; i += 4) {
      const pr = data[i], pg = data[i + 1], pb = data[i + 2];
      r += pr; g += pg; b += pb; n++;
      const hsl = rgbToHsl(pr, pg, pb);
      if (hsl.s >= 0.45 && hsl.l >= 0.14) { vr += pr; vg += pg; vb += pb; vn++; }
    }
    if (!n) return null;
    r /= n; g /= n; b /= n;
    const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    let vivid = null;
    if (vn) { vivid = { r: vr / vn, g: vg / vn, b: vb / vn }; }
    return { r: r, g: g, b: b, lum: lum, vivid: vivid };
  }

  function paletteOf(st) {
    if (!st) return null;
    return st.vivid || { r: st.r, g: st.g, b: st.b };
  }

  /* 在「白蒙层+深色字」和「深蒙层+浅色字」两种方案里挑对比度更高的那个；
     同时把第二层卡片的底色往壁纸的平均色靠（深图深卡片、浅图浅卡片） */
  function applyTone() {
    const p = state.personalize || {};
    const root = document.documentElement;
    const lum = Number(p.lum);
    if (!p.bg_url || !isFinite(lum)) {
      document.body.classList.remove('pg-dark');
      root.style.setProperty('--pg-scrim-rgb', '246,245,242');
      root.style.removeProperty('--card-rgb');
      root.style.removeProperty('--card-line');
      ['--accent-soft', '--accent-line'].forEach(function (k) { root.style.removeProperty(k); });
      root.style.removeProperty('--accent-text');
      return;
    }
    const a = (Number(p.scrim_alpha) || 0) / 100;
    const effWhite = lum * (1 - a) + 0.964 * a;   // 白蒙层之后的背景亮度
    const effDark = lum * (1 - a) + 0.055 * a;    // 深蒙层之后的背景亮度
    const scoreDarkText = Math.abs(effWhite - 0.10);
    const scoreLightText = Math.abs(effDark - 0.92);
    const dark = scoreLightText >= scoreDarkText;
    document.body.classList.toggle('pg-dark', dark);
    root.style.setProperty('--pg-scrim-rgb', dark ? '18,17,15' : '246,245,242');

    /* 卡片底色：跟着壁纸平均色走，但保证和文字对比够 */
    const pal = p.palette || { r: 246, g: 245, b: 242 };
    const hsl = rgbToHsl(pal.r, pal.g, pal.b);
    let h = hsl.h, s = hsl.s;
    if (!isFinite(h) || s < 0.06) { h = 222; s = 0.06; }   // 灰白图：轻微偏冷
    let rgb, line;
    if (dark) {
      // 深色卡片：比背景亮一档，靠浅色描边+内高光把边界亮出来
      const cardL = clampNum(lum + 0.06, 0.14, 0.26);
      rgb = hslToRgb(h, clampNum(s * 0.45, 0.10, 0.22), cardL);
      line = 'rgba(255,255,255,.20)';
    } else {
      rgb = hslToRgb(h, clampNum(s * 0.18, 0.02, 0.10), 0.97);
      line = 'hsl(' + Math.round(h) + ' ' + Math.round(clampNum(s * 0.3, 0.04, 0.22) * 100) + '% 86%)';
    }
    root.style.setProperty('--card-rgb', rgb.r + ',' + rgb.g + ',' + rgb.b);
    root.style.setProperty('--card-line', line);

    /* 强调色的柔和底/描边也要分深浅两套 */
    const accentHsl = hexToHsl(String(p.accent || ''));
    if (accentHsl) {
      if (dark) {
        const ar = hslToRgb(accentHsl.h, accentHsl.s, 0.5);
        root.style.setProperty('--accent-soft',
          'rgba(' + ar.r + ',' + ar.g + ',' + ar.b + ',.18)');
        root.style.setProperty('--accent-line',
          'rgba(' + ar.r + ',' + ar.g + ',' + ar.b + ',.45)');
        /* 深色卡片上的强调色文字要提亮，不然链接/标签会糊在深底上 */
        root.style.setProperty('--accent-text',
          hslToHex(accentHsl.h, clampNum(accentHsl.s, 0.40, 0.85),
            clampNum(accentHsl.l + 0.26, 0.64, 0.80)));
      } else {
        root.style.setProperty('--accent-soft',
          hslToHex(accentHsl.h, Math.max(0.30, accentHsl.s - 0.10), 0.95));
        root.style.setProperty('--accent-line',
          hslToHex(accentHsl.h, Math.max(0.28, accentHsl.s - 0.18), 0.85));
        root.style.setProperty('--accent-text', String(p.accent || ''));
      }
    } else {
      root.style.removeProperty('--accent-text');
    }
  }

  function refreshPersonalMood() {
    const url = state.personalize && state.personalize.bg_url;
    if (!url) {
      state.personalize.lum = null;
      state.personalize.palette = null;
      applyTone();
      return;
    }
    loadImage(url).then(function (img) {
      if (!state.personalize || state.personalize.bg_url !== url) return;
      const st = imageStats(img);
      state.personalize.lum = st ? st.lum : null;
      state.personalize.palette = paletteOf(st);
      applyTone();
    }).catch(function () {
      state.personalize.lum = null;
      state.personalize.palette = null;
      applyTone();
    });
  }

  function applyPersonalize() {
    const p = state.personalize || {};
    const root = document.documentElement;
    const bg = p.bg_url || '';
    document.body.classList.toggle('personalized', !!bg);
    if (bg) root.style.setProperty('--bg-image', "url('" + bg + "')");
    else root.style.removeProperty('--bg-image');

    const blur = Math.round(Number(p.blur));
    const veil = Math.round(Number(p.card_alpha));
    const scrim = Math.round(Number(p.scrim_alpha));
    root.style.setProperty('--pg-blur', (isFinite(blur) ? blur : PERSONAL_DEFAULTS.blur) + 'px');
    root.style.setProperty('--card-veil', (isFinite(veil) ? veil : PERSONAL_DEFAULTS.card_alpha) / 100);
    root.style.setProperty('--scrim-alpha', (isFinite(scrim) ? scrim : PERSONAL_DEFAULTS.scrim_alpha) / 100);

    const accent = String(p.accent || '').trim();
    const hsl = hexToHsl(accent);
    if (hsl) {
      root.style.setProperty('--accent', accent);
      root.style.setProperty('--accent-top', hslToHex(hsl.h, hsl.s, Math.min(0.64, hsl.l + 0.05)));
      root.style.setProperty('--accent-strong', hslToHex(hsl.h, hsl.s, Math.max(0.20, hsl.l - 0.08)));
    } else {
      ['--accent', '--accent-top', '--accent-strong', '--accent-soft', '--accent-line']
        .forEach(function (k) { root.style.removeProperty(k); });
    }
    applyTone();
  }

  function personalRangeRow(label, help, key, min, max, step, unit) {
    const p = state.personalize || {};
    const cfgKey = 'personalize_' + key;
    const cur = Number(p[key]);
    const val = isFinite(cur) ? cur : PERSONAL_DEFAULTS[key];
    const valEl = el('span', { class: 'range-val', text: val + unit });
    const input = el('input', {
      type: 'range', class: 'range', min: String(min), max: String(max),
      step: String(step), value: String(val), 'aria-label': label
    });
    input.addEventListener('input', function () {
      const v = Number(input.value);
      valEl.textContent = v + unit;
      state.personalize[key] = v;
      applyPersonalize();
    });
    input.addEventListener('change', function () {
      const v = Number(input.value);
      state.config[cfgKey] = v;
      queueSave(cfgKey, v);
    });
    return el('div', { class: 'range-row' },
      el('div', { class: 'range-main' },
        el('div', { class: 'row-label', text: label }),
        el('div', { class: 'row-help', text: help })
      ),
      el('div', { class: 'range-line' }, input, valEl)
    );
  }

  function renderPersonalize(host) {
    const p = state.personalize || {};
    const hasBg = !!p.bg_url;

    /* ---------- 背景图 ---------- */
    const preview = el('div', { class: 'pg-preview' + (hasBg ? '' : ' is-empty') });
    if (hasBg) {
      preview.append(el('img', { src: p.bg_url, alt: '背景图预览' }));
      preview.append(el('span', { class: 'pg-badge', text: '当前背景' }));
    } else {
      preview.append(el('span', { text: '还没有背景图' }));
    }
    const actions = el('div', { class: 'pg-actions' });
    actions.append(el('button', {
      type: 'button', class: 'btn btn-primary btn-sm',
      text: hasBg ? '更换图片' : '上传图片并裁切',
      onclick: function () { pickPersonalImage(); }
    }));
    if (hasBg) {
      actions.append(el('button', {
        type: 'button', class: 'btn btn-secondary btn-sm', text: '重新裁切',
        onclick: function () { openCropModal(state.personalize.bg_url); }
      }));
      const rm = el('button', { type: 'button', class: 'btn btn-ghost btn-sm', text: '移除背景' });
      rm.addEventListener('click', function () { confirmThen(rm, '再点一次移除', removePersonalBg); });
      actions.append(rm);
    }
    const bgCard = el('div', { class: 'card' },
      el('div', { class: 'pg-row' }, preview,
        el('div', { class: 'pg-main' },
          el('div', { class: 'row-label', text: hasBg ? '当前背景图' : '背景图' }),
          el('div', { class: 'row-help', text: '第一层显示这张图（清晰）；第二层的卡片隔着它做高斯模糊，像毛玻璃。' }),
          actions,
          el('div', { class: 'pg-note', text: '图片会复制一份到程序目录，只在本机使用；发布版不包含你的图片。图片偏深时会自动把字换成浅色，偏浅时保持深色。' })
        )
      )
    );
    host.append(sectionEl('背景图', null, bgCard));

    /* ---------- 效果参数 ---------- */
    const effectsCard = el('div', { class: 'card' },
      personalRangeRow('模糊强度', '卡片背后的模糊程度，越大越像毛玻璃', 'blur', 0, 60, 1, ' px'),
      personalRangeRow('卡片白纱', '卡片白色的浓度，太低文字会看不清', 'card_alpha', 40, 98, 1, ' %'),
      personalRangeRow('图片蒙层', '整张图上的白色蒙层；图片偏深、偏花时调高更好读', 'scrim_alpha', 0, 70, 1, ' %')
    );
    host.append(sectionEl('效果',
      el('span', { text: hasBg ? '调完立刻生效' : '上传图片后生效' }), effectsCard));

    /* ---------- 强调色 ---------- */
    const accent = String(p.accent || '');
    const swatch = el('div', { class: 'swatch', title: accent || '默认墨蓝' });
    const demo = el('div', { class: 'accent-demo' },
      el('button', { type: 'button', class: 'btn btn-primary btn-sm', text: '示例按钮' }),
      el('span', { class: 'switch-demo', 'aria-hidden': 'true' }),
      el('span', { class: 'tag tag-accent', text: '标签' }),
      el('span', { class: 'link', text: '示例链接' })
    );
    const accentMain = el('div', { class: 'accent-meta' },
      el('div', { class: 'row-label', text: hasBg ? '来自图片的平均色' : '默认强调色' }),
      el('div', {
        class: 'row-help',
        text: '取整张图的平均色，自动提亮到适合白字的深度；按钮用一个很轻的上下渐变。'
      }),
      el('div', { class: 'mono', text: accent || '#1F5AE0（默认墨蓝）' })
    );
    const accentCard = el('div', { class: 'card' },
      el('div', { class: 'accent-preview' }, swatch, accentMain),
      demo,
      hasBg ? el('div', { class: 'pg-actions' },
        el('button', {
          type: 'button', class: 'btn btn-secondary btn-sm', text: '从图片重新取色',
          onclick: function () { recomputeAccent(); }
        })
      ) : null
    );
    host.append(sectionEl('强调色',
      el('span', { text: hasBg ? '跟着图片走' : '上传图片后自动取色' }), accentCard));

    /* ---------- 恢复默认 ---------- */
    const resetBtn = el('button', {
      type: 'button', class: 'btn btn-secondary btn-sm', text: '恢复默认外观'
    });
    resetBtn.addEventListener('click', function () {
      confirmThen(resetBtn, '再点一次恢复', resetPersonalize);
    });
    const resetCard = el('div', { class: 'card' },
      el('div', { class: 'settings-row' },
        el('div', { class: 'settings-main' },
          el('div', { class: 'row-label', text: '恢复默认外观' }),
          el('div', { class: 'row-help', text: '移除背景图，模糊/白纱/蒙层都回到默认值，界面变回现在这样。' })
        ),
        el('div', { class: 'settings-ctl' }, resetBtn)
      )
    );
    host.append(sectionEl('恢复默认', null, resetCard));
  }

  /* ---------- 上传 / 裁切 ---------- */
  async function pickPersonalImage() {
    const r = await callApi('pick_personal_image', [], { failText: '没能打开选图窗口' });
    if (!r || !r.ok || r.cancelled) return;
    openCropModal(r.data_url);
  }

  function ensureCropModal() {
    let root = $('#cropModal');
    if (root) return root;
    const box = el('div', { class: 'crop-box', id: 'cropBox' },
      el('span', { class: 'crop-h', 'data-dir': 'nw' }),
      el('span', { class: 'crop-h', 'data-dir': 'ne' }),
      el('span', { class: 'crop-h', 'data-dir': 'sw' }),
      el('span', { class: 'crop-h', 'data-dir': 'se' })
    );
    const frame = el('div', { class: 'crop-frame', id: 'cropFrame' },
      el('img', { id: 'cropImg', alt: '背景图预览' }), box);
    const panel = el('div', {
      class: 'crop-panel', role: 'dialog', 'aria-modal': 'true',
      'aria-labelledby': 'cropTitle', tabindex: '-1'
    },
      el('div', { class: 'crop-bar' },
        el('div', { class: 'crop-title', id: 'cropTitle', text: '裁切背景图' }),
        el('button', {
          type: 'button', class: 'icon-btn', title: '关闭（Esc）', 'aria-label': '关闭',
          onclick: function () { closeCropModal(); }
        }, svgIcon('x'))
      ),
      el('div', { class: 'crop-stage' }, frame),
      el('div', { class: 'crop-foot' },
        el('div', { class: 'crop-hint', text: '拖动方框选择要显示的区域；背景会自动铺满整个窗口。' }),
        el('div', { class: 'crop-actions' },
          el('button', {
            type: 'button', class: 'btn btn-secondary btn-sm', text: '全图',
            onclick: function () { resetCropBox(); }
          }),
          el('button', {
            type: 'button', class: 'btn btn-ghost btn-sm', text: '取消',
            onclick: function () { closeCropModal(); }
          }),
          el('button', {
            type: 'button', class: 'btn btn-primary btn-sm', text: '使用这张',
            onclick: function () { confirmCrop(); }
          })
        )
      )
    );
    root = el('div', { class: 'crop', id: 'cropModal', hidden: true }, panel);
    root.addEventListener('click', function (e) { if (e.target === root) closeCropModal(); });
    box.addEventListener('pointerdown', cropPointerDown);
    document.body.append(root);
    return root;
  }

  function placeCropBox() {
    const c = state.crop;
    const box = $('#cropBox');
    if (!c || !box) return;
    box.style.left = c.box.x + 'px';
    box.style.top = c.box.y + 'px';
    box.style.width = c.box.w + 'px';
    box.style.height = c.box.h + 'px';
  }

  function resetCropBox() {
    const c = state.crop;
    if (!c) return;
    c.box = { x: 0, y: 0, w: c.dispW, h: c.dispH };
    placeCropBox();
  }

  function cropPointerDown(e) {
    if (!state.crop) return;
    e.preventDefault();
    const dir = (e.target && e.target.dataset && e.target.dataset.dir) || 'move';
    const startX = e.clientX, startY = e.clientY;
    const b0 = Object.assign({}, state.crop.box);
    const W = state.crop.dispW, H = state.crop.dispH;
    const MIN = 32;
    function onMove(ev) {
      const dx = ev.clientX - startX, dy = ev.clientY - startY;
      let x = b0.x, y = b0.y, w = b0.w, h = b0.h;
      if (dir === 'move') {
        x = clampNum(b0.x + dx, 0, W - b0.w);
        y = clampNum(b0.y + dy, 0, H - b0.h);
      } else {
        if (dir.indexOf('w') >= 0) {
          const nx = clampNum(b0.x + dx, 0, b0.x + b0.w - MIN);
          w = b0.x + b0.w - nx; x = nx;
        }
        if (dir.indexOf('e') >= 0) w = clampNum(b0.w + dx, MIN, W - b0.x);
        if (dir.indexOf('n') >= 0) {
          const ny = clampNum(b0.y + dy, 0, b0.y + b0.h - MIN);
          h = b0.y + b0.h - ny; y = ny;
        }
        if (dir.indexOf('s') >= 0) h = clampNum(b0.h + dy, MIN, H - b0.y);
      }
      state.crop.box = { x: x, y: y, w: w, h: h };
      placeCropBox();
    }
    function onUp() {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
    }
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  }

  function openCropModal(dataUrl) {
    if (!dataUrl) return;
    const root = ensureCropModal();
    root.hidden = false;
    state.cropOpen = true;
    state.lastFocus = document.activeElement;
    const panel = root.querySelector('.crop-panel');
    if (panel && panel.focus) panel.focus();
    const img = $('#cropImg');
    const frame = $('#cropFrame');
    img.onload = function () {
      const nw = img.naturalWidth || 1, nh = img.naturalHeight || 1;
      const maxW = Math.min(window.innerWidth * 0.82, 1000);
      const maxH = Math.min(window.innerHeight * 0.62, 620);
      const k = Math.min(maxW / nw, maxH / nh, 1);
      const dw = Math.max(60, Math.round(nw * k));
      const dh = Math.max(60, Math.round(nh * k));
      frame.style.width = dw + 'px';
      frame.style.height = dh + 'px';
      state.crop = {
        img: img, nw: nw, nh: nh, dispW: dw, dispH: dh,
        scale: dw / nw, box: { x: 0, y: 0, w: dw, h: dh }
      };
      placeCropBox();
    };
    img.onerror = function () {
      closeCropModal();
      toast('error', '这张图片读不出来，换一张试试');
    };
    img.src = dataUrl;
  }

  function closeCropModal() {
    const root = $('#cropModal');
    if (!root || root.hidden) return;
    root.hidden = true;
    state.cropOpen = false;
    state.crop = null;
    if (state.lastFocus && state.lastFocus.isConnected) {
      try { state.lastFocus.focus(); } catch (e) { /* 焦点回不去就算了 */ }
    }
  }

  async function confirmCrop() {
    const c = state.crop;
    if (!c || !c.img) return;
    const sx = c.box.x / c.scale, sy = c.box.y / c.scale;
    const sw = Math.max(1, c.box.w / c.scale);
    const sh = Math.max(1, c.box.h / c.scale);
    const MAXDIM = 1920;
    const k = Math.min(1, MAXDIM / Math.max(sw, sh));
    const cw = Math.max(1, Math.round(sw * k));
    const ch = Math.max(1, Math.round(sh * k));
    const cv = document.createElement('canvas');
    cv.width = cw; cv.height = ch;
    const ctx = cv.getContext('2d');
    let dataUrl = '';
    try {
      ctx.drawImage(c.img, sx, sy, sw, sh, 0, 0, cw, ch);
      dataUrl = cv.toDataURL('image/jpeg', 0.9);
    } catch (e) {
      toast('error', '这张图片处理不了，换一张试试');
      return;
    }
    if (!dataUrl) { toast('error', '裁切失败了，再试一次'); return; }
    const accent = accentFromDrawable(cv);
    const stats = imageStats(cv);
    closeCropModal();
    const r = await callApi('save_personal_image', [dataUrl, accent],
      { failText: '没能保存背景图' });
    if (!r || !r.ok) return;
    if (r.config) state.config = r.config;
    state.personalize = Object.assign({}, state.personalize,
      { bg_url: dataUrl, accent: accent,
        lum: stats ? stats.lum : null,
        palette: paletteOf(stats) });
    applyPersonalize();
    refreshPage();
  }

  async function removePersonalBg() {
    const r = await callApi('clear_personal_image', [], { failText: '没能移除背景' });
    if (!r || !r.ok) return;
    if (r.config) state.config = r.config;
    state.personalize = Object.assign({}, state.personalize,
      { bg_url: '', accent: '', lum: null, palette: null });
    applyPersonalize();
    refreshPage();
  }

  async function recomputeAccent() {
    const url = state.personalize && state.personalize.bg_url;
    if (!url) return;
    let img;
    try { img = await loadImage(url); } catch (e) { toast('error', '图片读不出来'); return; }
    const accent = accentFromDrawable(img);
    if (!accent) { toast('error', '取色失败，换一张试试'); return; }
    const stats = imageStats(img);
    state.personalize = Object.assign({}, state.personalize,
      { accent: accent,
        lum: stats ? stats.lum : null,
        palette: paletteOf(stats) });
    state.config.personalize_accent = accent;
    applyPersonalize();
    queueSave('personalize_accent', accent);
    refreshPage();
    toast('ok', '已从图片重新取色');
  }

  async function resetPersonalize() {
    const a = bridge();
    if (!a) return;
    try {
      await a.save_config({
        personalize_blur: PERSONAL_DEFAULTS.blur,
        personalize_card_alpha: PERSONAL_DEFAULTS.card_alpha,
        personalize_scrim_alpha: PERSONAL_DEFAULTS.scrim_alpha
      });
    } catch (e) { noteErr(e); }
    const r = await callApi('clear_personal_image', [], { failText: '没能恢复默认' });
    if (!r || !r.ok) return;
    if (r.config) state.config = r.config;
    state.personalize = {
      bg_url: '', accent: '', lum: null, palette: null,
      blur: PERSONAL_DEFAULTS.blur,
      card_alpha: PERSONAL_DEFAULTS.card_alpha,
      scrim_alpha: PERSONAL_DEFAULTS.scrim_alpha
    };
    applyPersonalize();
    refreshPage();
  }

  /* ============================================================
     渲染入口表
     ============================================================ */
  const RENDERERS = {
    overview: renderOverview,
    channels: renderChannels,
    notify: renderNotify,
    settings: renderSettings,
    personalize: renderPersonalize,
    startup: renderStartup,
    reports: renderReports,
    logs: renderLogs
  };

  /* ============================================================
     键盘 / 窗口 chrome
     ============================================================ */
  function onKeydown(e) {
    if (e.key === 'Escape') {
      if (state.cropOpen) { e.preventDefault(); closeCropModal(); return; }
      if (state.pickerOpen) { e.preventDefault(); closePicker(); return; }
      if (state.readerOpen) { e.preventDefault(); closeReader(); return; }
      dismissLastToast();
    }
  }

  /* ---------- 自绘标题栏 / 窗口控制 ---------- */
  async function winCall(name) {
    const a = bridge();
    if (!a || typeof a[name] !== 'function') return null;
    try {
      return await a[name]();
    } catch (e) {
      noteErr(e);
      return null;
    }
  }

  function setMaximizedUI(max) {
    const on = !!max;
    state.maximized = on;
    document.body.classList.toggle('is-maximized', on);
    const btn = $('#winMax');
    const use = btn ? btn.querySelector('use') : null;
    if (use) use.setAttribute('href', on ? '#i-win-restore' : '#i-win-max');
    if (btn) {
      btn.title = on ? '还原' : '最大化';
      btn.setAttribute('aria-label', on ? '还原' : '最大化');
    }
  }

  async function windowMinimize() {
    await winCall('window_minimize');
  }

  async function windowToggleMax() {
    const r = await winCall('window_toggle_max');
    if (r && typeof r.maximized === 'boolean') setMaximizedUI(r.maximized);
  }

  async function windowClose() {
    const r = await winCall('window_close');
    if (!r) await closeWindow();
  }

  function wireTitlebar() {
    const drag = $('#titlebarDrag');
    if (drag) {
      drag.addEventListener('dblclick', function (e) {
        e.preventDefault();
        windowToggleMax();
      });
    }
    const min = $('#winMin');
    const max = $('#winMax');
    const close = $('#winClose');
    if (min) min.addEventListener('click', windowMinimize);
    if (max) max.addEventListener('click', windowToggleMax);
    if (close) close.addEventListener('click', windowClose);

    $$('.wbtn').forEach(function (btn) {
      btn.addEventListener('mousedown', function (e) { e.stopPropagation(); });
    });

    $$('.rz').forEach(function (rz) {
      rz.addEventListener('mousedown', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (state.maximized) return;
        const a = bridge();
        if (a && typeof a.begin_resize === 'function') {
          try { a.begin_resize(rz.dataset.edge); } catch (err) { /* 预览里没有后端，静默 */ }
        }
      });
    });

    const bar = $('#titlebar');
    const syncFocus = function () {
      if (!bar) return;
      bar.classList.toggle('is-blurred', !document.hasFocus());
    };
    window.addEventListener('focus', syncFocus);
    window.addEventListener('blur', function () {
      if (bar) bar.classList.add('is-blurred');
    });
    syncFocus();
  }

  function wireChrome() {
    wireTitlebar();
    $$('.nav-item').forEach(function (btn) {
      btn.addEventListener('click', function () { go(btn.dataset.page); });
    });
    const closeBtn = $('#btnCloseWindow');
    if (closeBtn) closeBtn.addEventListener('click', function () { closeWindow(); });
    const quitBtn = $('#btnQuitAll');
    if (quitBtn) {
      quitBtn.addEventListener('click', function () {
        confirmThen(quitBtn, '再点一次退出', function () { quitAll(); });
      });
    }
    const selfcheckBtn = $('#btnSelfcheck');
    if (selfcheckBtn) selfcheckBtn.addEventListener('click', function () { runSelfcheck(); });

    const readerClose = $('#readerClose');
    if (readerClose) readerClose.addEventListener('click', closeReader);
    const reader = $('#reader');
    if (reader) reader.addEventListener('click', function (e) { if (e.target === reader) closeReader(); });
    const browserBtn = $('#readerBrowser');
    if (browserBtn) browserBtn.addEventListener('click', function () {
      if (state.readerFile) openExternal('browser', state.readerFile);
    });
    const folderBtn = $('#readerFolder');
    if (folderBtn) folderBtn.addEventListener('click', function () { openExternal('report_folder'); });
    const frame = $('#readerFrame');
    if (frame) frame.addEventListener('load', function () {
      const loading = $('#readerLoading');
      if (loading) loading.hidden = true;
      frame.style.visibility = 'visible';
    });

    document.addEventListener('keydown', onKeydown);

    /* 窗口宽度跨过断点时，报告页在「双栏预览 / 单栏点开阅读」之间切换 */
    let reportsWide = !reportsNarrow();
    window.addEventListener('resize', function () {
      const wide = !reportsNarrow();
      if (wide === reportsWide) return;
      reportsWide = wide;
      if (state.page === 'reports') {
        state.reportViewHost = null;
        renderPage('reports');
      }
    });
  }

  async function closeWindow() {
    const a = bridge();
    if (!a) return;
    try { await a.close_window(); } catch (e) { noteErr(e); }
  }

  async function quitAll() {
    const a = bridge();
    if (!a) return;
    try { await a.quit_all(); } catch (e) { noteErr(e); }
  }

  /* ============================================================
     启动
     ============================================================ */
  function init() {
    $$('.page').forEach(function (p) { PAGE_HOSTS[p.dataset.view] = p; });
    wireChrome();
    if (window.__mockApi) { start(); return; }
    if (window.pywebview && window.pywebview.api) { start(); return; }
    window.addEventListener('pywebviewready', function () { start(); }, { once: true });
    setTimeout(function () {
      if (!state.booted && !state.booting && bridge()) start();
    }, 6000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
