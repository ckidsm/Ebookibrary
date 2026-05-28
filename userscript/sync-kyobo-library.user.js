// ==UserScript==
// @name         Kyobo e-Library → NAS Sync
// @namespace    https://192.168.10.205/
// @version      0.3.0
// @description  교보 e-Library 페이지에서 내 도서 목록을 NAS Kyobo Bridge(9000)로 동기화
// @author       YUNDEOKSOO
// @match        https://elibrary.kyobobook.co.kr/*
// @match        https://ebook.kyobobook.co.kr/dig/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      192.168.10.205
// @connect      redcodeme.synology.me
// @run-at       document-idle
// @updateURL    http://192.168.10.205:8080/userscript/sync-kyobo-library.user.js
// @downloadURL  http://192.168.10.205:8080/userscript/sync-kyobo-library.user.js
// ==/UserScript==

(() => {
    'use strict';

    const DEFAULTS = { backend: 'http://192.168.10.205:9000' };
    const backendUrl = () => GM_getValue('backendUrl', DEFAULTS.backend);

    // ── UI: 우측 하단 floating 패널 ────────────────────────
    function injectPanel() {
        if (document.getElementById('nvk-panel')) return;
        const panel = document.createElement('div');
        panel.id = 'nvk-panel';
        panel.style.cssText = [
            'position:fixed', 'bottom:20px', 'right:20px', 'z-index:999999',
            'background:#0a0c10', 'color:#e6ecf2',
            'border:1px solid #2f3a4d', 'border-radius:10px',
            'padding:14px 16px',
            'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif',
            'font-size:13px',
            'box-shadow:0 12px 32px rgba(0,0,0,0.5)',
            'min-width:300px', 'max-width:380px',
        ].join(';');
        panel.innerHTML = `
            <div style="font-weight:700;color:#22d3ee;margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;">
                <span>📚 NAS Sync <span style="opacity:0.6;font-weight:400;font-family:monospace;font-size:11px;">v0.3.0</span></span>
                <span id="nvk-close" style="cursor:pointer;opacity:0.5;font-size:16px;">×</span>
            </div>
            <div id="nvk-status" style="color:#8b96a8;font-size:12px;margin-bottom:10px;line-height:1.5;">
                백엔드: <code id="nvk-backend" style="color:#22d3ee;">${backendUrl()}</code>
            </div>
            <div style="display:flex;gap:6px;margin-bottom:8px;">
                <button id="nvk-preview" style="flex:1;padding:7px 10px;background:#1c2230;border:1px solid #2f3a4d;border-radius:6px;color:#e6ecf2;cursor:pointer;font-size:12px;">미리보기 (F12)</button>
                <button id="nvk-sync" style="flex:1;padding:7px 10px;background:rgba(34,211,238,0.18);border:1px solid #22d3ee;border-radius:6px;color:#22d3ee;cursor:pointer;font-size:12px;font-weight:600;">동기화</button>
            </div>
            <details style="font-size:11px;color:#8b96a8;">
                <summary style="cursor:pointer;">설정·진단</summary>
                <div style="margin-top:6px;">
                    <input id="nvk-url" type="text" value="${backendUrl()}"
                        style="width:100%;padding:5px;background:#161b24;color:#e6ecf2;border:1px solid #2f3a4d;border-radius:4px;font-family:monospace;font-size:11px;box-sizing:border-box;" />
                    <div style="display:flex;gap:4px;margin-top:5px;">
                        <button id="nvk-save"  style="flex:1;padding:4px 8px;background:#1c2230;border:1px solid #2f3a4d;border-radius:4px;color:#e6ecf2;cursor:pointer;font-size:11px;">URL 저장</button>
                        <button id="nvk-diag"  style="flex:1;padding:4px 8px;background:#1c2230;border:1px solid #2f3a4d;border-radius:4px;color:#e6ecf2;cursor:pointer;font-size:11px;">진단 dump</button>
                    </div>
                </div>
            </details>
        `;
        document.body.appendChild(panel);

        document.getElementById('nvk-close').onclick = () => panel.remove();
        document.getElementById('nvk-preview').onclick = () => doExtract(true);
        document.getElementById('nvk-sync').onclick = () => doExtract(false);
        document.getElementById('nvk-save').onclick = () => {
            const v = document.getElementById('nvk-url').value.trim();
            if (v) {
                GM_setValue('backendUrl', v);
                document.getElementById('nvk-backend').textContent = v;
                setStatus('저장됨: ' + v, '#10b981');
            }
        };
        document.getElementById('nvk-diag').onclick = () => {
            console.log('[NVK] === FULL DIAGNOSTIC DUMP ===');
            console.log('[NVK] diagnose():', diagnose());
            setStatus('진단 dump 콘솔 출력 — F12 → Console 확인', '#8b96a8');
        };
    }

    function setStatus(html, color) {
        const el = document.getElementById('nvk-status');
        if (!el) return;
        el.innerHTML = html;
        if (color) el.style.color = color;
    }

    // ── 풍부한 진단 dump ──────────────────────────────────
    function diagnose() {
        const url = location.href;
        const title = document.title;

        // 모든 element 의 class 빈도 (반복 5+ 만)
        const classCounts = new Map();
        document.querySelectorAll('[class]').forEach(el => {
            const c = (el.className && el.className.toString()) || '';
            if (!c) return;
            classCounts.set(c, (classCounts.get(c) || 0) + 1);
        });
        const repeated = Array.from(classCounts.entries())
            .filter(([_, n]) => n >= 5)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 20)
            .map(([cls, n]) => `${String(n).padStart(3)}× ${cls.slice(0, 100)}`);

        // 도서 관련 키워드 element 후보
        const bookLike = Array.from(
            document.querySelectorAll('[class*="book"], [class*="Book"], [class*="library"], [class*="prod"], [class*="item"]')
        ).slice(0, 30).map(el => ({
            tag: el.tagName.toLowerCase(),
            cls: (el.className && el.className.toString()) || '',
            dataset: Object.assign({}, el.dataset),
            text: (el.textContent || '').trim().slice(0, 80),
        }));

        // ul/ol > li 패턴 — 자식 li 5개 이상
        const lists = Array.from(document.querySelectorAll('ul, ol'))
            .filter(ul => ul.children.length >= 5)
            .slice(0, 10)
            .map(ul => ({
                ulClass: (ul.className && ul.className.toString()) || '',
                ulId: ul.id || '',
                liCount: ul.children.length,
                firstLiClass: ul.children[0]?.className?.toString() || '',
                sampleText: ul.children[0]?.textContent?.trim().slice(0, 100),
            }));

        return { url, title, repeated, bookLike, lists };
    }

    // ── 핵심: 도서 카드 추출 ──────────────────────────────
    // v0.3.0 — 셀렉터 후보 확장
    const EXTRACT_RULES = {
        cardSelectors: [
            // v0.2 — 일반 패턴
            '.book-card', '.book-item', '.b_book', 'li.book',
            '[class*="book-card"]', '[class*="book-item"]',
            '[class*="BookCard"]', '[class*="BookItem"]',
            '.book_list li', '.book-list li',
            '[data-product-id]', '[data-book-id]', '[data-barcode]',
            // v0.3 — 교보 신규 영역 추정
            '.list_book li', '.bookBox', '.gd_book', '.product_item',
            '.book_section_box', '[class*="bookItem"]', '[class*="bookList"]',
            '.list_type01 li', '.list_type02 li',
            'ul[class*="book"] > li', 'ul[class*="list"] > li',
            'div[class*="book"] > div', 'div[class*="library"] > div',
            '[class*="elibrary"] li', '[class*="elibrary"] [class*="item"]',
            // 데이터 속성 패턴 강화
            '[data-sno]', '[data-isbn]', '[data-prdno]', '[data-cartid]',
        ],
        title: (card) => {
            const cand = card.querySelector(
                '.title, .book-title, .book_title, [class*="title"], [class*="Title"], strong, h3, h4'
            );
            return cand?.textContent?.trim();
        },
        author: (card) => {
            const cand = card.querySelector(
                '.author, .book-author, [class*="author"], [class*="Author"], [class*="writer"]'
            );
            return cand?.textContent?.trim();
        },
        publisher: (card) => {
            const cand = card.querySelector(
                '.publisher, [class*="publisher"], [class*="Publisher"], [class*="company"]'
            );
            return cand?.textContent?.trim();
        },
        cover: (card) => card.querySelector('img')?.src,
        link: (card) => card.querySelector('a')?.href,
        kyoboIdFromLink: (link) => {
            if (!link) return null;
            const m = link.match(/[?&](barcode|isbn|productId|bookId|prdNo|sktSno|sno|cmdt_code)=([^&]+)/i)
                   || link.match(/\/(b\d{6,}|p\d{6,}|\d{10,})\b/);
            return m ? (m[2] || m[1]) : null;
        },
        kyoboIdFromDataset: (card) =>
            card.dataset.productId || card.dataset.bookId || card.dataset.barcode
            || card.dataset.sno || card.dataset.prdno || card.dataset.isbn || null,
    };

    function extractBooks() {
        let bestSelector = null;
        let bestCount = 0;
        const triedResults = [];
        for (const s of EXTRACT_RULES.cardSelectors) {
            const n = document.querySelectorAll(s).length;
            if (n > 0) triedResults.push(`${n}× ${s}`);
            if (n > bestCount) { bestCount = n; bestSelector = s; }
        }

        if (!bestSelector) {
            return { books: [], selector: null, tried: triedResults };
        }

        const cards = document.querySelectorAll(bestSelector);
        const books = [];
        cards.forEach(card => {
            const title = EXTRACT_RULES.title(card);
            if (!title) return;
            const link = EXTRACT_RULES.link(card);
            const kyobo_id = EXTRACT_RULES.kyoboIdFromDataset(card)
                          || EXTRACT_RULES.kyoboIdFromLink(link);
            books.push({
                kyobo_id,
                title,
                author: EXTRACT_RULES.author(card),
                publisher: EXTRACT_RULES.publisher(card),
                cover_url: EXTRACT_RULES.cover(card),
                link,
            });
        });
        return { books, selector: bestSelector, tried: triedResults };
    }

    function doExtract(previewOnly) {
        const { books, selector, tried } = extractBooks();

        if (books.length === 0) {
            const diag = diagnose();
            setStatus(
                '⚠ 카드 추출 실패. <strong>F12 → Console</strong> 의 <code>[NVK]</code> 진단 dump 확인 후 알려주세요.<br>' +
                `<small style="color:#8b96a8;">매칭된 후보 selector: ${tried.length}개</small>`,
                '#f59e0b'
            );
            console.log('[NVK] === 추출 실패 진단 ===');
            console.log('[NVK] tried selectors (>0):', tried);
            console.log('[NVK] diagnose():', diag);
            console.log('[NVK] 위 정보를 캡처/복사해서 개발자에게 전달하면 셀렉터 보정 가능');
            return;
        }

        console.log(`[NVK] 추출 ${books.length}건 (selector="${selector}", tried=${tried.length}):`, books);
        if (previewOnly) {
            setStatus(
                `미리보기 <b style="color:#22d3ee;">${books.length}건</b> · selector=<code>${selector}</code><br>` +
                `<small style="color:#8b96a8;">F12 → Console 에서 추출 결과 확인</small>`,
                '#8b96a8'
            );
            return;
        }

        setStatus(`전송 중 · <b>${books.length}건</b>...`, '#8b96a8');
        const url = backendUrl() + '/api/library/sync';
        GM_xmlhttpRequest({
            method: 'POST',
            url,
            headers: { 'Content-Type': 'application/json' },
            data: JSON.stringify({ source: 'kyobo-elibrary', books }),
            onload(resp) {
                let json = null;
                try { json = JSON.parse(resp.responseText); } catch (_) {}
                if (resp.status === 200 && json) {
                    setStatus(
                        `✓ 동기화 · 신규 <b>${json.inserted}</b> · 갱신 <b>${json.updated}</b> · 전체 <b>${json.total}</b>건`,
                        '#10b981'
                    );
                    console.log('[NVK] sync OK:', json);
                } else {
                    const msg = (json && json.detail) || resp.responseText.slice(0, 200);
                    setStatus(`✗ ${resp.status}: ${msg}`, '#ef4444');
                }
            },
            onerror(err) {
                setStatus('✗ 네트워크 오류 — 백엔드에 도달 못함', '#ef4444');
                console.error('[NVK] sync error:', err);
            },
            ontimeout() {
                setStatus('✗ 타임아웃 — 백엔드 응답 없음', '#ef4444');
            },
        });
    }

    // ── init ──────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectPanel);
    } else {
        injectPanel();
    }
})();
