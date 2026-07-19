/* 교보 캡처 앱 — 웹(redcodeme.../kyobo/)에 주입되는 후킹 스크립트.
 * 앱(pywebview) 안에서만 동작(window.pywebview 존재). "로컬 매크로(auto)" 선택 시
 * 백엔드 /api/jobs POST 대신 window.pywebview.api.start_local(...) 로 로컬 파이프라인 실행.
 * 진행 오버레이 패널 주입 + window.__kyoboApp.* 콜백(파이썬이 evaluate_js 로 호출).  */
(function () {
  if (!window.pywebview || window.__kyoboAppHooked) return;
  window.__kyoboAppHooked = true;

  // ── 1) showAnalyzeCmd 오버라이드: mode=auto(macOS 로컬 매크로) → 앱으로 위임 ──
  var _origAnalyze = window.showAnalyzeCmd;
  window.showAnalyzeCmd = async function (book, slug, mode) {
    if (mode === 'auto' || mode === 'capture-only') {
      var spEl = document.getElementById('cap-start-page');
      var sp = parseInt((spEl && spEl.value) || '1', 10);
      var payload = {
        slug: slug,
        title: (book && book.title) || slug,
        mode: mode,
        salecmdtid: (book && book.salecmdtid) || null,
        pages: sp > 1 ? String(sp) : null,
      };
      __kyoboApp.begin(payload);
      try { await window.pywebview.api.start_local(payload); } catch (e) { __kyoboApp.set({ line: '앱 호출 실패: ' + e }); }
      // 책 모달 닫기(오버레이로 진행 표시)
      var x = document.getElementById('bmodal-bd'); if (x) x.classList.remove('open');
      var m = document.getElementById('bmodal'); if (m) m.classList.remove('open');
      return;
    }
    if (_origAnalyze) return _origAnalyze.apply(this, arguments); // 그 외 모드는 원래 흐름
  };

  // ── 2) 진행 오버레이 패널 주입 ──
  var el = document.createElement('div');
  el.id = '__kyobo-overlay';
  el.style.cssText = 'position:fixed;right:16px;bottom:16px;width:380px;max-height:74vh;overflow:auto;z-index:2147483000;background:#0f1722;color:#e2e8f0;border:1px solid #2c3e50;border-radius:14px;box-shadow:0 10px 48px rgba(0,0,0,.55);padding:16px 18px;font-size:13px;line-height:1.5;display:none;font-family:-apple-system,system-ui,sans-serif;';
  el.innerHTML =
    '<div style="display:flex;justify-content:space-between;align-items:center;">' +
    '  <b id="__k-title" style="font-size:14px;">로컬 분석</b>' +
    '  <button id="__k-x" style="background:none;border:none;color:#8090a0;font-size:17px;cursor:pointer;line-height:1;">✕</button></div>' +
    '<div id="__k-step" style="margin-top:10px;color:#7ee787;font-weight:600;"></div>' +
    '<div style="background:#1a2332;border-radius:6px;height:9px;margin-top:9px;overflow:hidden;"><div id="__k-bar" style="height:100%;width:0;background:linear-gradient(90deg,#1abc9c,#3498db);transition:width .3s;"></div></div>' +
    '<div id="__k-line" style="margin-top:9px;color:#95a5a6;font-size:12px;word-break:break-all;max-height:9em;overflow:auto;"></div>' +
    '<div id="__k-prompt" style="display:none;margin-top:12px;">' +
    '  <button id="__k-ok" style="background:#1abc9c;border:none;color:#04120e;font-weight:700;padding:8px 14px;border-radius:7px;cursor:pointer;">확인 · 캡처 시작</button>' +
    '  <button id="__k-no" style="margin-left:8px;background:#34495e;border:none;color:#dfe6ee;padding:8px 14px;border-radius:7px;cursor:pointer;">취소</button></div>' +
    '<button id="__k-cancel" style="margin-top:12px;background:#c0392b;border:none;color:#fff;padding:7px 13px;border-radius:7px;cursor:pointer;">중단</button>';
  document.body.appendChild(el);

  var $ = function (id) { return document.getElementById(id); };
  $('__k-x').onclick = function () { el.style.display = 'none'; };
  $('__k-cancel').onclick = function () { try { window.pywebview.api.cancel(); } catch (e) {} };
  $('__k-ok').onclick = function () { $('__k-prompt').style.display = 'none'; try { window.pywebview.api.book_confirm(true); } catch (e) {} };
  $('__k-no').onclick = function () { $('__k-prompt').style.display = 'none'; try { window.pywebview.api.book_confirm(false); } catch (e) {} };

  function setUI(o) {
    if (o.title != null) $('__k-title').textContent = o.title;
    if (o.step != null) $('__k-step').textContent = o.step;
    if (o.pct != null) $('__k-bar').style.width = Math.max(0, Math.min(100, o.pct)) + '%';
    if (o.line != null) $('__k-line').textContent = o.line;
  }

  // ── 3) 파이썬이 호출하는 콜백 ──
  window.__kyoboApp = {
    show: function () { el.style.display = 'block'; },
    set: setUI,
    begin: function (p) { this.show(); setUI({ title: '분석: ' + (p.title || p.slug), step: '준비 중...', pct: 0, line: '교보 앱 확인 중...' }); $('__k-prompt').style.display = 'none'; },
    start: function (d) { this.show(); setUI({ title: '분석: ' + (d.title || d.slug), step: '준비 중...', pct: 0, line: '' }); },
    progress: function (d) {
      var pct = d.stage_total ? Math.round(((d.stage - 1) + (d.tot ? d.cur / d.tot : 0)) / d.stage_total * 100) : 0;
      setUI({ step: '[' + d.stage + '/' + d.stage_total + '] ' + d.step, pct: pct, line: d.line || '' });
    },
    prompt: function (d) { // 캡처 프리플라이트 폴백 — 확인/취소 버튼 노출(블로킹 confirm 안 씀)
      this.show();
      setUI({ step: '📖 교보 앱에서 책을 열어주세요', line: '"' + (d.title || '') + '" 을 교보 eBook 앱에서 열고 첫 페이지로 이동한 뒤 [확인 · 캡처 시작]' });
      $('__k-prompt').style.display = 'block';
    },
    done: function (d) {
      $('__k-prompt').style.display = 'none';
      if (d.status === 'done') setUI({ step: '✅ 완료 — 라이브 발행됨', pct: 100, line: '' });
      else if (d.status === 'cancelled') setUI({ step: '⏹ 중단됨', line: d.error || '' });
      else setUI({ step: '❌ 실패', line: (d.failed_step ? '[' + d.failed_step + '] ' : '') + (d.error || '') });
    },
  };
  console.log('[kyobo-app] hook 주입 완료');
})();
