// ==UserScript==
// @name         Kyobo e-Library → NAS Sync
// @namespace    https://192.168.10.205/
// @version      0.8.0
// @description  교보 e-Library 도서 목록을 NAS Kyobo Bridge 로 동기화 + 로그인 상태 감지 보고
// @author       YUNDEOKSOO
// @match        https://elibrary.kyobobook.co.kr/*
// @match        https://ebook.kyobobook.co.kr/dig/*
// @match        https://ebook-product.kyobobook.co.kr/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      192.168.10.205
// @connect      redcodeme.synology.me
// @run-at       document-idle
// @updateURL    https://redcodeme.synology.me/kyobo/userscript/sync-kyobo-library.user.js
// @downloadURL  https://redcodeme.synology.me/kyobo/userscript/sync-kyobo-library.user.js
// ==/UserScript==

(() => {
    'use strict';

    // 패널·로그에 표시할 버전 (@version 과 일치시켜야 함)
    const SCRIPT_VERSION = (typeof GM_info !== 'undefined' && GM_info?.script?.version) || '0.7.0';

    // 환경 자동 분기:
    //  · 외부 도메인 또는 일반 인터넷 환경 → https://redcodeme.synology.me:9443 (Reverse Proxy)
    //  · LAN(VPN) 환경에서 LAN IP 원하면 패널 [URL 저장] 으로 변경 가능
    const DEFAULTS = {
        backend_external: 'https://redcodeme.synology.me:9443',
        backend_lan: 'http://192.168.10.205:9000',
    };
    function pickDefaultBackend() {
        const saved = GM_getValue('backendUrl', null);
        if (saved) return saved;
        // 사용자가 외부망(공유 IP=NAS 외부) 인지 LAN(공유기 안) 인지 자동 판단은 어렵다.
        // 보수적으로: 외부 도메인 우선 (LAN VPN 도 외부 도메인 동작 OK).
        return DEFAULTS.backend_external;
    }
    const backendUrl = () => GM_getValue('backendUrl', pickDefaultBackend());

    // v0.6.1 마이그레이션: 옛 LAN IP 가 저장돼 있으면 외부 도메인으로 자동 갱신
    (function migrateBackend() {
        const saved = GM_getValue('backendUrl', null);
        if (saved && saved.startsWith('http://192.168.10.205')) {
            console.log('[NVK] 옛 LAN backend URL 감지 → 외부 도메인으로 자동 갱신');
            GM_setValue('backendUrl', DEFAULTS.backend_external);
        }
    })();

    // ── 교보 로그인 상태 감지 + 백엔드 보고 (포털 준비 팝업의 ✓ 체크용) ──
    function reportLoginStatus() {
        try {
            const hasLogout = !!document.querySelector('a[href*="logout"], a[href*="Logout"], button[onclick*="logout"]');
            const baro = [...document.querySelectorAll('button,a')]
                .some(el => /webViewerCall/.test(el.getAttribute('onclick') || ''));
            const loggedIn = hasLogout || baro;
            GM_xmlhttpRequest({
                method: 'POST',
                url: backendUrl() + '/api/kyobo/login-status',
                headers: { 'Content-Type': 'application/json' },
                data: JSON.stringify({ logged_in: loggedIn, can_view: baro, page: location.hostname }),
            });
            console.log('[NVK] 로그인 상태 보고:', loggedIn, '(바로보기:', baro, ')');
        } catch (e) { console.warn('[NVK] 로그인 상태 보고 실패', e); }
    }
    setTimeout(reportLoginStatus, 1500);

    // ── UI ──────────────────────────────────────────────
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
                <span>📚 NAS Sync <span style="opacity:0.6;font-weight:400;font-family:monospace;font-size:11px;">v${SCRIPT_VERSION}</span></span>
                <span id="nvk-close" style="cursor:pointer;opacity:0.5;font-size:16px;">×</span>
            </div>
            <div id="nvk-status" style="color:#8b96a8;font-size:12px;margin-bottom:10px;line-height:1.5;">
                백엔드: <code id="nvk-backend" style="color:#22d3ee;">${backendUrl()}</code>
            </div>
            <div style="display:flex;gap:6px;margin-bottom:8px;">
                <button id="nvk-preview" style="flex:1;padding:7px 10px;background:#1c2230;border:1px solid #2f3a4d;border-radius:6px;color:#e6ecf2;cursor:pointer;font-size:12px;">미리보기 (현재)</button>
                <button id="nvk-sync"    style="flex:1;padding:7px 10px;background:rgba(34,211,238,0.18);border:1px solid #22d3ee;border-radius:6px;color:#22d3ee;cursor:pointer;font-size:12px;font-weight:600;">동기화 (전체)</button>
            </div>
            <details style="font-size:11px;color:#8b96a8;">
                <summary style="cursor:pointer;">설정·진단</summary>
                <div style="margin-top:6px;">
                    <input id="nvk-url" type="text" value="${backendUrl()}"
                        style="width:100%;padding:5px;background:#161b24;color:#e6ecf2;border:1px solid #2f3a4d;border-radius:4px;font-family:monospace;font-size:11px;box-sizing:border-box;" />
                    <div style="display:flex;gap:4px;margin-top:5px;">
                        <button id="nvk-save" style="flex:1;padding:4px 8px;background:#1c2230;border:1px solid #2f3a4d;border-radius:4px;color:#e6ecf2;cursor:pointer;font-size:11px;">URL 저장</button>
                        <button id="nvk-diag" style="flex:1;padding:4px 8px;background:#1c2230;border:1px solid #2f3a4d;border-radius:4px;color:#e6ecf2;cursor:pointer;font-size:11px;">진단 dump</button>
                    </div>
                </div>
            </details>
        `;
        document.body.appendChild(panel);

        document.getElementById('nvk-close').onclick = () => panel.remove();
        document.getElementById('nvk-preview').onclick = () => doExtract({ preview: true, scroll: false });
        document.getElementById('nvk-sync').onclick = () => doExtract({ preview: false, allPages: true });
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
            const { books, selector } = extractBooks();
            if (selector && books.length > 0) {
                const sample = document.querySelector(selector);
                console.log('[NVK] sample card outerHTML (첫 카드):\n', sample?.outerHTML);
            }
            setStatus('진단 dump 콘솔 출력 — F12 → Console 확인', '#8b96a8');
        };
    }

    function setStatus(html, color) {
        const el = document.getElementById('nvk-status');
        if (!el) return;
        el.innerHTML = html;
        if (color) el.style.color = color;
    }

    // ── 자동 스크롤 (무한 스크롤 페이지 대응) ─────────────
    // v0.5: window 스크롤이 안 먹히는 SPA(별도 스크롤 컨테이너) 대응.
    //   1단계: 모든 후보 컨테이너 자동 감지
    //   2단계: 각 컨테이너에 스크롤 + 카드 수 변화로 검증
    //   3단계: 카드 증가하는 컨테이너 발견 시 그것만 계속 스크롤
    function findScrollCandidates() {
        const set = new Set([window, document.documentElement, document.body]);
        document.querySelectorAll('*').forEach(el => {
            const delta = el.scrollHeight - el.clientHeight;
            if (delta < 100) return;
            const style = getComputedStyle(el);
            if (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflow === 'auto' || style.overflow === 'scroll') {
                set.add(el);
            }
        });
        return Array.from(set);
    }

    function scrollToBottom(target) {
        if (target === window) {
            window.scrollTo(0, document.documentElement.scrollHeight);
        } else if (target === document.documentElement || target === document.body) {
            window.scrollTo(0, document.documentElement.scrollHeight);
        } else {
            target.scrollTop = target.scrollHeight;
        }
    }

    function describeTarget(t) {
        if (t === window) return 'window';
        if (t === document.documentElement) return '<html>';
        if (t === document.body) return '<body>';
        const cls = (t.className && t.className.toString().slice(0, 50)) || '';
        return `<${t.tagName.toLowerCase()}${cls ? '.' + cls.split(' ')[0] : ''}>`;
    }

    function countCards() {
        let best = 0;
        for (const s of EXTRACT_RULES.cardSelectors) {
            const n = document.querySelectorAll(s).length;
            if (n > best) best = n;
        }
        return best;
    }

    async function autoScroll(opts = {}) {
        const maxRounds = opts.maxRounds || 80;
        const delay = opts.delay || 700;

        const candidates = findScrollCandidates();
        const baseCount = countCards();
        console.log(`[NVK] autoScroll start · 초기 카드 ${baseCount}개 · 스크롤 후보 ${candidates.length}개`,
            candidates.map(describeTarget));

        // 각 후보를 1회씩 시도 → 카드 수 변화가 가장 큰 컨테이너 선택
        let bestTarget = window;
        let bestDelta = 0;
        for (const t of candidates) {
            const before = countCards();
            scrollToBottom(t);
            await new Promise(r => setTimeout(r, 500));
            const after = countCards();
            const delta = after - before;
            console.log(`[NVK]   probe ${describeTarget(t)} → ${before}→${after} (Δ${delta})`);
            if (delta > bestDelta) { bestDelta = delta; bestTarget = t; }
        }
        console.log(`[NVK] 선택된 스크롤 컨테이너: ${describeTarget(bestTarget)} (probe Δ${bestDelta})`);

        // 선택된 컨테이너로 본격 스크롤 (카드 수 변화 기준)
        let lastCount = countCards();
        let stillCount = 0;
        for (let i = 0; i < maxRounds; i++) {
            scrollToBottom(bestTarget);
            setStatus(`자동 스크롤 ${i + 1}/${maxRounds} · 카드 ${lastCount}개 · ${describeTarget(bestTarget)}`, '#8b96a8');
            await new Promise(r => setTimeout(r, delay));
            const c = countCards();
            if (c === lastCount) {
                stillCount++;
                if (stillCount >= 4) break;  // 4회 연속 변화 없으면 종료
            } else {
                stillCount = 0;
                lastCount = c;
            }
        }
        console.log(`[NVK] autoScroll done · 최종 카드 ${lastCount}개`);

        // 추출 위치 복귀 (상단)
        if (bestTarget === window) window.scrollTo(0, 0);
        else bestTarget.scrollTop = 0;
        await new Promise(r => setTimeout(r, 300));
    }

    // ── 풍부한 진단 dump ──────────────────────────────────
    function diagnose() {
        const url = location.href;
        const title = document.title;

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

        const bookLike = Array.from(
            document.querySelectorAll('[class*="book"], [class*="Book"], [class*="library"], [class*="prod"], [class*="item"]')
        ).slice(0, 30).map(el => ({
            tag: el.tagName.toLowerCase(),
            cls: (el.className && el.className.toString()) || '',
            dataset: Object.assign({}, el.dataset),
            text: (el.textContent || '').trim().slice(0, 80),
        }));

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

        // v0.5 — 스크롤 컨테이너 후보
        const scrollCandidates = findScrollCandidates().map(t => {
            if (t === window) return { target: 'window', scrollHeight: document.documentElement.scrollHeight, clientHeight: window.innerHeight };
            return {
                target: describeTarget(t),
                cls: (t.className && t.className.toString().slice(0, 80)) || '',
                scrollHeight: t.scrollHeight,
                clientHeight: t.clientHeight,
                delta: t.scrollHeight - t.clientHeight,
            };
        });

        return { url, title, repeated, bookLike, lists, scrollCandidates };
    }

    // ── 도서 카드 추출 ────────────────────────────────────
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
            '[data-sno]', '[data-isbn]', '[data-prdno]', '[data-cartid]',
        ],
        title: (card) => {
            const cand = card.querySelector(
                '.title, .book-title, .book_title, [class*="title"], [class*="Title"], strong, h3, h4'
            );
            return cand?.textContent?.trim();
        },
        // v0.4 — 한국 도서 사이트 패턴 추가 (.aut, .gd_name, .writer 등)
        author: (card) => {
            const cand = card.querySelector(
                '.author, .book-author, .gd_name, .writer, .writer_name, .aut, '
                + '[class*="author"], [class*="Author"], [class*="writer"], '
                + '[data-author]'
            );
            return cand?.textContent?.trim().replace(/\s+/g, ' ');
        },
        publisher: (card) => {
            const cand = card.querySelector(
                '.publisher, .pub, [class*="publisher"], [class*="Publisher"], '
                + '[class*="company"], [class*="brand"]'
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

    // ── v0.6: ul#myBookList 정확한 추출 (Phase #47) ─────────
    function extractBookCard_v06(li) {
        const checkbox = li.querySelector('input[name="mybookChk"]');
        if (!checkbox) return null;

        const goPrdDetail = li.querySelector('.goPrdDetail');
        const directBtn = li.querySelector('button.clickDirectView');
        const downloadBtn = li.querySelector('button.clickDownload');
        const seriesBtn = li.querySelector('button.btnGoSris');
        const anyBtn = directBtn || downloadBtn || seriesBtn;

        const titleEl = li.querySelector('.info strong');
        const title = titleEl?.textContent?.trim();
        if (!title) return null;

        const infoSpans = li.querySelectorAll('.info > span');
        const coverImg = li.querySelector('.img img');
        const progressEm = li.querySelector('.img > em');
        const ownEm = li.querySelector('.info .own em');

        const salecmdtid = checkbox.value || checkbox.dataset.rprssalecmdtid || null;
        const progressText = progressEm?.textContent?.trim() || '';
        const progress_pct = parseInt(progressText) || 0;

        return {
            salecmdtid,
            kyobo_id: salecmdtid,            // 안정 ID 로 kyobo_id 도 동일 사용
            bkscmdtcode: goPrdDetail?.dataset?.bkscmdtcode || null,
            rprssalecmdtid: checkbox.dataset?.rprssalecmdtid || null,
            dgctsalecmdtdvsncode: goPrdDetail?.dataset?.dgctsalecmdtdvsncode || null,
            title,
            author: infoSpans[0]?.textContent?.trim() || null,
            publisher: infoSpans[1]?.textContent?.trim() || null,
            cover_url: coverImg?.src || null,
            progress_pct,
            can_web_view: !!directBtn,        // ★ wviewer 가능 여부 = clickDirectView 버튼 존재
            status: ownEm?.textContent?.trim() === '소장' ? 'available' : (ownEm?.textContent?.trim() || 'available'),
            // viewer 호출 메타 (Playwright 자동화에 필요)
            ordrid: anyBtn?.dataset?.ordrid || null,
            dgctelbcmdtcdtncode: anyBtn?.dataset?.dgctelbcmdtcdtncode || null,
            dgctsalefrdvsncode: directBtn?.dataset?.dgctsalefrdvsncode || null,
            dgctordrcmdtsrmb: anyBtn?.dataset?.dgctordrcmdtsrmb || null,
        };
    }

    function extractBooks() {
        // v0.6 우선: ul#myBookList 직접 추출 (100% 매칭)
        const list = document.querySelector('ul#myBookList');
        if (list) {
            const cards = list.querySelectorAll(':scope > li');
            if (cards.length > 0) {
                const books = Array.from(cards).map(extractBookCard_v06).filter(Boolean);
                if (books.length > 0) {
                    return { books, selector: 'ul#myBookList > li', tried: [`${cards.length}× ul#myBookList > li (v0.6)`] };
                }
            }
        }

        // fallback: v0.5 추측 로직 (다른 페이지·구조용)
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

    // ── v0.7: 전체 페이지 자동 순회 (Phase #47) ──────────
    // 교보 e-library 는 SPA — fetch 한 page=N HTML 에는 빈 ul#myBookList 만 들어있을 가능성.
    // 그래서 페이지네이션 버튼 클릭으로 SPA navigate + DOM mutation 대기 방식.

    function findPaginationContainer() {
        return document.querySelector('div.pagination#pagi')
            || document.querySelector('div.pagination')
            || document.querySelector('#pagi');
    }

    function findCurrentPageNum() {
        const pag = findPaginationContainer();
        if (!pag) return 1;
        const active = pag.querySelector('.on, .active, [aria-current="page"]');
        const t = active?.textContent?.trim();
        return parseInt(t) || 1;
    }

    function findNextPageElement() {
        const pag = findPaginationContainer();
        if (!pag) return null;
        // 1) 활성 페이지의 다음 형제
        const active = pag.querySelector('.on, .active, [aria-current="page"]');
        if (active) {
            let sib = active.nextElementSibling;
            while (sib) {
                if (sib.tagName === 'A' || sib.tagName === 'BUTTON') return sib;
                sib = sib.nextElementSibling;
            }
        }
        // 2) "다음" 라벨
        const next = pag.querySelector('[aria-label="다음"], .next, .btn_next, [class*="next"]');
        return next || null;
    }

    function firstBookIdInList() {
        return document.querySelector('ul#myBookList input[name="mybookChk"]')?.value || '';
    }

    // v0.7.3: 페이지 번호 + 첫 책 ID 둘 다 변화해야 진짜 페이지 로딩 완료
    async function waitPageChange(beforePageNum, beforeFirstId, timeoutMs = 10000) {
        const t0 = Date.now();
        while (Date.now() - t0 < timeoutMs) {
            await new Promise(r => setTimeout(r, 120));
            const curPage = findCurrentPageNum();
            const curFirstId = firstBookIdInList();
            // 핵심: 첫 책 ID 가 실제로 바뀌어야 새 데이터 로드 완료
            if (curFirstId && curFirstId !== beforeFirstId) {
                // 추가 안정화 (다른 li 들도 로드 완료)
                await new Promise(r => setTimeout(r, 300));
                return true;
            }
        }
        return false;
    }

    async function extractAllPages(onProgress) {
        const allBooks = [];
        const seen = new Set();

        const addBooks = (books, page) => {
            let added = 0;
            for (const b of books) {
                const key = b.salecmdtid || `${b.title}|${b.author}`;
                if (!seen.has(key)) { seen.add(key); allBooks.push(b); added++; }
            }
            if (onProgress) onProgress({ page, total_books: allBooks.length, page_books: books.length, added });
            return added;
        };

        // 1) 현재(=1) 페이지: 직접 추출
        let curPage = findCurrentPageNum();
        const firstBooks = extractBooks().books;
        addBooks(firstBooks, curPage);
        console.log('[NVK] v0.7 page', curPage, 'extracted:', firstBooks.length);

        // 2) 페이지네이션 컨테이너 확인 + 진단
        const pag = findPaginationContainer();
        if (!pag) {
            console.warn('[NVK] pagination 컨테이너 못 찾음 — 단일 페이지로 종료');
            return allBooks;
        }
        console.log('[NVK] pagination 발견:', pag.outerHTML.slice(0, 500));

        // 3) 페이지네이션 클릭 순회 (SPA — DOM mutation 으로 대기)
        const MAX_PAGES = 60;
        let consecutiveEmpty = 0;
        let consecutiveTimeout = 0;
        for (let i = 0; i < MAX_PAGES; i++) {
            const nextEl = findNextPageElement();
            if (!nextEl) {
                console.log('[NVK] 다음 페이지 요소 없음 — 종료');
                break;
            }
            const nextText = nextEl.textContent?.trim() || '';
            const beforePage = findCurrentPageNum();
            const beforeFirstId = firstBookIdInList();
            console.log('[NVK] click next:', nextText, '(현재 page', beforePage, 'firstBook:', beforeFirstId.slice(0,12) + ')');
            nextEl.click();

            const ok = await waitPageChange(beforePage, beforeFirstId, 10000);
            if (!ok) {
                consecutiveTimeout++;
                console.warn('[NVK] page change timeout (', consecutiveTimeout, '/3 ) — page', beforePage, 'firstBook:', firstBookIdInList().slice(0,12));
                if (consecutiveTimeout >= 3) {
                    console.warn('[NVK] timeout 3회 연속 — 종료');
                    break;
                }
                await new Promise(r => setTimeout(r, 500));
                continue;
            }
            consecutiveTimeout = 0;

            curPage = findCurrentPageNum();
            const books = extractBooks().books;
            const added = addBooks(books, curPage);

            if (added === 0) {
                consecutiveEmpty++;
                if (consecutiveEmpty >= 3) {
                    console.warn('[NVK] 신규 0건 3회 연속 — 종료');
                    break;
                }
            } else {
                consecutiveEmpty = 0;
            }
        }
        return allBooks;
    }

    // ── 메인: 추출 + (선택)전송 ──────────────────────────
    async function doExtract({ preview = false, scroll = false, allPages = false } = {}) {
        // v0.7: 전체 페이지 자동 순회 (myBookList 가 있는 페이지에서만)
        if (allPages && document.querySelector('ul#myBookList')) {
            setStatus('전체 페이지 수집 중...', '#22d3ee');
            const allBooks = await extractAllPages(({ page, total_books, page_books }) => {
                setStatus(`📥 page ${page} 처리 · 누적 <b>${total_books}</b>권 (이번 페이지 ${page_books})`, '#22d3ee');
            });
            console.log(`[NVK] === v0.7 전체 페이지 순회 완료: ${allBooks.length}권 ===`);
            if (allBooks.length === 0) {
                setStatus('⚠ 0건 — 도서함 페이지인지 확인하세요', '#f59e0b');
                return;
            }
            if (preview) {
                const canWebCount = allBooks.filter(b => b.can_web_view).length;
                setStatus(
                    `🔍 미리보기 <b>${allBooks.length}권</b> 수집 (전송 X)<br>` +
                    `<small>웹뷰 가능: ${canWebCount}권 · 로컬뷰만: ${allBooks.length - canWebCount}권</small>`,
                    '#8b96a8'
                );
                return;
            }
            // 백엔드 sync
            return sendBooks(allBooks, 'allPages');
        }

        if (scroll) {
            try { await autoScroll(); } catch (e) { console.warn('[NVK] autoScroll error:', e); }
        }

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
            return;
        }

        // 첫 카드 outerHTML 콘솔에 출력 (author/publisher 셀렉터 진단용)
        const sampleCard = document.querySelector(selector);
        const sampleHtml = sampleCard?.outerHTML?.slice(0, 4000);
        console.log(`[NVK] 추출 ${books.length}건 (selector="${selector}", tried=${tried.length}):`, books);
        console.log('[NVK] === 첫 카드 outerHTML (author/publisher 셀렉터 진단용) ===\n', sampleHtml);

        if (preview) {
            const sample = books[0];
            const authorStatus = sample.author ? `author="${sample.author}"` : '<span style="color:#f59e0b">author 못 잡음</span>';
            setStatus(
                `미리보기 <b style="color:#22d3ee;">${books.length}건</b> · selector=<code>${selector}</code><br>` +
                `<small>첫 책: <b>${escHtml(sample.title)}</b> · ${authorStatus}</small>`,
                '#8b96a8'
            );
            return;
        }

        return sendBooks(books, 'single');
    }

    function sendBooks(books, mode) {
        setStatus(`전송 중 · <b>${books.length}건</b>... <small style="color:#8b96a8;">(${mode})</small>`, '#8b96a8');
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
                        `✓ 동기화 · 신규 <b>${json.inserted}</b> · 갱신 <b>${json.updated}</b> · 전체 <b>${json.total}</b>권`,
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
            ontimeout() { setStatus('✗ 타임아웃 — 백엔드 응답 없음', '#ef4444'); },
        });
    }

    function escHtml(s) {
        return String(s || '').replace(/[&<>"']/g, c => (
            {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
        ));
    }

    // ── init ──────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', injectPanel);
    } else {
        injectPanel();
    }
})();
