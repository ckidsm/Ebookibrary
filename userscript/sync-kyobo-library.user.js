// ==UserScript==
// @name         Kyobo e-Library → NAS Sync
// @namespace    https://192.168.10.205/
// @version      0.2.0
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
            'min-width:300px',
        ].join(';');
        panel.innerHTML = `
            <div style="font-weight:700;color:#22d3ee;margin-bottom:8px;display:flex;align-items:center;justify-content:space-between;">
                <span>📚 NAS Sync <span style="opacity:0.6;font-weight:400;font-family:monospace;font-size:11px;">v0.2.0</span></span>
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
                <summary style="cursor:pointer;">설정</summary>
                <div style="margin-top:6px;">
                    <input id="nvk-url" type="text" value="${backendUrl()}"
                        style="width:100%;padding:5px;background:#161b24;color:#e6ecf2;border:1px solid #2f3a4d;border-radius:4px;font-family:monospace;font-size:11px;box-sizing:border-box;" />
                    <button id="nvk-save" style="margin-top:5px;padding:4px 8px;background:#1c2230;border:1px solid #2f3a4d;border-radius:4px;color:#e6ecf2;cursor:pointer;font-size:11px;">저장</button>
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
    }

    function setStatus(html, color) {
        const el = document.getElementById('nvk-status');
        if (!el) return;
        el.innerHTML = html;
        if (color) el.style.color = color;
    }

    // ── 핵심: 도서 카드 추출 ──────────────────────────────
    // 교보 e-Library 도서함 페이지의 카드 구조에 맞춰 셀렉터를 시도.
    // 실제 페이지 마크업이 다르면 콘솔에서 후보 element를 확인하고
    // EXTRACT_RULES 의 각 selector·attr 함수를 보정한다.
    const EXTRACT_RULES = {
        // 후보 컨테이너 selector — 여러 패턴 시도 후 가장 많이 잡히는 것 선택
        cardSelectors: [
            '.book-card', '.book-item', '.b_book', 'li.book',
            '[class*="book-card"]', '[class*="book-item"]',
            '[class*="BookCard"]', '[class*="BookItem"]',
            '.book_list li', '.book-list li',
            '[data-product-id]', '[data-book-id]', '[data-barcode]',
        ],
        title: (card) => card.querySelector('.title,.book-title,.book_title,[class*="title"]')?.textContent?.trim(),
        author: (card) => card.querySelector('.author,.book-author,[class*="author"]')?.textContent?.trim(),
        cover: (card) => card.querySelector('img')?.src,
        link: (card) => card.querySelector('a')?.href,
        kyoboIdFromLink: (link) => {
            if (!link) return null;
            const m = link.match(/[?&](barcode|isbn|productId|bookId|prdNo|sktSno|sno)=([^&]+)/i)
                   || link.match(/\/(b\d{6,}|p\d{6,}|\d{10,})\b/);
            return m ? (m[2] || m[1]) : null;
        },
        kyoboIdFromDataset: (card) => card.dataset.productId
            || card.dataset.bookId || card.dataset.barcode || card.dataset.sno || null,
    };

    function extractBooks() {
        // 가장 잘 매칭되는 컨테이너 셀렉터 자동 선택
        let bestSelector = null;
        let bestCount = 0;
        for (const s of EXTRACT_RULES.cardSelectors) {
            const n = document.querySelectorAll(s).length;
            if (n > bestCount) { bestCount = n; bestSelector = s; }
        }
        if (!bestSelector) return { books: [], selector: null };

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
                cover_url: EXTRACT_RULES.cover(card),
                link,
            });
        });
        return { books, selector: bestSelector };
    }

    function doExtract(previewOnly) {
        const { books, selector } = extractBooks();
        if (books.length === 0) {
            setStatus(
                '⚠ 카드 추출 실패. 페이지 로드 완료 후 다시 시도하거나 셀렉터 조정 필요.<br>' +
                '<small style="color:#8b96a8;">F12 → Console 에서 <code>document.querySelectorAll(\'[class*="book"]\')</code> 결과 확인</small>',
                '#f59e0b'
            );
            console.log('[NVK] 추출 0건. 진단용:', {
                bookLikeAll: document.querySelectorAll('[class*="book"]'),
                Book_Like_All: document.querySelectorAll('[class*="Book"]'),
                liCount: document.querySelectorAll('li').length,
            });
            return;
        }

        console.log(`[NVK] 추출 ${books.length}건 (selector="${selector}"):`, books);
        if (previewOnly) {
            setStatus(
                `미리보기 <b style="color:#22d3ee;">${books.length}건</b> 추출 (selector=<code>${selector}</code>)<br>` +
                `<small style="color:#8b96a8;">F12 → Console 확인</small>`,
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
                        `✓ 동기화 완료 · 신규 <b>${json.inserted}</b> · 갱신 <b>${json.updated}</b> · 전체 <b>${json.total}</b>건`,
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
