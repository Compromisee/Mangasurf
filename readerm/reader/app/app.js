/* app.js — reader front-end controller.
 *
 * Talks to Python over pywebview's `window.pywebview.api`. When the page is
 * opened in a plain browser (the LAN phone server, or a test harness) that
 * object is absent, so `call()` falls back to a `fetch` bridge and the UI
 * behaves the same either way.
 */

import './manga-view.js'
import { ACTIONS, PRESETS, PRESET_ORDER, createKeymap, pretty } from './keys.js'
import { createShelves } from './shelves.js'
import {
    ACCENTS, ACCENT_ORDER, THEMES, THEME_ORDER,
    applyAccent, applyAnimations, applyColumns, applyCorners, applyTheme,
    createMatrix, createSearchGridWave,
} from './themes.js'

const $ = sel => document.querySelector(sel)
const $$ = sel => [...document.querySelectorAll(sel)]
const escapeHtml = s => s == null ? '' : String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

const state = {
    settings: {},
    book: null,          // { path, title, kind, pages[]|url }
    chapters: [],
    marks: [],
    filters: {},
    saveTimer: null,
    booted: false,
}

/* ── bridge ───────────────────────────────────────────────────────────── */

const ready = () => new Promise(resolve => {
    if (window.pywebview?.api) return resolve(true)
    let waited = 0
    const tick = () => {
        if (window.pywebview?.api) return resolve(true)
        // pywebview injects its bridge after DOMContentLoaded; if it never
        // shows up we are in a normal browser and use HTTP instead.
        if ((waited += 60) > 3000) return resolve(false)
        setTimeout(tick, 60)
    }
    tick()
})

let useBridge = false

async function call(method, ...args) {
    try {
        if (useBridge && window.pywebview?.api?.[method]) {
            const val = await window.pywebview.api[method](...args)
            return val?.result && typeof val.result === 'object' ? { ...val.result, ...val } : val
        }
        const res = await fetch(`./_api/${method}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ args }),
        })
        if (!res.ok) {
            const res2 = await fetch(`/api/${method}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ args }),
            })
            if (!res2.ok) return { ok: false, error: `HTTP ${res.status}` }
            const data2 = await res2.json()
            return data2?.result && typeof data2.result === 'object' ? { ...data2.result, ...data2 } : data2
        }
        const data = await res.json()
        return data?.result && typeof data.result === 'object' ? { ...data.result, ...data } : data
    } catch (e) {
        return { ok: false, error: String(e?.message || e) }
    }
}

/* ── settings ─────────────────────────────────────────────────────────── */

const DEFAULTS = {
    // Appearance. These already live in Python's DEFAULT_SETTINGS and have
    // been saved and loaded since v1.x -- after v3.0.0 replaced the
    // front-end, nothing read them, so changing them did nothing at all.
    theme: 'midnight', accent: 'blue', corners: 'rounded',
    matrix: true, animations: true, columns: 0,
    // Reading.
    reader_mode: 'webtoon', reader_fit: 'contain',
    reader_gap: 0, reader_max_width: '100%', reader_spread: false,
    reader_filter: 'none', reader_zoom: 1, reader_keep_position: true,
    reader_tap_zones: true, reader_autoscroll_speed: 60,
}

async function loadSettings() {
    const res = await call('get_settings')
    state.settings = { ...DEFAULTS, ...(res?.settings || res || {}) }
    return state.settings
}

let settingsTimer = null
let settingsPending = {}
function pushSettings(changes) {
    Object.assign(state.settings, changes)
    // Coalesce: dragging a slider fires dozens of input events, and each one
    // would otherwise be its own config write.
    //
    // The pending changes have to *accumulate*. An earlier version restarted
    // the timer but only sent the newest object, so changing three settings
    // inside the debounce window saved one and silently dropped two --
    // measured: theme + accent + corners went in, only {corners} came out.
    Object.assign(settingsPending, changes)
    clearTimeout(settingsTimer)
    settingsTimer = setTimeout(() => {
        const batch = settingsPending
        settingsPending = {}
        call('set_settings', batch)
    }, 250)
}

/* ── appearance ───────────────────────────────────────────────────────── */

let matrix = null
let searchWave = null

function setTheme(name, { persist = true } = {}) {
    const theme = applyTheme(name)
    state.settings.theme = document.documentElement.dataset.theme
    if (persist) pushSettings({ theme: state.settings.theme })
    matrix?.refreshColour()
    // A theme's page filter is a starting point, not a lock: an explicit
    // filter choice wins, so switching theme does not silently undo it.
    if (state.settings.reader_filter === 'none' || state.settings._filterFromTheme)
        applyFilter(theme.filter, { fromTheme: true })
    syncAppearanceControls()
    return theme
}

function setAccent(name, { persist = true } = {}) {
    const accent = applyAccent(name)
    state.settings.accent = accent
    if (persist) pushSettings({ accent })
    syncAppearanceControls()
    return accent
}

function setCorners(square, { persist = true } = {}) {
    applyCorners(square)
    state.settings.corners = square ? 'square' : 'rounded'
    if (persist) pushSettings({ corners: state.settings.corners })
    syncAppearanceControls()
    return square
}

function setAnimations(on, { persist = true } = {}) {
    applyAnimations(on)
    state.settings.animations = !!on
    if (persist) pushSettings({ animations: !!on })
    return !!on
}

function setColumns(count, { persist = true } = {}) {
    const n = applyColumns(count)
    state.settings.columns = n
    const out = $('#set-columns-out')
    if (out) out.textContent = n === 0 ? 'Auto' : String(n)
    if (persist) pushSettings({ columns: n })
    return n
}

function setMatrix(on, { persist = true } = {}) {
    matrix?.set(!!on)
    state.settings.matrix = !!on
    if (persist) pushSettings({ matrix: !!on })
    return !!on
}

function applyFilter(filter, { fromTheme = false } = {}) {
    const mv = $('#mv')
    if (filter && filter !== 'none') mv.setAttribute('filter', filter)
    else mv.removeAttribute('filter')
    state.settings._filterFromTheme = fromTheme
    if (!fromTheme) {
        state.settings.reader_filter = filter
        pushSettings({ reader_filter: filter })
    }
    for (const sel of ['#r-filter', '#set-filter']) {
        const el = $(sel)
        if (el) el.value = filter
    }
}

/** Keep every appearance control in step, wherever it lives. */
function syncAppearanceControls() {
    const { theme, accent } = document.documentElement.dataset
    const square = document.documentElement.dataset.corners === 'square'

    for (const el of $$('#theme-tiles .theme-tile'))
        el.classList.toggle('on', el.dataset.theme === theme)
    for (const el of $$('#accent-swatches .swatch'))
        el.classList.toggle('on', el.dataset.accent === accent)

    const rt = $('#r-theme'); if (rt) rt.value = theme
    const ra = $('#r-accent'); if (ra) ra.value = accent
    const rc = $('#r-corners'); if (rc) rc.checked = square
    const sc = $('#set-corners'); if (sc) sc.checked = square
}

/** Theme tiles show the actual palette, read back out of the stylesheet. */
function buildAppearancePickers() {
    const tiles = $('#theme-tiles')
    if (tiles) {
        tiles.innerHTML = THEME_ORDER.map(name => `
            <button class="theme-tile" data-theme="${name}" type="button"
                    title="${esc(THEMES[name].label)}">
              <span class="bars" data-preview="${name}">
                <i></i><i></i><i></i>
              </span>
              <span>${esc(THEMES[name].label)}</span>
            </button>`).join('')
        // Paint each preview from the real theme tokens rather than a
        // hand-copied hex list that would drift out of step with theme.css.
        for (const preview of $$('#theme-tiles .bars')) {
            const probe = document.createElement('div')
            probe.dataset.theme = preview.dataset.preview
            probe.style.display = 'none'
            document.body.append(probe)
            const read = key => getComputedStyle(probe).getPropertyValue(key).trim()
            // The tile's own background is --surface, so a --surface-2 bar
            // next to it is invisible: measured, the middle swatch vanished
            // in every dark theme. Show the three that actually differ.
            const [a, b, c] = preview.querySelectorAll('i')
            a.style.background = read('--bg')
            b.style.background = read('--accent')
            c.style.background = read('--text-2')
            probe.remove()
        }
        tiles.addEventListener('click', e => {
            const tile = e.target.closest('.theme-tile')
            if (tile) setTheme(tile.dataset.theme)
        })
    }

    const swatches = $('#accent-swatches')
    if (swatches) {
        swatches.innerHTML = ACCENT_ORDER.map(name => `
            <button class="swatch" data-accent="${name}" type="button"
                    title="${esc(ACCENTS[name])}" aria-label="${esc(ACCENTS[name])}"></button>`).join('')
        for (const swatch of $$('#accent-swatches .swatch')) {
            const probe = document.createElement('div')
            probe.dataset.theme = document.documentElement.dataset.theme
            probe.dataset.accent = swatch.dataset.accent
            probe.style.display = 'none'
            document.body.append(probe)
            swatch.style.background = getComputedStyle(probe)
                .getPropertyValue('--accent').trim()
            probe.remove()
        }
        swatches.addEventListener('click', e => {
            const swatch = e.target.closest('.swatch')
            if (swatch) setAccent(swatch.dataset.accent)
        })
    }

    const themeSel = $('#r-theme')
    if (themeSel) themeSel.innerHTML = THEME_ORDER
        .map(k => `<option value="${k}">${esc(THEMES[k].label)}${THEMES[k].dark ? '' : ' (light)'}</option>`)
        .join('')
    const accentSel = $('#r-accent')
    if (accentSel) accentSel.innerHTML = ACCENT_ORDER
        .map(k => `<option value="${k}">${esc(ACCENTS[k])}</option>`).join('')
}

/* ── views ────────────────────────────────────────────────────────────── */

function showTab(container, name) {
    for (const tab of container.querySelectorAll('.tab'))
        tab.classList.toggle('on', tab.dataset.tab === name)
    const scope = container.parentElement
    for (const pane of scope.querySelectorAll('.tabpane'))
        pane.hidden = pane.dataset.tab !== name
}

function showView(name) {
    if (name === 'servers') {
        $$('.view').forEach(v => v.classList.toggle('on', v.dataset.view === 'settings'))
        $$('.rail-btn').forEach(b => b.classList.toggle('on', b.id === 'rail-server-btn'))
        const srvTab = $(`#settings-nav-tabs .tab[data-set-target="servers-group"]`)
        if (srvTab) srvTab.click()
        return
    }

    $$('.view').forEach(v => v.classList.toggle('on', v.dataset.view === name))
    $$('.rail-btn').forEach(b => {
        if (b.id === 'rail-server-btn') {
            b.classList.remove('on')
        } else {
            b.classList.toggle('on', b.dataset.view === name)
        }
    })
    if (name === 'library') refreshLibrary()
    if (name === 'queue') refreshQueue()
    if (name === 'stats') refreshStats()
    if (name === 'marks') refreshMarks()
    if (name === 'search') {
        const input = $('#search-input')
        const grid = $('#search-grid')
        const searchView = $('#search-view') || $('.view[data-view="search"]')
        if (searchView && (!input?.value?.trim() && !grid?.children?.length)) {
            searchView.classList.add('search-centered')
            $('#search-hero')?.classList.remove('query-active')
            searchWave?.start()
            searchWave?.setOpacity(1)
        }
    } else {
        searchWave?.stop()
    }
}

/* ── library ──────────────────────────────────────────────────────────── */

let libraryCache = []

/** The shelf tree beside the grid. Created here so it can hand the grid its
 *  filter and open a book through the same path the cards use. */
const shelves = createShelves({
    call, esc, toast,
    onOpenBook: path => path && openPath(path),
    // Selecting a shelf narrows the grid, so the two stay in step without the
    // tree needing to know how a card is drawn.
    onFilter: () => renderLibrary(),
})

async function refreshLibrary() {
    const res = await call('reader_library')
    libraryCache = res?.books || []
    renderLibrary()
    // The tree is a second view of the same books; refreshing it here keeps
    // shelf counts honest after a download finishes.
    shelves.refresh()
    const recent = await call('reader_recent', 8)
    renderContinue(recent?.items || [])
    renderStats(libraryCache, recent?.items || [])
}

function parseBookTitleParts(item) {
    let raw = item.title || item.name || 'Untitled'
    let path = item.path || ''
    // Strip file extension (.cbz, .cbr, .epub, .pdf, .zip, etc.)
    raw = raw.replace(/\.(cbz|cbr|epub|pdf|zip|cb7|mobi|azw3)$/i, '').trim()

    let seriesTitle = raw
    let chapterLabel = ''

    // Match patterns like ' - Chapters 001-050', ' - Chapter 12', ' - Vol. 3', ' Ch. 5', '#12'
    const match = raw.match(/^(.*?)(?:\s*[-–—]\s*|\s+)(Chapters?|Ch\.?|Volumes?|Vol\.?|Ep\.?|Episodes?|#)\s*([0-9].*)$/i)
    if (match) {
        seriesTitle = match[1].trim()
        const prefix = match[2].trim()
        const num = match[3].trim()
        chapterLabel = `${prefix} ${num}`.trim()
    } else if (/^(?:chapter|ch\.?|ep\.?|volume|vol\.?|#)?\s*\d+/i.test(raw) && path) {
        const parts = path.replace(/[\\/]+$/, '').split(/[\\/]/)
        if (parts.length >= 2) {
            seriesTitle = parts[parts.length - 2]
            chapterLabel = raw
        }
    }

    return {
        title: seriesTitle || raw,
        chapter: chapterLabel || (item.kind === 'folder' ? raw : ''),
    }
}

function circularProgressHtml(pct) {
    const radius = 16
    const circ = 2 * Math.PI * radius // ~100.53
    const fraction = Math.max(0, Math.min(100, pct)) / 100
    const offset = circ * (1 - fraction)
    return `
    <div class="progress-ring-wrap" title="${Math.round(pct)}% completed">
      <svg class="progress-ring-svg" width="40" height="40" viewBox="0 0 40 40">
        <circle class="progress-ring-bg" cx="20" cy="20" r="${radius}"></circle>
        <circle class="progress-ring-fill" cx="20" cy="20" r="${radius}"
                stroke-dasharray="${circ.toFixed(2)}"
                stroke-dashoffset="${offset.toFixed(2)}"></circle>
      </svg>
      <span class="progress-ring-text">${Math.round(pct)}%</span>
    </div>`
}

function renderContinue(items) {
    const wrap = $('#continue-wrap'), box = $('#continue')
    const usable = items.filter(i => i.readable !== false)
    wrap.hidden = !usable.length
    box.innerHTML = usable.map(i => {
        const art = coverAttrs(i.cover, '')
        const parts = parseBookTitleParts(i)
        const pct = Math.round((i.fraction || 0) * 100)
        const pageText = i.total ? `page ${(i.index || 0) + 1} of ${i.total}` : 'in progress'
        const subDetails = parts.chapter ? `${esc(parts.chapter)} · ${pageText}` : pageText
        return `
        <div class="row" data-open="${esc(i.path)}">
          <div class="rthumb" style="${art.style}"${art.data}>
            ${art.fallback ? '<span class="mi">image</span>' : ''}
          </div>
          <div class="rmain">
            <div class="rname">${esc(parts.title)}</div>
            <div class="rsub">${subDetails}</div>
          </div>
          ${circularProgressHtml(pct)}
        </div>`
    }).join('')
    hydrateCovers(box)
}

let currentLibPage = 1

function renderLibrary() {
    const term = ($('#lib-filter').value || '').toLowerCase().trim()
    // Shelf selection first, then the text filter: picking a shelf and then
    // typing should search *within* the shelf, not jump back to everything.
    let books = shelves.visibleBooks(libraryCache)
    if (term) books = books.filter(b => (b.title || '').toLowerCase().includes(term))
    renderCarousel(books)

    const grid = $('#library-grid')
    const emptyEl = $('#library-empty')
    const titleEl = $('#all-title')
    const pagBar = $('#lib-pagination')

    const mode = state.settings?.lib_display_mode || 'carousel'
    const isCarouselOnly = mode === 'carousel-only'

    if (isCarouselOnly) {
        grid.hidden = true
        if (titleEl) titleEl.hidden = true
        if (pagBar) pagBar.hidden = true
    } else {
        grid.hidden = !books.length
    }

    const isPaginate = !!state.settings?.lib_paginate
    const pageSize = Number(state.settings?.lib_page_size) || 24
    const totalPages = isPaginate ? Math.max(1, Math.ceil(books.length / pageSize)) : 1

    if (currentLibPage > totalPages) currentLibPage = totalPages
    if (currentLibPage < 1) currentLibPage = 1

    let displayBooks = books
    if (isPaginate && books.length > pageSize) {
        const start = (currentLibPage - 1) * pageSize
        displayBooks = books.slice(start, start + pageSize)
        if (pagBar) {
            pagBar.hidden = false
            const nums = $('#lib-page-numbers')
            if (nums) {
                nums.innerHTML = Array.from({ length: totalPages }, (_, i) => i + 1).map(p => `
                    <button class="lib-page-btn ${p === currentLibPage ? 'on' : ''}" data-page="${p}" type="button">${p}</button>
                `).join('')
            }
            const prevBtn = $('#lib-page-prev')
            const nextBtn = $('#lib-page-next')
            if (prevBtn) prevBtn.disabled = currentLibPage <= 1
            if (nextBtn) nextBtn.disabled = currentLibPage >= totalPages
        }
    } else {
        if (pagBar) pagBar.hidden = true
    }

    grid.innerHTML = displayBooks.map(b => {
        const first = b.items[0]
        const art = coverAttrs(b.cover, b.source)
        // Clicking the cover of something you already downloaded opens it to
        // *read*. It used to route to the series page, which is the download
        // manager -- the wrong destination for a book already on disk. The
        // info button on the corner still goes there.
        const target = first?.path
            ? `data-open="${esc(first.path)}"`
            : `data-manga="${esc(b.url)}"`
        const metaAttrs = `data-key="${esc(b.key || b.url || b.directory || '')}" data-manga="${esc(b.url || '')}" data-directory="${esc(b.directory || '')}" data-title="${esc(b.title || '')}" data-source="${esc(b.source || '')}"`
        const colorAttr = b.color ? `data-card-color="${esc(b.color)}" style="--card-color:${esc(b.color)}"` : ''
        return `<div class="card" ${target} ${metaAttrs} ${colorAttr}>
          <div class="thumb" style="${art.style}"${art.data}>
            ${art.fallback ? '<span class="mi">image</span>' : ''}
            ${b.url ? `<button class="thumb-info" title="Series info"
                         data-manga="${esc(b.url)}" data-source="${esc(b.source || '')}"
                       ><span class="mi">info</span></button>` : ''}
          </div>
          <div class="meta">
            <div class="name">${esc(b.title)}</div>
            <div class="sub">${b.items.length} item${b.items.length === 1 ? '' : 's'} · ${esc(b.source_name || b.provider || b.source || 'local')}</div>
          </div>
        </div>`
    }).join('')
    hydrateCovers(grid)
}

/* ── search (manga sources, not text-in-book) ────────────────────────── */

async function fillSources() {
    const res = await call('get_sources')
    const list = res?.sources || []
    const sourceSelect = $('#set-default-source')
    if (sourceSelect) {
        const cur = state.settings?.default_source || 'mangadex'
        sourceSelect.innerHTML = list.map(s =>
            `<option value="${esc(s.id || s.name)}" ${s.id === cur ? 'selected' : ''}>${esc(s.name || s.id)}</option>`
        ).join('')
        sourceSelect.value = cur
    }
    if ($('#quick-sources-chips')) refreshQuickSources()
}

let currentSearchPage = 1
let currentSearchTotal = 0
let activeSearchSeq = 0
const loadedSearchUrls = new Set()

let searchLayout = 'grid'
function updateSearchLayout(layout) {
    searchLayout = layout || 'grid'
    const grid = $('#search-grid')
    const icon = $('#search-layout-icon')
    if (grid) grid.classList.toggle('list-view', searchLayout === 'list')
    if (icon) icon.textContent = searchLayout === 'list' ? 'grid_view' : 'view_list'
}

const FLARESOLVERR_SOURCES = new Set(['kagane', 'comix', 'mangadotnet', 'manhwa18', 'manga18club', 'hentaiakane'])

async function doSearch(isAppend = false) {
    const thisSearch = ++activeSearchSeq
    const query = ($('#search-input').value || '').trim()
    const status = $('#search-status')
    const view = $('#search-view') || $('.view[data-view="search"]')
    const moreWrap = $('#search-more-wrap')

    // Direct URL support: instant resolve and open detail or curated list
    if (!isAppend && (query.startsWith('http://') || query.startsWith('https://') || query.includes('.moe/') || query.includes('.com/') || query.includes('.org/') || query.includes('.io/') || query.includes('/title/') || query.includes('/series/') || query.includes('/manga/') || query.includes('/gallery/') || query.includes('/lists/'))) {
        try {
            const res = await call('search', query)
            // Curated List URL (e.g. https://chikari.moe/lists/461-my-manhwa-list)
            if (res?.is_list && res?.list) {
                if (status) status.hidden = true
                const listData = res.list
                const series = res.results || listData.series || []
                toast(`Found list: "${listData.title}" (${series.length} series)`)
                const confirmDownload = confirm(`Download all chapters from all ${series.length} manga in "${listData.title}"?`)
                if (confirmDownload) {
                    toast(`Enqueuing all ${series.length} series for download…`)
                    const dlRes = await call('download_list', query)
                    showDownloadToast(`Downloading List: ${listData.title}`, `${dlRes?.enqueued || series.length} series enqueued`, listData.cover)
                    toast(`Started downloading list (${dlRes?.enqueued || series.length} series)`)
                    refreshQueue()
                } else {
                    renderSearchResults(series, false)
                }
                return
            }

            if (res?.url && res?.source) {
                if (status) status.hidden = true
                openDetail(res.url, res.source)
                return
            }
        } catch (e) {
            console.debug('Direct URL search fallback:', e)
        }
    }

    // Parse potential @source prefix from query or filter
    let targetSrc = ''
    const matchPrefix = query.match(/^@([a-zA-Z0-9._-]+)\s*/i) || query.match(/^([a-zA-Z0-9._-]+):\s*/i)
    if (matchPrefix) {
        targetSrc = matchPrefix[1].toLowerCase()
    } else {
        targetSrc = ($('#search-source')?.value || '').trim().toLowerCase()
    }

    if (!isAppend) {
        currentSearchPage = 1
        currentSearchTotal = 0
        loadedSearchUrls.clear()
        // Immediately erase previous results for clean new source population
        $('#search-grid').innerHTML = ''
        if (moreWrap) moreWrap.hidden = true
    } else {
        currentSearchPage += 1
    }

    if (view) view.classList.remove('search-centered')

    status.hidden = false
    const isProtected = targetSrc && FLARESOLVERR_SOURCES.has(targetSrc)

    let loadingTitle = ''
    if (isAppend) {
        loadingTitle = `Loading more ${query ? `results for “${esc(query)}”` : 'trending titles'} (page ${currentSearchPage})`
    } else if (targetSrc) {
        loadingTitle = `Searching <strong>${esc(targetSrc)}</strong>…${isProtected ? ' (resolving Cloudflare protection if needed)' : ''}`
    } else if (query) {
        loadingTitle = `Searching enabled sources for “${esc(query)}”…`
    } else {
        loadingTitle = `Browsing trending titles across sources…`
    }

    if (!isAppend) {
        status.innerHTML = `
        <div class="search-math-wave-container">
          <div class="search-wave-orb">
            <div class="wave-ring ring-1"></div>
            <div class="wave-ring ring-2"></div>
            <div class="wave-ring ring-3"></div>
            <div class="orb-core"><span class="mi spin-icon">sync</span></div>
          </div>
          <div class="search-math-frequencies">
            <span class="freq-bar"></span>
            <span class="freq-bar"></span>
            <span class="freq-bar"></span>
            <span class="freq-bar"></span>
            <span class="freq-bar"></span>
            <span class="freq-bar"></span>
            <span class="freq-bar"></span>
          </div>
          <div class="search-wave-title">${loadingTitle}</div>
          <div class="search-wave-math-formula">λ = v / f · ∫ sin(ωt + φ) dt</div>
        </div>`
    } else {
        const spinIcon = `<span class="mi spin-icon" style="display:inline-block;animation:spin 1s linear infinite;vertical-align:middle;margin-right:6px">sync</span>`
        status.innerHTML = `${spinIcon}${loadingTitle}…`
    }

    const res = await call('search', query, {
        source: $('#search-source')?.value || '',
        sort: $('#srt-sort')?.value || '',
        order: $('#srt-order')?.value || 'Descending',
        status: $('#srt-status')?.value || '',
        type: $('#srt-type')?.value || '',
        genres: [...chosenGenres],
        genre_match: $('#srt-match')?.value || 'all',
        page: currentSearchPage,
    })

    // If another search was started while this one was fetching, ignore stale response
    if (thisSearch !== activeSearchSeq) return

    const rawResults = res?.results || []

    // Deduplicate against already loaded URLs to prevent duplicating old results
    const freshResults = rawResults.filter(r => {
        if (!r || !r.url) return false
        if (loadedSearchUrls.has(r.url)) return false
        loadedSearchUrls.add(r.url)
        return true
    })

    currentSearchTotal += freshResults.length

    if (res?.ok === false) {
        const errMsg = String(res.error || '')
        if (errMsg.toLowerCase().includes('cloudflare') || errMsg.toLowerCase().includes('flaresolverr')) {
            status.innerHTML = `<span class="mi" style="color:var(--accent);vertical-align:middle;margin-right:4px">shield</span> Cloudflare challenge detected for ${esc(targetSrc || 'source')}. <small style="color:var(--text-3)">(Ensure FlareSolverr is running on port 8191)</small>`
        } else {
            status.textContent = `Search failed: ${res.error}`
        }
    } else if (currentSearchTotal === 0) {
        if (isProtected) {
            status.innerHTML = `<span class="mi" style="vertical-align:middle;margin-right:4px">info</span> No results found on <strong>${esc(targetSrc)}</strong>. <small style="color:var(--text-3)">(If this source is behind Cloudflare, start FlareSolverr to bypass)</small>`
        } else {
            status.textContent = `0 results found${query ? ` for “${query}”` : ''}`
        }
    } else {
        status.textContent = `${currentSearchTotal} result${currentSearchTotal === 1 ? '' : 's'}`
            + (query ? ` for “${query}”` : '')
    }

    if (freshResults.length > 0) {
        const newCardsHtml = freshResults.map(r => {
            const art = coverAttrs(r.cover, r.source)
            return `
            <div class="card" data-manga="${esc(r.url)}" data-source="${esc(r.source || '')}">
              <div class="thumb" style="${art.style}"${art.data}>${art.fallback ? '<span class="mi">image</span>' : ''}</div>
              <div class="meta">
                <div class="name">${esc(r.title)}</div>
                <div class="sub">${esc(r.source_name || r.source || '')}</div>
              </div>
            </div>`
        }).join('')

        if (isAppend) {
            $('#search-grid').insertAdjacentHTML('beforeend', newCardsHtml)
        } else {
            $('#search-grid').innerHTML = newCardsHtml
        }

        hydrateCovers($('#search-grid'))
    }

    if (moreWrap) {
        if (freshResults.length > 0) {
            moreWrap.hidden = false
            const loadBtn = $('#search-load-more')
            if (loadBtn) {
                loadBtn.disabled = false
                loadBtn.innerHTML = '<span class="mi">expand_circle_down</span>Load More Results'
            }
        } else if (isAppend || rawResults.length === 0) {
            moreWrap.hidden = false
            const loadBtn = $('#search-load-more')
            if (loadBtn) {
                loadBtn.disabled = true
                loadBtn.innerHTML = '<span class="mi">check_circle</span>No More Results'
            }
        } else {
            moreWrap.hidden = true
        }
    }
}

/* ── HeroUI islands ───────────────────────────────────────────────────── */

/* Real HeroUI components, mounted into DOM the app already owns. The rest of
 * the interface stays vanilla: rewriting 5,000 working lines in React would
 * have spent this release re-earning bugs that are already fixed.
 *
 * Everything degrades: if the bundle is missing, `window.ReaderMUI` is
 * undefined and the plain <select> or <input> underneath keeps working. */

const UI = () => window.MangasurfUI || window.ReaderMUI

/** Replace a native control with a HeroUI one, keeping the original in sync. */
function heroSelect(nativeSelector, { label, placeholder } = {}) {
    const native = $(nativeSelector)
    const ui = UI()
    if (!native || !ui) return
    const host = document.createElement('div')
    host.className = 'rm-island'
    native.after(host)
    native.classList.add('rm-hidden-native')

    const paint = () => ui.select(host, {
        label: label || native.getAttribute('aria-label') || '',
        placeholder,
        items: [...native.options].map(o => ({ id: o.value, label: o.textContent })),
        selected: native.value,
        onSelect: value => {
            native.value = value
            native.dispatchEvent(new Event('change', { bubbles: true }))
        },
    })
    paint()
    // The app rebuilds <option> lists (sources, genres) after data arrives.
    new MutationObserver(paint).observe(native, { childList: true })
    return paint
}

function heroSlider(nativeSelector, { label, format } = {}) {
    const native = $(nativeSelector)
    const ui = UI()
    if (!native || !ui) return
    const host = document.createElement('div')
    host.className = 'rm-island'
    native.after(host)
    native.classList.add('rm-hidden-native')
    ui.slider(host, {
        label,
        value: Number(native.value),
        min: Number(native.min) || 0,
        max: Number(native.max) || 100,
        step: Number(native.step) || 1,
        format,
        onChange: value => {
            native.value = String(value)
            native.dispatchEvent(new Event('input', { bubbles: true }))
        },
    })
}

function mountHeroIslands() {
    if (!UI()) return
    // The search refinements are the controls that most want a real combo box:
    heroSelect('#srt-sort', { label: 'Sort' })
    heroSelect('#srt-order', { label: 'Order' })
    heroSelect('#srt-status', { label: 'Status' })
    heroSelect('#srt-type', { label: 'Type' })
    heroSelect('#srt-match', { label: 'Genre match' })
    heroSelect('#set-downloaded', { label: 'Downloaded titles' })
    document.documentElement.classList.add('heroui-ready')
}

/* ── covers ───────────────────────────────────────────────────────────── */

/* Some sites serve a different image depending on who is asking. MangaDex is
 * the loud example: fetched with `Referer: http://127.0.0.1` it answers 200
 * with a *placeholder* reading "You can read this at mangadex.org" -- measured
 * 59,480 bytes against 77,292 for the real cover at the same URL. Nothing
 * looks broken; the art is simply wrong.
 *
 * Python has no such Referer, so `proxy_cover` fetches it there and hands back
 * a data URI. That is a round trip per cover, so it is done lazily -- only for
 * thumbnails actually scrolled into view -- and the result is cached by the
 * Api for the session.
 */

/* Hosts that refuse, or lie about, a cross-origin image request. Found by
 * watching what the browser actually blocked, not by guessing:
 *   mangadex.org      -- 200 with a "read this at mangadex.org" placeholder
 *   manhuatop.org     -- ERR_BLOCKED_BY_RESPONSE.NotSameOrigin
 *   pstatic.net       -- ERR_BLOCKED_BY_ORB (Webtoons' CDN)
 * Everything else is loaded directly, because a round trip per cover is not
 * free. */
const HOTLINK_PROTECTED = new RegExp(
    '(^|\\.)(' + [
        'mangadex\\.org',
        'manhuatop\\.org',
        'pstatic\\.net',
        'webtoons\\.com',
        'gold-usergeneratedcontent\\.net',
        'hitomi\\.la',
        'kstatic\\.to',
        'shadowabyss\\.com',
        'r2d2storage\\.com',
        'resmk\\.org',
        'qvzre\\.org',
        'qvzra\\.org',
        'chikari\\.moe',
        'witchtoons\\.net',
        'hiperdex\\.com',
        'hiperdex\\.tv',
        'kuramanga\\.com',
        'kurahentai\\.com',
        'mangak\\.io',
        'madaradex\\.org',
    ].join('|') + ')$', 'i')

function needsProxy(url) {
    try {
        return HOTLINK_PROTECTED.test(new URL(url).hostname)
    } catch {
        return false
    }
}

const coverCache = new Map()

async function resolveCover(url, source) {
    if (coverCache.has(url)) return coverCache.get(url)
    try {
        const stored = sessionStorage.getItem(`cv:${url}`)
        if (stored) {
            coverCache.set(url, stored)
            return stored
        }
    } catch {}
    const res = await call('proxy_cover', url, source || undefined)
    const data = res?.data || ''
    if (data) {
        coverCache.set(url, data)
        try { sessionStorage.setItem(`cv:${url}`, data) } catch {}
    }
    return data
}

let coverObserver = null

/** Swap hotlink-protected thumbnails for proxied data as they scroll in. */
function hydrateCovers(root = document) {
    if (!coverObserver) {
        coverObserver = new IntersectionObserver(entries => {
            for (const entry of entries) {
                if (!entry.isIntersecting) continue
                const el = entry.target
                coverObserver.unobserve(el)
                const { coverUrl, coverSource } = el.dataset
                if (!coverUrl) continue
                resolveCover(coverUrl, coverSource).then(data => {
                    if (data) {
                        el.style.backgroundImage = `url('${data}')`
                        el.textContent = ''
                    }
                })
            }
        }, { rootMargin: '600px 0px' })
    }
    for (const el of root.querySelectorAll('[data-cover-url]')) {
        coverObserver.observe(el)
    }
}

function bgUrl(url) {
    if (!url) return ''
    const safeUrl = String(url).replace(/\\/g, '\\\\').replace(/'/g, "\\'")
    return `background-image:url('${safeUrl}')`
}

/** The style + dataset a thumbnail needs, proxying only where required. */
function coverAttrs(url, source) {
    if (!url) return { style: '', data: '', fallback: true }
    if (needsProxy(url)) {
        // Show nothing rather than the placeholder while the real one loads.
        return {
            style: '',
            data: ` data-cover-url="${esc(url)}" data-cover-source="${esc(source || '')}"`,
            fallback: true,
        }
    }
    return { style: bgUrl(url), data: '', fallback: false }
}

/* ── pages sidebar ────────────────────────────────────────────────────── */

/* A list of every page in the book, the way the screenshot shows it, with a
 * bookmark that appears on hover. Page bookmarks reuse the same annotation
 * store the toolbar button writes to, so the two stay in step. */

const pages = { names: [], marks: new Set(), tab: 'all' }

function pageLabel(index) {
    return pages.names[index] || `Page ${index + 1}`
}

async function loadPageMarks() {
    if (!state.book) return
    const res = await call('reader_annotations', state.book.path)
    pages.marks = new Set((res?.annotations?.bookmarks || [])
        .map(mark => Number(mark.index)))
}

function renderPages() {
    const box = $('#pl-items')
    if (!box) return
    const term = ($('#pl-filter').value || '').toLowerCase().trim()
    const mv = $('#mv')
    const current = mv.index

    const rows = []
    for (let i = 0; i < mv.length; i++) {
        const label = pageLabel(i)
        if (term && !label.toLowerCase().includes(term)) continue
        if (pages.tab === 'marked' && !pages.marks.has(i)) continue
        rows.push({ index: i, label })
    }

    const countAll = $('#pl-count-all')
    const countMarked = $('#pl-count-marked')
    if (countAll) countAll.textContent = String(mv.length)
    if (countMarked) countMarked.textContent = String(pages.marks.size)

    box.innerHTML = rows.map(({ index, label }) => {
        const marked = pages.marks.has(index)
        const here = index === current
        return `${here ? `<div class="pl-current"><span class="mi">book</span>
                   Current position<span class="n">${index + 1}</span></div>` : ''}
          <div class="pl-row ${here ? 'on' : ''}" data-page="${index}">
            <span class="pn">${esc(label)}</span>
            <button class="pmark ${marked ? 'on' : ''}" data-mark="${index}"
                    title="${marked ? 'Remove bookmark' : 'Bookmark this page'}">
              <span class="mi">${marked ? 'bookmark' : 'bookmark_border'}</span>
            </button>
          </div>`
    }).join('') || `<p class="empty" style="font-size:12px">${
        pages.tab === 'marked'
            ? 'No bookmarked pages yet. Hover a page and press its bookmark.'
            : 'No pages match.'}</p>`

    const here = box.querySelector('.pl-row.on')
    if (here) here.scrollIntoView({ block: 'nearest' })
}

function renderPagesHeader() {
    const book = state.book
    if (!book) return
    $('#pl-title').textContent = book.title || 'Untitled'
    $('#pl-sub').textContent = `${$('#mv').length} pages`
    for (const [id, cover] of [['#pl-cover', book.cover], ['#r-book', book.cover]]) {
        const el = $(id)
        if (!el) continue
        el.classList.toggle('has-cover', !!cover)
        el.style.backgroundImage = cover ? `url('${cover}')` : ''
    }
}

async function togglePageMark(index) {
    if (!state.book) return
    if (pages.marks.has(index)) {
        const res = await call('reader_annotations', state.book.path)
        const hit = (res?.annotations?.bookmarks || [])
            .find(mark => Number(mark.index) === index)
        if (hit) await call('reader_delete_annotation', state.book.path, 'bookmark', hit.id)
        pages.marks.delete(index)
    } else {
        await call('reader_add_bookmark', state.book.path, index, 0,
                   pageLabel(index))
        pages.marks.add(index)
    }
    renderPages()
    loadMarks()
}

function wirePages() {
    $('#r-pages').addEventListener('click', () => {
        const panel = $('#r-pagelist')
        panel.hidden = !panel.hidden
        $('#r-pages').classList.toggle('on', !panel.hidden)
        if (!panel.hidden) { renderPagesHeader(); renderPages() }
    })
    $('#pl-filter').addEventListener('input', renderPages)
    $('#pl-tabs').addEventListener('click', e => {
        const tab = e.target.closest('[data-ptab]')
        if (!tab) return
        pages.tab = tab.dataset.ptab
        for (const other of $$('#pl-tabs .tab'))
            other.classList.toggle('on', other === tab)
        renderPages()
    })
    $('#pl-items').addEventListener('click', e => {
        const mark = e.target.closest('[data-mark]')
        if (mark) {
            e.stopPropagation()
            togglePageMark(Number(mark.dataset.mark))
            return
        }
        const row = e.target.closest('[data-page]')
        if (row) $('#mv').goTo(Number(row.dataset.page))
    })
}

/* ── minimalist mode ──────────────────────────────────────────────────── */

/* Nothing but the page. The toolbars come back when the pointer nears the top
 * or bottom edge, which is what the thin .zen-edge strips are for -- a
 * whole-window mousemove listener would fire on every pixel of a scroll. */
function setZen(on) {
    const reader = $('#reader')
    reader.classList.toggle('zen', !!on)
    reader.classList.remove('peek-top', 'peek-bottom')
    $('#r-zen').classList.toggle('on', !!on)
    state.settings.reader_zen = !!on
    pushSettings({ reader_zen: !!on })
    if (on) {
        // The drawers are chrome too; leaving one open defeats the point.
        $('#r-panel').hidden = true
        $('#r-chaplist').hidden = true
        $('#r-pagelist').hidden = true
        $('#r-pages').classList.remove('on')
    }
}

function wireZen() {
    $('#r-zen').addEventListener('click', () => setZen(!$('#reader').classList.contains('zen')))
    for (const [selector, cls] of [['.zen-edge.top', 'peek-top'],
                                   ['.zen-edge.bottom', 'peek-bottom']]) {
        const edge = document.querySelector(selector)
        edge.addEventListener('mouseenter', () => $('#reader').classList.add(cls))
        edge.addEventListener('mouseleave', () => $('#reader').classList.remove(cls))
    }
    // A toolbar the pointer is *on* must not vanish out from under it.
    for (const bar of ['#r-top', '#r-bottom']) {
        const cls = bar === '#r-top' ? 'peek-top' : 'peek-bottom'
        $(bar).addEventListener('mouseenter', () => $('#reader').classList.add(cls))
        $(bar).addEventListener('mouseleave', () => $('#reader').classList.remove(cls))
    }
}

/* ── manga detail ─────────────────────────────────────────────────────── */

/* Opening a search result used to do nothing useful. This is the page the
 * screenshot asks for: cover, title, source, tags, description and facts on
 * the left; download options and a chapter picker on the right. */

const detail = {
    url: '', source: '', info: null, chapters: [], selected: new Set(),
    have: new Set(), sort: 'desc', bundle: 0,
}

function parseRanges(text, max) {
    /* "1-20, 25, 30-40" -> a Set of 1-based chapter numbers. Tolerates
     * spaces, reversed pairs and out-of-range values. */
    const picked = new Set()
    for (const part of String(text || '').split(',')) {
        const chunk = part.trim()
        if (!chunk) continue
        const range = chunk.match(/^(\d+)\s*[-–]\s*(\d+)$/)
        if (range) {
            let [, a, b] = range
            a = parseInt(a, 10); b = parseInt(b, 10)
            if (a > b) [a, b] = [b, a]
            for (let i = a; i <= b; i++) if (i >= 1 && i <= max) picked.add(i)
        } else if (/^\d+$/.test(chunk)) {
            const n = parseInt(chunk, 10)
            if (n >= 1 && n <= max) picked.add(n)
        }
    }
    return picked
}

function chapterNumber(chapter) {
    const raw = chapter.number ?? chapter.chapter ?? chapter.name ?? ''
    const hit = String(raw).match(/\d+(\.\d+)?/)
    return hit ? parseFloat(hit[0]) : null
}

/** Clear the chapter filters.
 *
 * They are per-series controls living in a panel that is reused for every
 * series, so leaving them set meant the NEXT series opened filtered by the
 * last one. Reproduced: set the minimum to 50, open a 30-chapter series, and
 * the panel reads "No chapters match those filters." -- which reads as
 * "chapters are not showing", because nothing on screen says a filter is on.
 */
function resetChapterFilters() {
    for (const id of ['#d-min', '#d-max', '#d-find', '#d-range']) {
        const el = $(id)
        if (el) el.value = ''
    }
    const hide = $('#d-hide-have')
    if (hide) hide.checked = false
}

async function openDetail(url, source) {
    if (!url) return
    // A different series: start from an unfiltered view.
    if (detail.url !== url) resetChapterFilters()
    detail.url = url
    detail.source = source || ''
    detail.selected = new Set()
    $('#detail').hidden = false
    $('#d-crumb').textContent = 'Loading…'
    $('#d-title').textContent = 'Loading…'
    $('#d-chapters').innerHTML = '<p class="empty">Fetching chapters…</p>'

    const res = await call('get_manga', url, source || undefined)
    if (res?.ok === false) {
        $('#d-crumb').textContent = 'Could not open'
        $('#d-chapters').innerHTML =
            `<p class="empty">${esc(res.error || 'That series could not be loaded.')}</p>`
        return
    }
    const info = res?.info || res?.manga || res || {}
    detail.info = info
    detail.chapters = info.chapters || res?.chapters || []
    renderDetail(info)

    const lib = await call('downloaded_status', url)
    detail.have = new Set((lib?.chapters || lib?.downloaded || []).map(String))
    renderChapters()

    const marked = await call('get_bookmarks')
    const isMarked = (marked?.items || []).some(b => b.url === url)
    $('#d-bookmark').classList.toggle('on', isMarked)
    const watched = await call('is_watched', url)
    $('#d-watch').classList.toggle('on', !!(watched?.watched ?? watched?.ok))
}

function renderDetail(info) {
    $('#d-crumb').textContent = info.title || 'Series'
    $('#d-title').textContent = info.title || 'Untitled'

    const cover = info.cover || info.cover_medium || info.cover_small
    const art = $('#d-cover')
    if (cover && needsProxy(cover)) {
        art.innerHTML = '<span class="mi">image</span>'
        art.style.backgroundImage = ''
        resolveCover(cover, info.source).then(data => {
            if (data) { art.style.backgroundImage = `url('${data}')`; art.innerHTML = '' }
        })
    } else if (cover) {
        art.style.backgroundImage = `url('${esc(cover)}')`
        art.innerHTML = ''
    } else {
        art.style.backgroundImage = ''
        art.innerHTML = '<span class="mi">image</span>'
    }

    $('#d-source').innerHTML =
        `<i class="live"></i>from <strong>${esc(info.source_name || info.source || 'unknown')}</strong>`
    const people = [...(info.authors || []), ...(info.artists || [])]
    $('#d-people').textContent = [...new Set(people)].join(', ')

    const tags = []
    if (info.source_name) tags.push([info.source_name, 'source-tag', 'source'])
    if (info.status) tags.push([info.status, 'status-tag', 'status'])
    for (const tag of (info.tags || []).slice(0, 18)) {
        const name = typeof tag === 'string' ? tag : (tag.name || '')
        if (name) tags.push([name, 'genre-tag', 'genre'])
    }
    $('#d-tags').innerHTML = tags
        .filter(([label]) => label)
        .map(([label, cls, type]) =>
            `<button type="button" class="chip ${cls} tag-chip clickable-tag" data-tag="${esc(label)}" data-type="${type}" title="Search manga by ${type}: ${esc(label)}">${esc(label)}</button>`
        ).join('')

    $('#d-tags').querySelectorAll('.clickable-tag').forEach(btn => {
        btn.addEventListener('click', e => {
            e.preventDefault()
            e.stopPropagation()
            const tagVal = btn.dataset.tag
            if (!tagVal) return
            showView('search')
            const searchInput = $('#search-input')
            if (searchInput) {
                searchInput.value = tagVal
            }
            doSearch()
        })
    })

    const desc = $('#d-desc')
    desc.textContent = info.description || 'No description.'
    desc.classList.add('clamped')
    const existing = $('#d-more')
    if (existing) existing.remove()
    if ((info.description || '').length > 420) {
        const more = document.createElement('button')
        more.id = 'd-more'
        more.className = 'd-more'
        more.textContent = 'Show more'
        more.addEventListener('click', () => {
            const clamped = desc.classList.toggle('clamped')
            more.textContent = clamped ? 'Show more' : 'Show less'
        })
        desc.after(more)
    }

    const facts = []
    if (info.year) facts.push(['Year', info.year])
    if (info.series_type) facts.push(['Type', info.series_type])
    if (info.demographic) facts.push(['Demographic', info.demographic])
    if (info.original_language) facts.push(['Language', info.original_language])
    if (info.content_rating) facts.push(['Rating', info.content_rating])
    if (info.last_chapter) facts.push(['Last chapter', info.last_chapter])
    $('#d-facts').innerHTML = facts
        .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')
}

function visibleChapters() {
    const min = parseFloat($('#d-min').value)
    const max = parseFloat($('#d-max').value)
    const term = ($('#d-find').value || '').toLowerCase().trim()
    const hideHave = $('#d-hide-have').checked

    let rows = detail.chapters.map((chapter, index) => ({ chapter, index }))
    rows = rows.filter(({ chapter }) => {
        const name = String(chapter.name || chapter.title || chapter.chapter || '')
        if (term && !name.toLowerCase().includes(term)) return false
        if (hideHave && detail.have.has(name)) return false
        const number = chapterNumber(chapter)
        if (!Number.isNaN(min) && number !== null && number < min) return false
        if (!Number.isNaN(max) && number !== null && number > max) return false
        return true
    })
    if (detail.sort === 'desc') rows.reverse()
    return rows
}

function renderChapters() {
    const rows = visibleChapters()
    const box = $('#d-chapters')
    $('#d-count').textContent = String(detail.chapters.length)
    const have = $('#d-have')
    have.hidden = detail.have.size === 0
    have.textContent = `${detail.have.size} downloaded`

    box.innerHTML = rows.length ? rows.map(({ chapter, index }) => {
        const name = String(chapter.name || chapter.title || chapter.chapter || `Chapter ${index + 1}`)
        const downloaded = detail.have.has(name)
        const chosen = detail.selected.has(index)
        const icon = downloaded ? 'check_circle' : (chosen ? 'check_circle' : 'radio_button_unchecked')
        const extra = chapter.date || chapter.scanlator || ''
        return `<div class="ch ${chosen ? 'sel' : ''} ${downloaded ? 'have' : ''}" data-index="${index}">
          <span class="mi">${icon}</span>
          <span class="cname">${esc(name)}</span>
          ${extra ? `<span class="cmeta">${esc(extra)}</span>` : ''}
        </div>`
    }).join('') : emptyChapterMessage()

    updateDownloadLabel()
}

/** Why the list is empty, and how to get out of it.
 *
 * "No chapters match those filters" is true but unhelpful when the filter was
 * left over from a different series and there is no visible sign of it. This
 * names the filters that are actually on and offers a way to clear them.
 */
function emptyChapterMessage() {
    if (!detail.chapters.length)
        return '<p class="empty">This series has no chapters listed.</p>'

    const active = []
    const min = $('#d-min')?.value.trim()
    const max = $('#d-max')?.value.trim()
    const term = $('#d-find')?.value.trim()
    if (min) active.push(`from ${esc(min)}`)
    if (max) active.push(`up to ${esc(max)}`)
    if (term) active.push(`matching “${esc(term)}”`)
    if ($('#d-hide-have')?.checked) active.push('hiding downloaded')

    if (!active.length)
        return '<p class="empty">No chapters match those filters.</p>'
    return `<p class="empty">
        None of the ${detail.chapters.length} chapters match
        ${active.join(', ')}.
        <button class="btn sm" id="d-clear-filters">Clear filters</button>
      </p>`
}

function updateDownloadLabel() {
    const n = detail.selected.size
    $('#d-download-label').textContent =
        n ? `Download ${n} chapter${n === 1 ? '' : 's'}` : 'Download all chapters'
    $('#d-read').hidden = detail.have.size === 0
}

function pickChapters(which) {
    const rows = visibleChapters()
    if (which === 'all') for (const { index } of rows) detail.selected.add(index)
    else if (which === 'none') detail.selected.clear()
    else if (which === 'invert') {
        for (const { index } of rows) {
            if (detail.selected.has(index)) detail.selected.delete(index)
            else detail.selected.add(index)
        }
    } else if (which === 'new') {
        detail.selected.clear()
        for (const { chapter, index } of rows) {
            const name = String(chapter.name || chapter.title || chapter.chapter || '')
            if (!detail.have.has(name)) detail.selected.add(index)
        }
    } else if (which === 'latest') {
        detail.selected.clear()
        const newest = detail.sort === 'desc' ? rows.slice(0, 1) : rows.slice(-1)
        for (const { index } of newest) detail.selected.add(index)
    }
    renderChapters()
}

function closeDetail() {
    $('#detail').hidden = true
    detail.url = ''
}

function wireDetail() {
    $('#d-close').addEventListener('click', closeDetail)
    $('#d-open').addEventListener('click', () => call('open_url', detail.url))

    $('#d-bookmark').addEventListener('click', async () => {
        const res = await call('toggle_bookmark', detail.info || { url: detail.url })
        const on = !!(res?.bookmarked ?? res?.added)
        $('#d-bookmark').classList.toggle('on', on)
        toast(on ? 'Bookmarked' : 'Bookmark removed')
        if (!$('.view[data-view="marks"]').hidden) refreshMarks()
    })

    $('#d-watch').addEventListener('click', async () => {
        const on = $('#d-watch').classList.contains('on')
        await call(on ? 'unwatch' : 'watch', detail.url,
                   detail.info?.title || '', detail.chapters.length,
                   detail.source, detail.info?.cover || '')
        $('#d-watch').classList.toggle('on', !on)
        toast(on ? 'No longer watching' : 'Watching for new chapters')
    })

    $('#d-chapters').addEventListener('click', e => {
        const row = e.target.closest('.ch')
        if (!row) return
        const index = Number(row.dataset.index)
        if (detail.selected.has(index)) detail.selected.delete(index)
        else detail.selected.add(index)
        renderChapters()
    })

    for (const button of $$('#detail [data-pick]'))
        button.addEventListener('click', () => pickChapters(button.dataset.pick))

    $('#d-range-go').addEventListener('click', () => {
        const picked = parseRanges($('#d-range').value, detail.chapters.length)
        detail.selected = new Set([...picked].map(n => n - 1))
        renderChapters()
        toast(`${detail.selected.size} selected`)
    })
    $('#d-range').addEventListener('keydown', e => {
        if (e.key === 'Enter') $('#d-range-go').click()
    })

    for (const id of ['#d-min', '#d-max', '#d-find'])
        $(id).addEventListener('input', renderChapters)
    $('#d-hide-have').addEventListener('change', renderChapters)
    // The "Clear filters" button only exists while the list is empty, so it
    // is reached by delegation rather than bound to an element that comes
    // and goes with every render.
    $('#d-chapters').addEventListener('click', e => {
        if (e.target.closest('#d-clear-filters')) {
            resetChapterFilters()
            renderChapters()
        }
    })
    $('#d-sort').addEventListener('change', e => {
        detail.sort = e.target.value
        renderChapters()
    })
    $('#d-reset').addEventListener('click', () => {
        $('#d-min').value = ''
        $('#d-max').value = ''
        $('#d-find').value = ''
        $('#d-hide-have').checked = false
        detail.selected.clear()
        renderChapters()
    })

    for (const button of $$('#d-format button'))
        button.addEventListener('click', () => {
            for (const other of $$('#d-format button'))
                other.classList.toggle('on', other === button)
            pushSettings({ format: button.dataset.format })
        })
    for (const button of $$('#d-bundle button'))
        button.addEventListener('click', () => {
            for (const other of $$('#d-bundle button'))
                other.classList.toggle('on', other === button)
            detail.bundle = button.dataset.bundle
            $('#d-bundle-n-wrap').hidden = button.dataset.bundle !== 'n'
        })

    $('#d-browse').addEventListener('click', async () => {
        const res = await call('choose_folder')
        const dir = res?.path || res?.folder
        if (dir) { $('#d-out').value = dir; pushSettings({ output_dir: dir }) }
    })

    $('#d-download').addEventListener('click', () => startDetailDownload(false))
    $('#d-queue').addEventListener('click', () => startDetailDownload(true))
    $('#d-read').addEventListener('click', async () => {
        const lib = await call('get_library_entry', detail.url)
        const entry = lib?.entry || lib
        const first = (entry?.items || [])[0]
        if (first?.path) { closeDetail(); openPath(first.path) }
        else toast('Nothing downloaded from this series yet')
    })
}

function chosenChapterNames() {
    if (!detail.selected.size) return []
    return [...detail.selected]
        .sort((a, b) => a - b)
        .map(i => {
            const chapter = detail.chapters[i]
            return String(chapter?.name || chapter?.title || chapter?.chapter || '')
        })
        .filter(Boolean)
}

async function startDetailDownload(queueOnly) {
    if (detail.isStartingDownload) return
    detail.isStartingDownload = true

    const btnDl = $('#d-download')
    const btnQ = $('#d-queue')
    if (btnDl) btnDl.disabled = true
    if (btnQ) btnQ.disabled = true

    try {
        const chapters = chosenChapterNames()
        const bundle = detail.bundle === 'n'
            ? Math.max(2, Number($('#d-bundle-n').value) || 10)
            : Number(detail.bundle) || 0
        const chosenFormat = $('#d-format button.on')?.dataset?.format || state.settings?.format || 'cbz'
        const options = {
            url: detail.url,
            title: detail.info?.title || '',
            cover: detail.info?.cover || '',
            source: detail.source || undefined,
            chapters: chapters.length ? chapters : undefined,
            selection: chapters.length ? chapters : 'all',
            output_dir: $('#d-out').value || undefined,
            format: chosenFormat,
            bundle,
        }
        const res = await call(queueOnly ? 'queue_add' : 'start_download', options)
        if (res?.ok === false) {
            toast(res.error || 'Could not start')
            return
        }
        toast(queueOnly ? 'Added to the queue' : 'Download started')
        refreshQueue()
    } finally {
        setTimeout(() => {
            detail.isStartingDownload = false
            if (btnDl) btnDl.disabled = false
            if (btnQ) btnQ.disabled = false
        }, 1200)
    }
}

/* ── floating download notification toast ────────────────────────── */
let dlToastTimer = null

function showDownloadToast(title, chapterName, coverUrl) {
    const card = $('#download-toast-card')
    if (!card) return
    const titleEl = $('#dl-toast-title')
    const chEl = $('#dl-toast-chapter')
    const thumbEl = $('#dl-toast-thumb')

    if (titleEl) titleEl.textContent = title || 'Manga'
    if (chEl) chEl.textContent = chapterName ? `Chapter: ${chapterName}` : 'Downloading…'
    if (thumbEl) {
        if (coverUrl) {
            thumbEl.style.backgroundImage = `url("${coverUrl}")`
            thumbEl.innerHTML = ''
        } else {
            thumbEl.style.backgroundImage = ''
            thumbEl.innerHTML = '<span class="mi">download</span>'
        }
    }

    card.hidden = false
    card.style.opacity = '1'
    card.style.transform = 'translateY(0)'

    clearTimeout(dlToastTimer)
    dlToastTimer = setTimeout(() => {
        card.style.opacity = '0'
        card.style.transform = 'translateY(24px)'
        setTimeout(() => { card.hidden = true }, 300)
    }, 3500)
}

/* ── 3D Depth Library Carousel ────────────────────────────────────── */
let carouselIndex = 0
let carouselBooks = []

function getBookReadingProgress(book) {
    if (!book) return { percent: 0, readChapters: 0, totalChapters: 0, statusText: 'Unread' }
    const items = book.items || []
    if (!items.length) return { percent: 0, readChapters: 0, totalChapters: 0, statusText: '0 Chapters' }

    let readCount = 0
    let totalFraction = 0

    for (const it of items) {
        if (it.read) {
            readCount += 1
            totalFraction += 1.0
        } else if (it.position) {
            const frac = it.position.fraction || 0
            if (frac >= 0.85) {
                readCount += 1
                totalFraction += 1.0
            } else if (frac > 0) {
                totalFraction += frac
            }
        }
    }

    const pct = Math.min(100, Math.round((totalFraction / items.length) * 100))
    let statusText = 'Unread'
    if (pct >= 100) statusText = 'Completed'
    else if (pct > 0) statusText = `Reading (Ch ${readCount}/${items.length})`

    return {
        percent: pct,
        readChapters: readCount,
        totalChapters: items.length,
        statusText,
    }
}

function sortCarouselBooks(books, sortMode) {
    const list = [...(books || [])]
    if (sortMode === 'progress') {
        list.sort((a, b) => getBookReadingProgress(b).percent - getBookReadingProgress(a).percent)
    } else if (sortMode === 'size') {
        list.sort((a, b) => (b.items?.length || b.chapters || 0) - (a.items?.length || a.chapters || 0))
    } else if (sortMode === 'source') {
        list.sort((a, b) => String(a.source_name || a.source || '').localeCompare(String(b.source_name || b.source || '')))
    } else if (sortMode === 'title') {
        list.sort((a, b) => String(a.title || '').localeCompare(String(b.title || '')))
    } else {
        list.sort((a, b) => String(b.last_download || b.added || '').localeCompare(String(a.last_download || a.added || '')))
    }
    return list
}

function renderCarousel(books) {
    const sortMode = $('#carousel-sort')?.value || 'downloaded'
    carouselBooks = sortCarouselBooks(books, sortMode)
    const wrap = $('#lib-carousel-wrap')
    if (!wrap) return

    const mode = state.settings?.lib_display_mode || 'carousel'
    if (mode === 'grid' || mode === 'list' || carouselBooks.length === 0) {
        wrap.hidden = true
        return
    }

    wrap.hidden = false
    if (carouselIndex >= carouselBooks.length) carouselIndex = Math.max(0, carouselBooks.length - 1)
    const curBook = carouselBooks[carouselIndex]
    if (!curBook) return

    const track = $('#carousel-track')
    if (track) {
        const visibleIndices = []
        for (let i = 0; i < carouselBooks.length; i++) {
            const diff = i - carouselIndex
            if (Math.abs(diff) <= 3) visibleIndices.push(i)
        }

        track.innerHTML = visibleIndices.map(idx => {
            const b = carouselBooks[idx]
            const diff = idx - carouselIndex
            let cls = 'carousel-card'
            if (diff === 0) cls += ' active'
            else if (diff === -1) cls += ' prev-1'
            else if (diff === 1) cls += ' next-1'
            else if (diff === -2) cls += ' prev-2'
            else if (diff === 2) cls += ' next-2'
            else if (diff === -3) cls += ' prev-3'
            else if (diff === 3) cls += ' next-3'

            const art = coverAttrs(b.cover, b.source)
            const style = art.style || (b.cover ? bgUrl(b.cover) : '')
            return `<div class="${cls}" data-carousel-idx="${idx}" style="${style}" ${art.data}></div>`
        }).join('')
        hydrateCovers(track)
    }

    // Dots or counter pill
    const dotsWrap = $('#carousel-dots')
    const counterPill = $('#carousel-counter-pill')
    if (carouselBooks.length <= 20) {
        if (counterPill) counterPill.hidden = true
        if (dotsWrap) {
            dotsWrap.hidden = false
            dotsWrap.innerHTML = carouselBooks.map((_, idx) => `
                <span class="carousel-dot ${idx === carouselIndex ? 'active' : ''}" data-carousel-dot="${idx}"></span>
            `).join('')
        }
    } else {
        if (dotsWrap) dotsWrap.hidden = true
        if (counterPill) {
            counterPill.hidden = false
            counterPill.textContent = `${String(carouselIndex + 1).padStart(2, '0')} / ${String(carouselBooks.length).padStart(2, '0')}`
        }
    }

    // Info panel underneath
    const titleEl = $('#carousel-title')
    if (titleEl) titleEl.textContent = curBook.title || 'Untitled'

    const srcBadge = $('#carousel-source-badge')
    if (srcBadge) srcBadge.textContent = curBook.source_name || curBook.provider || curBook.source || 'Local Library'

    const prog = getBookReadingProgress(curBook)

    const chText = $('#carousel-chapters-text')
    if (chText) {
        chText.textContent = `${prog.readChapters} / ${prog.totalChapters} Chapters Read · ${curBook.items?.length || 0} Files on Disk`
    }

    const statusBadge = $('#carousel-status-badge')
    if (statusBadge) statusBadge.textContent = prog.statusText

    // Progress Bar
    const pctEl = $('#carousel-progress-pct')
    if (pctEl) pctEl.textContent = `${prog.percent}%`
    const fillEl = $('#carousel-progress-bar-fill')
    if (fillEl) fillEl.style.width = `${prog.percent}%`

    // Description
    const descEl = $('#carousel-description')
    if (descEl) descEl.textContent = curBook.description || 'No description available for this series. Click Edit Description to add series summary.'
    const descInput = $('#carousel-desc-input')
    if (descInput) descInput.value = curBook.description || ''

    // Tags
    const tagsEl = $('#carousel-footer-tags')
    if (tagsEl) {
        const tags = curBook.tags || curBook.genres || []
        tagsEl.innerHTML = tags.slice(0, 10).map(t => `<span class="carousel-tag-pill">${escapeHtml(t)}</span>`).join('')
    }
}

function wireCarousel() {
    $('#carousel-sort')?.addEventListener('change', () => {
        carouselIndex = 0
        renderCarousel(libraryCache)
    })

    $('#carousel-immersive-toggle')?.addEventListener('click', () => {
        const wrap = $('#lib-carousel-wrap')
        const icon = $('#carousel-immersive-icon')
        if (wrap && icon) {
            const isSplit = wrap.classList.toggle('immersive-split')
            icon.textContent = isSplit ? 'fullscreen_exit' : 'fullscreen'
            toast(isSplit ? 'Immersive Theatre Mode enabled' : 'Standard Carousel view')
        }
    })

    $('#carousel-prev')?.addEventListener('click', () => {
        if (carouselBooks.length === 0) return
        carouselIndex = (carouselIndex - 1 + carouselBooks.length) % carouselBooks.length
        renderCarousel(carouselBooks)
    })

    $('#carousel-next')?.addEventListener('click', () => {
        if (carouselBooks.length === 0) return
        carouselIndex = (carouselIndex + 1) % carouselBooks.length
        renderCarousel(carouselBooks)
    })

    $('#carousel-track')?.addEventListener('click', e => {
        const card = e.target.closest('[data-carousel-idx]')
        if (!card) return
        const idx = Number(card.dataset.carouselIdx)
        if (isNaN(idx)) return
        if (idx === carouselIndex) {
            // Clicked the active center cover -> Open in reader immediately
            const curBook = carouselBooks[carouselIndex]
            if (curBook) {
                const first = (curBook.items || [])[0]
                if (first?.path) openPath(first.path)
                else if (curBook.url) openDetail(curBook.url, curBook.source)
            }
        } else {
            // Clicked a side card -> Slide and animate to that card
            carouselIndex = idx
            renderCarousel(carouselBooks)
        }
    })

    $('#carousel-dots')?.addEventListener('click', e => {
        const dot = e.target.closest('[data-carousel-dot]')
        if (!dot) return
        const idx = Number(dot.dataset.carouselDot)
        if (!isNaN(idx)) {
            carouselIndex = idx
            renderCarousel(carouselBooks)
        }
    })

    $('#carousel-read-btn')?.addEventListener('click', () => {
        const curBook = carouselBooks[carouselIndex]
        if (!curBook) return
        const first = (curBook.items || [])[0]
        if (first?.path) openPath(first.path)
        else if (curBook.url) openDetail(curBook.url, curBook.source)
    })

    $('#carousel-detail-btn')?.addEventListener('click', () => {
        const curBook = carouselBooks[carouselIndex]
        if (curBook?.url) openDetail(curBook.url, curBook.source)
    })

    $('#carousel-folder-btn')?.addEventListener('click', () => {
        const curBook = carouselBooks[carouselIndex]
        if (curBook?.directory) call('open_folder', curBook.directory)
        else toast('No folder path found')
    })

    // Edit description
    $('#carousel-edit-desc-btn')?.addEventListener('click', () => {
        const wrap = $('#carousel-edit-desc-wrap')
        const descEl = $('#carousel-description')
        if (wrap && descEl) {
            wrap.hidden = false
            descEl.hidden = true
        }
    })

    $('#carousel-cancel-desc-btn')?.addEventListener('click', () => {
        const wrap = $('#carousel-edit-desc-wrap')
        const descEl = $('#carousel-description')
        if (wrap && descEl) {
            wrap.hidden = true
            descEl.hidden = false
        }
    })

    $('#carousel-save-desc-btn')?.addEventListener('click', async () => {
        const curBook = carouselBooks[carouselIndex]
        const val = ($('#carousel-desc-input')?.value || '').trim()
        if (!curBook) return
        curBook.description = val
        const descEl = $('#carousel-description')
        if (descEl) descEl.textContent = val || 'No description available for this series.'
        $('#carousel-edit-desc-wrap').hidden = true
        if (descEl) descEl.hidden = false
        toast('Description saved')
    })
}

/* ── Search Suggestions Dropdown ──────────────────────────────────── */
let suggestTimer = null
let activeSuggestionIdx = -1

function wireSearchSuggestions() {
    const input = $('#search-input')
    const panel = $('#search-suggestions')
    if (!input || !panel) return

    input.addEventListener('input', () => {
        clearTimeout(suggestTimer)
        const val = input.value.trim()
        if (!val || val.length < 2) {
            panel.hidden = true
            panel.innerHTML = ''
            return
        }
        suggestTimer = setTimeout(async () => {
            try {
                const res = await call('suggest_query', val)
                const suggestions = res?.suggestions || []
                const history = (res?.items || []).map(h => ({
                    type: 'history',
                    label: h,
                    value: h,
                    icon: 'history',
                    category: 'Recent',
                }))
                const combined = [...history, ...suggestions].slice(0, 8)
                if (combined.length === 0) {
                    panel.hidden = true
                    panel.innerHTML = ''
                    return
                }
                activeSuggestionIdx = -1
                panel.innerHTML = combined.map((s, idx) => `
                    <div class="suggestion-item" data-suggest-idx="${idx}" data-suggest-val="${escapeHtml(s.value)}" data-suggest-url="${escapeHtml(s.url || '')}" data-suggest-source="${escapeHtml(s.source || '')}">
                        <span class="mi suggestion-icon">${escapeHtml(s.icon || 'search')}</span>
                        <span class="suggestion-label">${escapeHtml(s.label)}</span>
                        <span class="suggestion-category">${escapeHtml(s.category || '')}</span>
                    </div>
                `).join('')
                panel.hidden = false
            } catch (e) {
                console.debug('Search suggestions error:', e)
            }
        }, 140)
    })

    input.addEventListener('keydown', e => {
        if (panel.hidden) return
        const items = [...panel.querySelectorAll('.suggestion-item')]
        if (items.length === 0) return

        if (e.key === 'ArrowDown') {
            e.preventDefault()
            activeSuggestionIdx = (activeSuggestionIdx + 1) % items.length
            items.forEach((it, i) => it.classList.toggle('selected', i === activeSuggestionIdx))
            if (activeSuggestionIdx >= 0) input.value = items[activeSuggestionIdx].dataset.suggestVal
        } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            activeSuggestionIdx = (activeSuggestionIdx - 1 + items.length) % items.length
            items.forEach((it, i) => it.classList.toggle('selected', i === activeSuggestionIdx))
            if (activeSuggestionIdx >= 0) input.value = items[activeSuggestionIdx].dataset.suggestVal
        } else if (e.key === 'Escape') {
            panel.hidden = true
        }
    })

    panel.addEventListener('click', e => {
        const item = e.target.closest('.suggestion-item')
        if (!item) return
        const val = item.dataset.suggestVal
        const url = item.dataset.suggestUrl
        const source = item.dataset.suggestSource
        panel.hidden = true
        if (url && source) {
            openDetail(url, source)
        } else if (val) {
            input.value = val
            doSearch(false)
        }
    })

    document.addEventListener('click', e => {
        if (!e.target.closest('.search-wrap')) {
            panel.hidden = true
        }
    })
}

/* ── bookmarks ────────────────────────────────────────────────────────── */

/* ── servers & opds hub ─────────────────────────────────────────── */

let serverStatusTimer = null
let srvLogsCursor = 0
let srvLogFilter = 'all'

async function refreshServersStatus() {
    try {
        const res = await call('get_servers_status')
        if (!res || res.ok === false) return
        renderServersHub(res)
    } catch (e) {
        console.debug('Failed to fetch servers status:', e)
    }
}

function renderServersHub(data) {
    if (!data) return
    const srv = data.server || {}
    const opds = data.opds || {}
    const isWebRunning = !!srv.running
    const isOpdsRunning = !!opds.running

    // 1. LAN Web Server UI
    const webCard = $('#srv-card-web')
    if (webCard) webCard.classList.toggle('online', isWebRunning)

    const webPill = $('#srv-web-pill')
    if (webPill) {
        webPill.className = `srv-pill ${isWebRunning ? 'online' : 'offline'}`
        const txt = webPill.querySelector('.pill-text')
        if (txt) txt.textContent = isWebRunning ? 'Online' : 'Offline'
    }

    const webInput = $('#srv-web-url-input')
    if (webInput) {
        webInput.value = srv.url || (srv.host_ip ? `http://${srv.host_ip}:${srv.port || 8577}/?token=${srv.token || ''}` : `http://localhost:${srv.port || 8577}`)
    }

    const webTsBox = $('#srv-web-ts-box')
    const webTsInput = $('#srv-web-ts-input')
    if (webTsBox && webTsInput) {
        if (srv.tailscale_url) {
            webTsBox.hidden = false
            webTsInput.value = srv.tailscale_url
        } else {
            webTsBox.hidden = true
        }
    }

    const webUptime = $('#srv-web-uptime')
    if (webUptime) webUptime.textContent = isWebRunning ? (srv.uptime || 'Active') : 'Offline'

    const webDevs = $('#srv-web-clients-count')
    if (webDevs) {
        const c = srv.active_devices_count || 0
        webDevs.textContent = `${c} Active Device${c === 1 ? '' : 's'}`
    }

    const btnToggleWeb = $('#btn-toggle-server')
    if (btnToggleWeb) {
        if (isWebRunning) {
            btnToggleWeb.className = 'btn danger srv-action-toggle'
            btnToggleWeb.innerHTML = '<span class="mi">stop</span><span>Stop Server</span>'
        } else {
            btnToggleWeb.className = 'btn primary srv-action-toggle'
            btnToggleWeb.innerHTML = '<span class="mi">play_arrow</span><span>Start Server</span>'
        }
    }

    // 2. OPDS Catalog UI
    const opdsCard = $('#srv-card-opds')
    if (opdsCard) opdsCard.classList.toggle('online', isOpdsRunning)

    const opdsPill = $('#srv-opds-pill')
    if (opdsPill) {
        opdsPill.className = `srv-pill ${isOpdsRunning ? 'online' : 'offline'}`
        const txt = opdsPill.querySelector('.pill-text')
        if (txt) txt.textContent = isOpdsRunning ? 'Online' : 'Offline'
    }

    const opdsInput = $('#srv-opds-url-input')
    if (opdsInput) {
        opdsInput.value = opds.url || (opds.host_ip ? `http://${opds.host_ip}:${opds.port || 8578}/opds` : `http://localhost:${opds.port || 8578}/opds`)
    }

    const opdsTsBox = $('#srv-opds-ts-box')
    const opdsTsInput = $('#srv-opds-ts-input')
    if (opdsTsBox && opdsTsInput) {
        if (opds.tailscale_url) {
            opdsTsBox.hidden = false
            opdsTsInput.value = opds.tailscale_url
        } else {
            opdsTsBox.hidden = true
        }
    }

    const opdsTitles = $('#srv-opds-titles-count')
    if (opdsTitles) opdsTitles.textContent = `${opds.titles_count || 0} Titles`

    const opdsDevs = $('#srv-opds-clients-count')
    if (opdsDevs) {
        const c = opds.active_devices_count || 0
        opdsDevs.textContent = `${c} Active Reader${c === 1 ? '' : 's'}`
    }

    const opdsUptime = $('#srv-opds-uptime')
    if (opdsUptime) opdsUptime.textContent = isOpdsRunning ? (opds.uptime || 'Active') : 'Offline'

    const btnToggleOpds = $('#btn-toggle-opds')
    if (btnToggleOpds) {
        if (isOpdsRunning) {
            btnToggleOpds.className = 'btn danger srv-action-toggle'
            btnToggleOpds.innerHTML = '<span class="mi">stop</span><span>Stop OPDS</span>'
        } else {
            btnToggleOpds.className = 'btn primary srv-action-toggle'
            btnToggleOpds.innerHTML = '<span class="mi">play_arrow</span><span>Start OPDS</span>'
        }
    }

    // 3. Rail and Summary Badges
    const anyRunning = isWebRunning || isOpdsRunning
    const totalActive = data.total_active_devices || 0

    const railBadge = $('#rail-server-badge')
    if (railBadge) {
        if (anyRunning) {
            railBadge.hidden = false
            railBadge.textContent = totalActive > 0 ? totalActive : 'ON'
            railBadge.title = `Servers Online (${totalActive} active device${totalActive === 1 ? '' : 's'})`
        } else {
            railBadge.hidden = true
        }
    }

    const summaryBadge = $('#servers-summary-badge')
    if (summaryBadge) {
        if (anyRunning) {
            summaryBadge.textContent = `• Online (${totalActive} active)`
            summaryBadge.style.color = '#10b981'
        } else {
            summaryBadge.textContent = '• Offline'
            summaryBadge.style.color = 'var(--text-3)'
        }
    }

    // 4. Connected Devices
    renderConnectedDevices(data.devices || [])
}

function renderConnectedDevices(devices) {
    const badge = $('#srv-total-devices-badge')
    if (badge) badge.textContent = devices.length

    const emptyBox = $('#srv-empty-devices')
    const grid = $('#srv-devices-grid')
    if (!emptyBox || !grid) return

    if (!devices || devices.length === 0) {
        emptyBox.hidden = false
        grid.hidden = true
        grid.innerHTML = ''
        return
    }

    emptyBox.hidden = true
    grid.hidden = false

    grid.innerHTML = devices.map(d => `
        <div class="srv-device-card" data-device-id="${escapeHtml(d.id)}">
          <div class="srv-device-top">
            <div class="srv-device-id">
              <div class="srv-device-icon"><span class="mi">${escapeHtml(d.icon || 'smartphone')}</span></div>
              <div>
                <div class="srv-device-name">${escapeHtml(d.name || 'Remote Device')}</div>
                <div style="font-size:11px;color:var(--text-3)">${escapeHtml(d.ip)} ${d.is_tailscale ? '• Tailscale' : (d.is_localhost ? '• Localhost' : '• LAN')}</div>
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:6px">
              <span class="srv-device-status-dot ${d.is_active ? 'active' : ''}"></span>
              <span style="font-size:11px;font-weight:var(--fw-semi);color:${d.is_active ? '#10b981' : 'var(--text-3)'}">${escapeHtml(d.status_label || (d.is_active ? 'Active' : 'Idle'))}</span>
            </div>
          </div>
          <div class="srv-device-meta">
            <span class="srv-device-badge">${escapeHtml(d.service || 'LAN Reader')}</span>
            <span>${d.requests_count || 1} reqs • ${escapeHtml(d.data_transferred || '0 B')}</span>
          </div>
          <div class="srv-device-footer">
            <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px" title="${escapeHtml(d.last_endpoint || '/')}">${escapeHtml(d.last_endpoint || '/')}</span>
            <span>${d.last_seen_formatted ? escapeHtml(d.last_seen_formatted.split(' ')[1]) : ''}</span>
          </div>
        </div>
    `).join('')
}

let activeQRWifiUrl = ''
let activeQRTailscaleUrl = ''

function updateQRDisplay(type) {
    const url = type === 'tailscale' && activeQRTailscaleUrl ? activeQRTailscaleUrl : activeQRWifiUrl
    const urlInput = $('#srv-qr-url-text')
    if (urlInput) urlInput.value = url

    const target = $('#srv-qr-svg-target')
    if (target && window.QRCode?.createSVG) {
        target.innerHTML = window.QRCode.createSVG(url, { size: 210, margin: 2 })
    } else if (target) {
        target.textContent = url
    }
}

function openServerQR(title, subtitle, wifiUrl, tsUrl = '') {
    const modal = $('#srv-qr-modal')
    if (!modal) return
    const titleEl = $('#srv-qr-title span:last-child')
    if (titleEl) titleEl.textContent = title
    const subEl = $('#srv-qr-subtitle')
    if (subEl) subEl.textContent = subtitle

    activeQRWifiUrl = wifiUrl || ''
    activeQRTailscaleUrl = tsUrl || ''

    const tabWifi = $('#tab-qr-wifi')
    const tabTs = $('#tab-qr-tailscale')
    if (tabWifi) tabWifi.classList.add('on')
    if (tabTs) {
        tabTs.classList.remove('on')
        tabTs.style.display = activeQRTailscaleUrl ? 'inline-flex' : 'none'
    }

    updateQRDisplay('wifi')
    modal.hidden = false
}

async function pollServerLogs() {
    try {
        const res = await call('get_server_logs', { service: srvLogFilter, since: srvLogsCursor })
        if (!res || !res.ok) return
        srvLogsCursor = res.cursor || srvLogsCursor
        const consoleBox = $('#srv-console-box')
        if (!consoleBox || !res.lines || res.lines.length === 0) return

        for (const line of res.lines) {
            const div = document.createElement('div')
            div.className = `srv-log-line ${line.level || 'info'}`
            div.innerHTML = `
                <span class="t">${escapeHtml(line.time || '')}</span>
                <span class="lvl">${escapeHtml(line.level || 'INFO')}</span>
                <span class="srv-tag">${escapeHtml(line.service || 'server')}</span>
                <span class="msg">${escapeHtml(line.text || '')}</span>
            `
            consoleBox.appendChild(div)
        }
        while (consoleBox.children.length > 200) {
            consoleBox.removeChild(consoleBox.firstChild)
        }
        consoleBox.scrollTop = consoleBox.scrollHeight
    } catch (e) {
        console.debug('Log poll failed:', e)
    }
}

function wireServersHub() {
    // 1. LAN Server Controls
    $('#btn-toggle-server')?.addEventListener('click', async () => {
        const isRunning = $('#srv-card-web')?.classList.contains('online')
        if (isRunning) {
            toast('Stopping LAN server…')
            const res = await call('stop_server')
            toast(res?.ok ? 'LAN server stopped' : (res?.error || 'Could not stop server'))
        } else {
            const port = Number($('#set-server-port')?.value || 8577)
            toast('Starting LAN server…')
            const res = await call('start_server', { port })
            toast(res?.ok ? 'LAN server started' : (res?.error || 'Could not start server'))
        }
        await refreshServersStatus()
    })

    $('#btn-restart-server')?.addEventListener('click', async () => {
        toast('Restarting LAN server…')
        const res = await call('restart_server')
        toast(res?.ok ? 'LAN server restarted' : (res?.error || 'Could not restart server'))
        await refreshServersStatus()
    })

    $('#btn-copy-web-url')?.addEventListener('click', () => {
        const val = $('#srv-web-url-input')?.value
        if (val) {
            navigator.clipboard.writeText(val)
            toast('LAN URL copied to clipboard')
        }
    })

    $('#btn-open-web-url')?.addEventListener('click', () => {
        const val = $('#srv-web-url-input')?.value
        if (val) {
            call('open_url', { url: val }).catch(() => window.open(val, '_blank'))
        }
    })

    $('#btn-copy-web-ts')?.addEventListener('click', () => {
        const val = $('#srv-web-ts-input')?.value
        if (val) {
            navigator.clipboard.writeText(val)
            toast('Tailscale URL copied to clipboard')
        }
    })

    $('#btn-qr-server')?.addEventListener('click', () => {
        const wifi = $('#srv-web-url-input')?.value
        const ts = $('#srv-web-ts-input')?.value
        if (wifi) {
            openServerQR('Pair Phone / Tablet', 'Scan with your camera to open Mangasurf on your phone or mobile browser.', wifi, ts)
        }
    })

    // 2. OPDS Catalog Controls
    $('#btn-toggle-opds')?.addEventListener('click', async () => {
        const isRunning = $('#srv-card-opds')?.classList.contains('online')
        if (isRunning) {
            toast('Stopping OPDS catalog…')
            const res = await call('stop_opds')
            toast(res?.ok ? 'OPDS catalog stopped' : (res?.error || 'Could not stop OPDS'))
        } else {
            const port = Number($('#set-opds-port')?.value || 8578)
            toast('Starting OPDS catalog…')
            const res = await call('start_opds', { port })
            toast(res?.ok ? 'OPDS catalog started' : (res?.error || 'Could not start OPDS'))
        }
        await refreshServersStatus()
    })

    $('#btn-restart-opds')?.addEventListener('click', async () => {
        toast('Restarting OPDS catalog…')
        const res = await call('restart_opds')
        toast(res?.ok ? 'OPDS catalog restarted' : (res?.error || 'Could not restart OPDS'))
        await refreshServersStatus()
    })

    $('#btn-copy-opds-url')?.addEventListener('click', () => {
        const val = $('#srv-opds-url-input')?.value
        if (val) {
            navigator.clipboard.writeText(val)
            toast('OPDS Feed URL copied to clipboard')
        }
    })

    $('#btn-copy-opds-ts')?.addEventListener('click', () => {
        const val = $('#srv-opds-ts-input')?.value
        if (val) {
            navigator.clipboard.writeText(val)
            toast('Tailscale OPDS URL copied to clipboard')
        }
    })

    $('#btn-qr-opds')?.addEventListener('click', () => {
        const wifi = $('#srv-opds-url-input')?.value
        const ts = $('#srv-opds-ts-input')?.value
        if (wifi) {
            openServerQR('OPDS Catalog Feed', 'Add this catalog URL in Readest, Panels, KyBook, Aldiko, or Thorium.', wifi, ts)
        }
    })

    // 3. QR Modal & Devices Controls
    $('#srv-qr-tabs')?.addEventListener('click', e => {
        const tab = e.target.closest('.tab')
        if (!tab) return
        for (const t of $$('#srv-qr-tabs .tab')) t.classList.toggle('on', t === tab)
        const type = tab.dataset.qrType || 'wifi'
        updateQRDisplay(type)
    })

    $('#srv-qr-close-btn')?.addEventListener('click', () => {
        const modal = $('#srv-qr-modal')
        if (modal) modal.hidden = true
    })

    $('#srv-qr-modal')?.addEventListener('click', e => {
        if (e.target === $('#srv-qr-modal')) $('#srv-qr-modal').hidden = true
    })

    $('#btn-copy-qr-url')?.addEventListener('click', () => {
        const val = $('#srv-qr-url-text')?.value
        if (val) {
            navigator.clipboard.writeText(val)
            toast('URL copied to clipboard')
        }
    })

    $('#btn-refresh-devices')?.addEventListener('click', async () => {
        toast('Refreshing connected devices…')
        await refreshServersStatus()
    })

    $('#btn-clear-devices')?.addEventListener('click', async () => {
        const res = await call('clear_server_devices', { inactive_only: true })
        toast(`Cleared inactive devices (${res?.removed || 0} removed)`)
        await refreshServersStatus()
    })

    // 4. Rail Jump Button
    $('#rail-server-btn')?.addEventListener('click', () => {
        showView('settings')
        const srvTab = $(`#settings-nav-tabs .tab[data-set-target="servers-group"]`)
        if (srvTab) srvTab.click()
    })

    // 5. Settings Form fields
    $('#set-server-token')?.addEventListener('change', e =>
        call('set_server_config', { token: e.target.value, server_token: e.target.value }))

    $('#server-token-gen')?.addEventListener('click', async () => {
        const res = await call('generate_server_token')
        const token = res?.token || res?.server_token
        if (token) {
            const input = $('#set-server-token')
            if (input) input.value = token
            toast('New access token generated')
            await refreshServersStatus()
        }
    })

    $('#set-server-port')?.addEventListener('change', e => {
        const p = Number(e.target.value)
        call('set_server_config', { port: p, server_port: p })
    })

    $('#set-server-autostart')?.addEventListener('change', e =>
        call('set_server_config', { autostart: e.target.checked }))

    $('#set-server-verbose')?.addEventListener('change', e =>
        call('set_server_config', { verbose: e.target.checked, server_verbose: e.target.checked }))

    $('#set-opds-port')?.addEventListener('change', e => {
        const p = Number(e.target.value)
        call('set_opds_config', { port: p, opds_port: p })
    })

    $('#set-opds-autostart')?.addEventListener('change', e =>
        call('set_opds_config', { autostart: e.target.checked, opds_autostart: e.target.checked }))

    $('#set-opds-cover-root')?.addEventListener('change', e =>
        call('set_opds_config', { cover_root: e.target.value, opds_cover_root: e.target.value }))

    $('#set-opds-cover-browse')?.addEventListener('click', async () => {
        const res = await call('choose_folder')
        const dir = res?.path || res?.folder
        if (dir) {
            const input = $('#set-opds-cover-root')
            if (input) input.value = dir
            call('set_opds_config', { cover_root: dir, opds_cover_root: dir })
        }
    })

    // 6. Log Console Tabs & Controls
    $('#srv-log-tabs')?.addEventListener('click', e => {
        const tab = e.target.closest('.tab')
        if (!tab) return
        for (const t of $$('#srv-log-tabs .tab')) t.classList.toggle('on', t === tab)
        srvLogFilter = tab.dataset.srvLog || 'all'
        srvLogsCursor = 0
        const box = $('#srv-console-box')
        if (box) box.innerHTML = ''
        pollServerLogs()
    })

    $('#btn-clear-srv-logs')?.addEventListener('click', () => {
        const box = $('#srv-console-box')
        if (box) box.innerHTML = ''
        toast('Log console cleared')
    })

    // 7. Polling Timer
    clearInterval(serverStatusTimer)
    serverStatusTimer = setInterval(() => {
        refreshServersStatus()
        pollServerLogs()
    }, 3500)
}

let markCache = []

async function refreshMarks() {
    const [marks, folders] = await Promise.all([
        call('get_bookmarks'), call('get_bookmark_folders'),
    ])
    markCache = marks?.items || []
    const list = folders?.folders || []

    const select = $('#marks-folder')
    const chosen = select.value
    select.innerHTML = '<option value="">All folders</option>'
        + list.map(f => `<option value="${esc(f.id)}">${esc(f.name)}</option>`).join('')
    select.value = chosen

    $('#marks-folders').innerHTML = list.length ? list.map(f => `
        <div class="row" data-folder="${esc(f.id)}">
          <span class="mi">folder</span>
          <div class="rmain">
            <div class="rname">${esc(f.name)}</div>
            <div class="rsub">${f.count ?? 0} saved</div>
          </div>
          <button class="btn sm ghost" data-delfolder="${esc(f.id)}">Delete</button>
        </div>`).join('') : ''

    renderMarks()
}

function renderMarks() {
    const term = ($('#marks-filter').value || '').toLowerCase().trim()
    const folder = $('#marks-folder').value
    let items = markCache
    if (term) items = items.filter(b => (b.title || '').toLowerCase().includes(term))
    if (folder) items = items.filter(b => String(b.folder || '') === folder)

    $('#marks-empty').hidden = !!items.length
    $('#marks-title').hidden = !items.length
    $('#marks-sub').textContent = markCache.length
        ? `${markCache.length} saved series`
        : 'Series you saved for later'

    $('#marks-grid').innerHTML = items.map(b => {
        const art = coverAttrs(b.cover, b.source)
        return `
        <div class="card" data-manga="${esc(b.url)}" data-source="${esc(b.source || '')}">
          <div class="thumb" style="${art.style}"${art.data}>
            ${art.fallback ? '<span class="mi">bookmark</span>' : ''}
          </div>
          <div class="meta">
            <div class="name">${esc(b.title || 'Untitled')}</div>
            <div class="sub">${esc(b.source_name || b.source || '')}</div>
          </div>
        </div>`
    }).join('')
    hydrateCovers($('#marks-grid'))
}

function wireMarks() {
    $('#marks-filter').addEventListener('input', renderMarks)
    $('#marks-folder').addEventListener('change', renderMarks)
    $('#marks-newfolder').addEventListener('click', async () => {
        const name = prompt('Folder name')
        if (!name) return
        await call('create_bookmark_folder', name)
        refreshMarks()
    })
    $('#marks-folders').addEventListener('click', async e => {
        const del = e.target.closest('[data-delfolder]')
        if (del) {
            e.stopPropagation()
            await call('delete_bookmark_folder', del.dataset.delfolder, false)
            refreshMarks()
            return
        }
        const row = e.target.closest('[data-folder]')
        if (row) {
            $('#marks-folder').value = row.dataset.folder
            renderMarks()
        }
    })
}

/* ── genres ───────────────────────────────────────────────────────────── */

const chosenGenres = new Set()

async function refreshGenres() {
    const source = $('#search-source')?.value || undefined
    const res = await call('get_genres', source)
    const genres = (res?.genres || []).map(g => (typeof g === 'string' ? { name: g } : g))
    const box = $('#genre-chips')
    if (!genres.length) {
        box.innerHTML = '<p class="hint">This source does not publish a genre list.</p>'
        return
    }
    box.innerHTML = genres.map(g => {
        const name = g.name || g.id || ''
        return `<button class="chip ${chosenGenres.has(name) ? 'on' : ''}" type="button"
                        data-genre="${esc(name)}">${esc(name)}</button>`
    }).join('')
    updateGenreCount()
}

function updateGenreCount() {
    $('#genre-count').textContent = chosenGenres.size
        ? `${chosenGenres.size} selected` : ''
}

async function refreshQuickSources() {
    const res = await call('get_source_config')
    const sources = res?.sources || []
    const chips = $('#quick-sources-chips')
    if (!chips) return
    const activeCount = sources.filter(s => s.enabled).length
    const countEl = $('#src-active-count')
    if (countEl) countEl.textContent = `${activeCount} of ${sources.length} active`

    chips.innerHTML = sources.map(s => {
        const on = s.enabled ? 'on' : 'off'
        return `<button type="button" class="chip source-toggle-chip ${on}" data-id="${esc(s.id)}" title="Click to ${s.enabled ? 'disable' : 'enable'} ${esc(s.name || s.id)}">
            <span class="dot ${s.enabled ? 'on' : ''}"></span>
            <span>${esc(s.name || s.id)}</span>
        </button>`
    }).join('')

    chips.querySelectorAll('.source-toggle-chip').forEach(btn => {
        btn.addEventListener('click', async e => {
            e.preventDefault()
            const id = btn.dataset.id
            const isCurrentlyOn = btn.classList.contains('on')
            const newState = !isCurrentlyOn
            btn.classList.toggle('on', newState)
            btn.classList.toggle('off', !newState)
            btn.querySelector('.dot')?.classList.toggle('on', newState)

            await call('toggle_source', id, newState)
            await fillSources()
            await refreshQuickSources()
            if ($('#source-list')) {
                const refreshed = await call('get_source_config')
                renderSourceRanks(refreshed?.sources || [])
            }
            toast(`${btn.textContent.trim()} ${newState ? 'enabled' : 'disabled'}`)
        })
    })
}

function addCustomGenre(tag) {
    const clean = String(tag || '').trim()
    if (!clean) return
    chosenGenres.add(clean)
    const box = $('#genre-chips')
    if (box) {
        const existing = box.querySelector(`[data-genre="${clean}"]`)
        if (existing) {
            existing.classList.add('on')
        } else {
            const btn = document.createElement('button')
            btn.type = 'button'
            btn.className = 'chip on custom-chip'
            btn.dataset.genre = clean
            btn.textContent = clean
            box.prepend(btn)
        }
    }
    updateGenreCount()
    doSearch()
}

function wireRefine() {
    $('#search-more').addEventListener('click', () => {
        const panel = $('#refine')
        panel.hidden = !panel.hidden
        if (!panel.hidden) {
            if (!$('#genre-chips').children.length) refreshGenres()
            refreshQuickSources()
        }
    })
    $('#genre-chips').addEventListener('click', e => {
        const chip = e.target.closest('[data-genre]')
        if (!chip) return
        const name = chip.dataset.genre
        if (chosenGenres.has(name)) chosenGenres.delete(name)
        else chosenGenres.add(name)
        chip.classList.toggle('on', chosenGenres.has(name))
        updateGenreCount()
    })
    $('#genre-clear').addEventListener('click', () => {
        chosenGenres.clear()
        for (const chip of $$('#genre-chips .chip')) chip.classList.remove('on')
        updateGenreCount()
    })

    // Custom genre enter & add button
    const customInp = $('#custom-genre-input')
    const customBtn = $('#custom-genre-add-btn')
    const handleAddCustom = () => {
        const val = (customInp?.value || '').trim()
        if (val) {
            addCustomGenre(val)
            customInp.value = ''
        }
    }
    customBtn?.addEventListener('click', handleAddCustom)
    customInp?.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault()
            handleAddCustom()
        }
    })

    // Load more button
    $('#search-load-more')?.addEventListener('click', async e => {
        e.preventDefault()
        const loadBtn = $('#search-load-more')
        if (loadBtn) {
            loadBtn.disabled = true
            loadBtn.innerHTML = '<span class="mi">sync</span>Loading…'
        }
        await doSearch(true)
    })

    $('#src-enable-all')?.addEventListener('click', async () => {
        const res = await call('get_source_config')
        for (const s of (res?.sources || [])) {
            if (!s.enabled) await call('toggle_source', s.id, true)
        }
        await fillSources()
        await refreshQuickSources()
        toast('All sources enabled')
    })
    $('#src-disable-all')?.addEventListener('click', async () => {
        const res = await call('get_source_config')
        for (const s of (res?.sources || [])) {
            if (s.enabled) await call('toggle_source', s.id, false)
        }
        await fillSources()
        await refreshQuickSources()
        toast('All sources disabled')
    })
    $('#search-source')?.addEventListener('change', () => {
        if (!$('#refine').hidden) refreshGenres()
    })
}

/* ── content filters ──────────────────────────────────────────────────── */

/* These live in `features.DEFAULT_FILTERS` and are already applied to every
 * search and browse call on the Python side (`apply_filters`). Until now
 * nothing could set them, so min/max chapters and the block lists were
 * unreachable from the interface. */

const FILTER_DEFAULTS = {
    min_chapters: 0, max_chapters: 0, strict_chapter_range: false,
    blocked_titles: [], blocked_tags: [], blocked_authors: [],
    hide_no_cover: false, safe_mode: false,
}

/** "a, b\nc" -> ["a", "b", "c"]. Commas and newlines both separate. */
function splitList(text) {
    return String(text || '')
        .split(/[,\n]/)
        .map(part => part.trim())
        .filter(Boolean)
}

function describeFilters(filters) {
    const parts = []
    if (filters.min_chapters) parts.push(`≥ ${filters.min_chapters} ch`)
    if (filters.max_chapters) parts.push(`≤ ${filters.max_chapters} ch`)
    const lists = (filters.blocked_titles || []).length
        + (filters.blocked_tags || []).length
        + (filters.blocked_authors || []).length
    if (lists) parts.push(`${lists} blocked`)
    if (filters.hide_no_cover) parts.push('cover required')
    if (filters.safe_mode) parts.push('safe mode')
    return parts.length ? parts.join(' · ') : 'Off'
}

async function refreshFilters() {
    const res = await call('get_filters')
    const filters = { ...FILTER_DEFAULTS, ...(res?.filters || {}) }
    state.filters = filters

    $('#flt-min').value = String(filters.min_chapters ?? 0)
    $('#flt-max').value = String(filters.max_chapters ?? 0)
    $('#flt-strict').checked = !!filters.strict_chapter_range
    $('#flt-titles').value = (filters.blocked_titles || []).join(', ')
    $('#flt-tags').value = (filters.blocked_tags || []).join(', ')
    $('#flt-authors').value = (filters.blocked_authors || []).join(', ')
    $('#flt-nocover').checked = !!filters.hide_no_cover
    $('#flt-safe').checked = !!filters.safe_mode
    $('#filter-summary').textContent = describeFilters(filters)
    return filters
}

let filterTimer = null
function pushFilters(changes) {
    Object.assign(state.filters, changes)
    $('#filter-summary').textContent = describeFilters(state.filters)
    clearTimeout(filterTimer)
    // Typing in a block list fires per keystroke; coalesce like settings do.
    filterTimer = setTimeout(async () => {
        const res = await call('set_filters', { ...state.filters })
        if (res?.filters) {
            state.filters = { ...FILTER_DEFAULTS, ...res.filters }
            $('#filter-summary').textContent = describeFilters(state.filters)
        }
    }, 300)
}

function wireFilters() {
    const number = (selector, key) => $(selector).addEventListener('input', e => {
        // A blank box means "no limit", not NaN.
        const raw = e.target.value.trim()
        pushFilters({ [key]: raw === '' ? 0 : Math.max(0, parseInt(raw, 10) || 0) })
    })
    number('#flt-min', 'min_chapters')
    number('#flt-max', 'max_chapters')

    const list = (selector, key) => $(selector).addEventListener('input', e =>
        pushFilters({ [key]: splitList(e.target.value) }))
    list('#flt-titles', 'blocked_titles')
    list('#flt-tags', 'blocked_tags')
    list('#flt-authors', 'blocked_authors')

    const flag = (selector, key) => $(selector).addEventListener('change', e =>
        pushFilters({ [key]: e.target.checked }))
    flag('#flt-strict', 'strict_chapter_range')
    flag('#flt-nocover', 'hide_no_cover')
    flag('#flt-safe', 'safe_mode')

    $('#flt-clear').addEventListener('click', async () => {
        state.filters = { ...FILTER_DEFAULTS }
        await call('set_filters', { ...FILTER_DEFAULTS })
        await refreshFilters()
        toast('Filters cleared')
    })
}

/* ── queue ────────────────────────────────────────────────────────────── */

let queuePollTimer = null

function renderSparkline(history) {
    if (!history || history.length < 2) return ''
    const maxVal = Math.max(1024, ...history)
    const points = history.map((val, idx) => {
        const x = (idx / (history.length - 1)) * 110
        const y = 26 - ((val / maxVal) * 22)
        return `${x.toFixed(1)},${y.toFixed(1)}`
    }).join(' ')
    return `
    <div class="q-sparkline" title="Live transfer speed graph">
      <svg width="110" height="28" viewBox="0 0 110 28">
        <polyline fill="none" stroke="var(--accent)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" points="${points}" />
      </svg>
    </div>`
}

async function refreshQueue() {
    const res = await call('get_queue')
    const items = res?.queue || res?.items || []
    $('#queue-empty').hidden = !!items.length

    const cartCount = (res?.cart || []).length || (res?.queued || 0)
    const cartBar = $('#cart-bar')
    if (cartBar) {
        if (cartCount > 0) {
            cartBar.hidden = false
            const sub = $('#cart-bar-sub')
            if (sub) sub.textContent = `${cartCount} item${cartCount === 1 ? '' : 's'} in cart ready to download`
        } else {
            cartBar.hidden = true
        }
    }

    $('#queue-list').innerHTML = items.map(j => {
        const pct = Math.round((j.progress || 0) * 100)
        const art = coverAttrs(j.cover, j.source)
        const spark = renderSparkline(j.history || [])
        return `
        <div class="queue-card-expanded" data-job-id="${esc(j.id || '')}">
          <div class="q-top">
            <div class="rthumb" style="${art.style}"${art.data}>
              ${art.fallback ? '<span class="mi">download</span>' : ''}
            </div>
            <div class="rmain">
              <div class="q-header-row">
                <div class="rname">${esc(j.title || 'Download')}</div>
                <span class="qstatus ${j.status === 'running' ? 'active' : ''}">${esc(j.status || 'running')}</span>
              </div>
              <div class="q-metrics-row">
                <span class="q-metric"><span class="mi">menu_book</span>${esc(j.chapter || 'Downloading…')}</span>
                <span class="q-metric"><span class="mi">speed</span>${esc(j.speed_text || '0 KB/s')}</span>
                <span class="q-metric"><span class="mi">schedule</span>ETA ${esc(j.eta_text || '--')}</span>
                <span class="q-metric"><span class="mi">data_usage</span>${esc(j.downloaded_text || '0 B')}</span>
              </div>
            </div>
            ${spark}
            <div class="rpct">${pct}%</div>
          </div>
          <div class="qbar-track">
            <div class="qbar-fill" style="width:${pct}%"></div>
          </div>
        </div>`
    }).join('')
    hydrateCovers($('#queue-list'))

    const activeCount = items.filter(j => j.status === 'running' || j.status === 'queued').length
    const badge = $('#queue-badge')
    if (badge) {
        badge.hidden = !activeCount
        badge.textContent = String(activeCount)
    }

    // Auto-poll while downloads are running
    clearTimeout(queuePollTimer)
    if (activeCount > 0) {
        queuePollTimer = setTimeout(refreshQueue, 1200)
    }
}

// Live engine events from python backend (GUI & LAN Server)
window.onEngineEvents = function(events) {
    if (!Array.isArray(events)) events = [events]
    for (const ev of events) {
        if (!ev) continue
        if (ev.type === 'job_started' || ev.type === 'plan' || ev.type === 'progress' ||
            ev.type === 'chapter_done' || ev.type === 'chapter_failed' ||
            ev.type === 'finished' || ev.type === 'done' || ev.type === 'error' || ev.type === 'stopped') {
            refreshQueue()
        }
        if (ev.type === 'finished' || ev.type === 'done') {
            refreshLibrary()
            if (ev.result?.title) {
                toast(`Download complete: ${ev.result.title}`)
            }
        }
    }
}

/* ── sliders ──────────────────────────────────────────────────────────── */

/** Every slider that has been wired, so fills can be repainted in bulk. */
const sliderRegistry = []

/* A range input cannot express "filled up to the thumb" on its own: the
 * WebKit track is one background, so the fill is painted with a gradient whose
 * stop is a custom property this keeps in step. Firefox has
 * ::-moz-range-progress and needs none of it. */
function paintSlider(el) {
    if (!el) return
    const min = Number(el.min) || 0
    const max = Number(el.max) || 100
    const span = max - min || 1
    const pct = ((Number(el.value) - min) / span) * 100
    el.style.setProperty('--fill', `${Math.max(0, Math.min(100, pct))}%`)
}

/**
 * Wire a slider: repaint the fill, update its value chip, and save.
 *
 * `key` may be null for sliders that drive something other than a setting.
 * `value` maps the raw string to what Python stores; `label` maps it to what
 * the chip shows; `apply` runs an extra side effect.
 */
function bindSlider(selector, key, { value, label, apply } = {}) {
    const el = $(selector)
    if (!el) return
    const out = $(`${selector}-out`)
    const render = () => {
        paintSlider(el)
        if (out) out.textContent = label ? label(el.value) : String(el.value)
    }
    el.addEventListener('input', () => {
        render()
        if (apply) apply(el.value)
        if (key) pushSettings({ [key]: value ? value(el.value) : Number(el.value) })
    })
    render()
    sliderRegistry.push(el)
}

function repaintSliders() {
    for (const el of document.querySelectorAll('input[type="range"]')) paintSlider(el)
}

/* ── stats ────────────────────────────────────────────────────────────── */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function human(n) {
    const v = Number(n) || 0
    if (v >= 1e9) return (v / 1e9).toFixed(1) + 'B'
    if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M'
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'k'
    return String(Math.round(v))
}

function humanBytes(n) {
    let v = Number(n) || 0
    for (const unit of ['B', 'KB', 'MB', 'GB', 'TB']) {
        if (v < 1024) return `${v < 10 && unit !== 'B' ? v.toFixed(1) : Math.round(v)} ${unit}`
        v /= 1024
    }
    return `${v.toFixed(1)} PB`
}

function tiles(target, items) {
    const el = $(target)
    if (!el) return
    el.innerHTML = items.map(([value, label, accent]) =>
        `<div class="stat${accent ? ' accent' : ''}"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join('')
    el.hidden = !items.length
}

const STAT_GRADIENTS = [
    'linear-gradient(90deg, #38bdf8, #818cf8)',
    'linear-gradient(90deg, #a855f7, #ec4899)',
    'linear-gradient(90deg, #10b981, #06b6d4)',
    'linear-gradient(90deg, #fbbf24, #f97316)',
    'linear-gradient(90deg, #f43f5e, #fb7185)',
    'linear-gradient(90deg, #6366f1, #3b82f6)',
    'linear-gradient(90deg, #14b8a6, #22c55e)',
    'linear-gradient(90deg, #e11d48, #c026d3)',
]

function bars(target, rows) {
    const el = $(target)
    if (!el) return
    const peak = Math.max(1, ...rows.map(r => r[1]))
    el.innerHTML = rows.length ? rows.map(([label, value, note], idx) => {
        const grad = STAT_GRADIENTS[idx % STAT_GRADIENTS.length]
        return `
        <div class="bar-row">
          <span class="bl" title="${esc(label)}">
            <span class="bar-dot" style="width:8px;height:8px;border-radius:50%;background:${grad.split(',')[1].trim()};flex-shrink:0"></span>
            ${esc(label)}
          </span>
          <span class="bt"><i style="width:${Math.max(2, (value / peak) * 100).toFixed(1)}%;--bar-grad:${grad}"></i></span>
          <span class="bv">${esc(note ?? human(value))}</span>
        </div>`
    }).join('')
    : '<p class="empty">Nothing recorded yet.</p>'
}

/* Longest and current run of consecutive days with a download. The calendar
 * is already ordered oldest-first and gap-free, so this is a single pass. */
function streaks(days) {
    let best = 0, run = 0, current = 0, active = 0
    for (const day of days) {
        if ((day.chapters || 0) > 0) {
            run += 1
            best = Math.max(best, run)
        } else {
            run = 0
        }
    }
    // "current" counts backwards from the most recent day, allowing today to
    // be empty -- a streak should not read as broken at 09:00.
    for (let i = days.length - 1; i >= 0; i--) {
        const has = (days[i].chapters || 0) > 0
        if (!has && i === days.length - 1) continue
        if (!has) break
        current += 1
        active = 1
    }
    return { best, current: active ? current : 0 }
}

async function refreshStats() {
    const weeks = Number($('#stats-range')?.value) || 52
    const [statsRes, calRes, libRes, recentRes] = await Promise.all([
        call('get_stats'), call('get_calendar', weeks),
        call('reader_library'), call('reader_recent', 10),
    ])

    const stats = statsRes?.stats || {}
    const totals = stats.totals || {}
    const derived = stats.derived || {}

    tiles('#stats-totals', [
        [human(totals.chapters || 0), 'Chapters', true],
        [human(totals.pages || 0), 'Pages'],
        [humanBytes(totals.bytes || 0), 'Downloaded'],
        [human(totals.downloads || 0), 'Jobs'],
        [derived.human_time || '0s', 'Time spent'],
    ])

    renderCalendar(calRes?.calendar || calRes || {})

    const sources = Object.entries(stats.sources || {})
        .sort((a, b) => (b[1].chapters || 0) - (a[1].chapters || 0))

    const totalSrcChapters = sources.reduce((n, s) => n + (s[1].chapters || 0), 0)
    const totalSrcBytes = sources.reduce((n, s) => n + (s[1].bytes || 0), 0)
    const topSource = sources[0] ? (sources[0][1].name || sources[0][0]) : 'None'

    tiles('#stats-sources-strip', [
        [String(sources.length), 'Active Providers', true],
        [human(totalSrcChapters), 'Total Chapters'],
        [humanBytes(totalSrcBytes), 'Data Streamed'],
        [topSource, 'Top Provider'],
    ])

    const peakCh = Math.max(1, ...sources.map(s => s[1].chapters || 0))
    const sGrid = $('#stats-sources-grid')
    if (sGrid) {
        sGrid.innerHTML = sources.map(([id, row], idx) => {
            const grad = STAT_GRADIENTS[idx % STAT_GRADIENTS.length]
            const ch = row.chapters || 0
            const pct = Math.round((ch / Math.max(1, totalSrcChapters)) * 100)
            return `
            <div class="source-stat-card">
              <div class="src-stat-top">
                <div class="src-stat-name">
                  <span class="mi" style="color:var(--accent)">lan</span>
                  <strong>${esc(row.name || id)}</strong>
                </div>
                <span class="src-stat-pct" style="color:${grad.split(',')[1].trim()}">${pct}%</span>
              </div>
              <div class="src-stat-bar-bg">
                <div class="src-stat-bar-fill" style="width:${Math.max(3, (ch / peakCh) * 100)}%;background:${grad}"></div>
              </div>
              <div class="src-stat-footer">
                <span>${human(ch)} chapters</span>
                <span>${humanBytes(row.bytes || 0)}</span>
              </div>
            </div>`
        }).join('')
    }

    bars('#stats-sources', sources.map(([id, row]) =>
        [row.name || id, row.chapters || 0,
         `${human(row.chapters || 0)} ch · ${humanBytes(row.bytes || 0)}`]))

    const books = libRes?.books || []
    const chapters = books.reduce((n, b) => n + (b.chapters || 0), 0)
    const items = books.reduce((n, b) => n + b.items.length, 0)
    tiles('#stats-library', [
        [String(books.length), 'Series', true],
        [human(chapters), 'Chapters held'],
        [human(items), 'Readable items'],
        [String(new Set(books.map(b => b.source).filter(Boolean)).size), 'Sources used'],
    ])
    bars('#stats-biggest', books
        .slice()
        .sort((a, b) => (b.chapters || 0) - (a.chapters || 0))
        .slice(0, 12)
        .map(b => [b.title, b.chapters || 0, `${human(b.chapters || 0)} ch`]))

    const recent = (recentRes?.items || []).filter(r => r.readable !== false)
    const done = recent.filter(r => (r.fraction || 0) >= 0.99).length
    const going = recent.filter(r => (r.fraction || 0) > 0.01 && (r.fraction || 0) < 0.99).length
    const pages = recent.reduce((n, r) => n + (r.index || 0), 0)
    tiles('#stats-reading', [
        [String(going), 'In progress', true],
        [String(done), 'Finished'],
        [human(pages), 'Pages read'],
        [String(recent.length), 'Books opened'],
    ])
    $('#stats-recent').innerHTML = recent.length ? recent.map(r => `
        <div class="row" data-open="${esc(r.path)}">
          <div class="rmain">
            <div class="rname">${esc(r.title || r.name || 'Untitled')}</div>
            <div class="rsub">${esc(r.name || '')}${r.total ? ` · page ${(r.index || 0) + 1} of ${r.total}` : ''}</div>
          </div>
          <div class="rpct">${Math.round((r.fraction || 0) * 100)}%</div>
        </div>`).join('')
        : '<p class="empty">Nothing opened yet.</p>'
}

function renderCalendar(cal) {
    const days = cal.days || []
    const grid = $('#cal')
    if (!grid) return
    if (!days.length) {
        grid.innerHTML = ''
        $('#cal-summary').textContent = 'No activity recorded yet'
        return
    }

    grid.innerHTML = days.map(day => {
        const when = new Date(day.date + 'T00:00:00')
        const label = when.toLocaleDateString(undefined,
            { weekday: 'short', month: 'short', day: 'numeric' })
        const what = day.chapters
            ? `${day.chapters} chapter${day.chapters === 1 ? '' : 's'}${day.top ? ` · ${day.top}` : ''}`
            : 'nothing downloaded'
        return `<i data-level="${day.level || 0}" title="${esc(label)}: ${esc(what)}"></i>`
    }).join('')

    // Month labels line up with the column each month starts in. The grid
    // flows top-to-bottom in weeks of seven, so a column is seven days.
    const months = []
    let last = -1
    days.forEach((day, index) => {
        const when = new Date(day.date + 'T00:00:00')
        if (when.getMonth() !== last && index % 7 === 0) {
            last = when.getMonth()
            months.push({ column: index / 7, label: MONTHS[last] })
        }
    })
    const columns = Math.ceil(days.length / 7)
    const strip = $('#cal-months')
    strip.innerHTML = Array.from({ length: columns }, (_, column) => {
        const hit = months.find(m => m.column === column)
        return `<span style="width:12px;display:inline-block">${hit ? esc(hit.label) : ''}</span>`
    }).join('')
    strip.style.letterSpacing = '0'

    const total = days.reduce((n, d) => n + (d.chapters || 0), 0)
    const active = days.filter(d => (d.chapters || 0) > 0).length
    $('#cal-summary').textContent =
        `${human(total)} chapters on ${active} day${active === 1 ? '' : 's'}`

    const run = streaks(days)
    tiles('#stats-streaks', [
        [`${run.current}d`, 'Current streak', true],
        [`${run.best}d`, 'Longest streak'],
        [String(active), 'Active days'],
        [cal.peak ? `${cal.peak}` : '0', 'Busiest day'],
    ])
}

/* ── source ranking ───────────────────────────────────────────────────── */

/* Drag to reorder, with up/down buttons alongside because a drag gesture is
 * not reachable from a keyboard. Both paths call the same two endpoints
 * (reorder_sources / move_source) that the pre-v3 shell used. */
async function refreshSources() {
    const res = await call('get_source_config')
    renderSourceRanks(res?.sources || [])
}

function renderSourceRanks(rows) {
    const list = $('#source-list')
    if (!list) return
    list.innerHTML = rows.map((row, index) => {
        const caps = []
        if (row.supports_language) caps.push('languages')
        if (row.supports_scanlator) caps.push('scanlators')
        if (row.needs_flaresolverr) caps.push('cloudflare')
        const adult = row.adult_only ? '<span class="cap adult">18+</span>' : ''
        const host = String(row.base_url || '').replace(/^https?:\/\//, '')
        return `<li draggable="true" data-id="${esc(row.id)}" class="${row.enabled ? '' : 'disabled'}">
          <span class="mi drag-handle">drag_indicator</span>
          <span class="rank-num">${index + 1}</span>
          <span class="src-name">${esc(row.name)}<span class="src-host">${esc(host)}</span></span>
          <span class="src-caps">${adult}${caps.map(c => `<span class="cap">${esc(c)}</span>`).join('')}</span>
          <span class="move-btns">
            <button data-move="-1" title="Move up" type="button"><span class="mi">expand_less</span></button>
            <button data-move="1" title="Move down" type="button"><span class="mi">expand_more</span></button>
          </span>
          <label class="switch" title="Include this source">
            <input type="checkbox" ${row.enabled ? 'checked' : ''}><span></span>
          </label>
        </li>`
    }).join('')

    for (const li of list.children) {
        const id = li.dataset.id

        li.querySelector('input[type=checkbox]').addEventListener('change', async e => {
            const isChecked = e.target.checked
            const res = await call('toggle_source', id, isChecked)
            const updated = res?.sources || (await call('get_source_config'))?.sources || []
            renderSourceRanks(updated)
            fillSources()
            toast(`${id} ${isChecked ? 'enabled' : 'disabled'}`)
        })

        for (const btn of li.querySelectorAll('[data-move]')) {
            btn.addEventListener('click', async () => {
                const res = await call('move_source', id, parseInt(btn.dataset.move, 10))
                const updated = res?.sources || (await call('get_source_config'))?.sources || []
                renderSourceRanks(updated)
                fillSources()
            })
        }

        li.addEventListener('dragstart', () => li.classList.add('dragging'))
        li.addEventListener('dragend', async () => {
            li.classList.remove('dragging')
            for (const child of list.children) child.classList.remove('drag-over')
            const order = [...list.children].map(c => c.dataset.id)
            const res = await call('reorder_sources', order)
            const updated = res?.sources || (await call('get_source_config'))?.sources || []
            renderSourceRanks(updated)
            fillSources()
        })
        li.addEventListener('dragover', e => {
            e.preventDefault()
            const dragging = list.querySelector('.dragging')
            if (!dragging || dragging === li) return
            li.classList.add('drag-over')
            const rect = li.getBoundingClientRect()
            const after = e.clientY > rect.top + rect.height / 2
            list.insertBefore(dragging, after ? li.nextSibling : li)
        })
        li.addEventListener('dragleave', () => li.classList.remove('drag-over'))
    }
}

/* ── library & folders ────────────────────────────────────────────────── */

async function refreshLibraryFolders() {
    const res = await call('get_library_folders')
    const outDir = res?.output_dir || ''
    const folders = res?.folders || []
    const list = $('#lib-folders-list')
    if (list) {
        let itemsHtml = ''
        if (outDir) {
            itemsHtml += `
            <li class="folder-item">
              <div class="folder-info">
                <span class="mi">folder</span>
                <span class="folder-path" title="Default Download Directory">${esc(outDir)} <small style="color:var(--accent);font-weight:600">(Primary Downloads)</small></span>
              </div>
              <div class="folder-actions">
                <button class="btn sm ghost" data-scan-folder="${esc(outDir)}" type="button" title="Rescan this folder"><span class="mi">sync</span>Scan</button>
              </div>
            </li>`
        }
        for (const folder of folders) {
            itemsHtml += `
            <li class="folder-item">
              <div class="folder-info">
                <span class="mi">folder_special</span>
                <span class="folder-path" title="${esc(folder)}">${esc(folder)}</span>
              </div>
              <div class="folder-actions">
                <button class="btn sm ghost" data-scan-folder="${esc(folder)}" type="button" title="Rescan this folder"><span class="mi">sync</span>Scan</button>
                <button class="btn sm ghost" data-remove-folder="${esc(folder)}" type="button" title="Remove this monitored folder" style="color:var(--danger)"><span class="mi">delete</span></button>
              </div>
            </li>`
        }
        if (!itemsHtml) {
            itemsHtml = '<p class="folder-empty-note">No library folders configured yet.</p>'
        }
        list.innerHTML = itemsHtml
    }
    const summary = $('#lib-folders-summary')
    if (summary) {
        const total = (outDir ? 1 : 0) + folders.length
        summary.textContent = `${total} path${total === 1 ? '' : 's'}`
    }
}

/* ── password lock ────────────────────────────────────────────────────── */

async function refreshLock() {
    const res = await call('lock_status')
    const on = !!(res?.enabled ?? res?.locked_enabled)
    const toggle = $('#set-lock-enabled')
    if (toggle) toggle.checked = on
    const label = $('#lock-state')
    if (label) label.textContent = on
        ? 'On — the app asks for a password when it starts'
        : 'Off'
    const fields = $('#lock-fields')
    const actions = $('#lock-actions')
    if (fields) fields.hidden = !on
    if (actions) actions.hidden = !on
    state.lock = res || {}
    if (res?.should_lock) showLock(res)
}

function showLock(status) {
    const box = $('#lock')
    if (!box) return
    box.hidden = false
    const hint = $('#lock-hint-text')
    if (hint) hint.textContent = status?.hint
        ? `Hint: ${status.hint}`
        : 'Enter your password to continue.'
    matrix?.pause()
    setTimeout(() => $('#lock-input')?.focus(), 60)
}

async function tryUnlock() {
    const input = $('#lock-input')
    const error = $('#lock-error')
    const res = await call('lock_verify', input.value)
    if (res?.ok) {
        $('#lock').hidden = true
        input.value = ''
        if (error) error.textContent = ''
        if (state.settings.matrix !== false) matrix?.resume()
    } else if (error) {
        error.textContent = res?.error || 'Wrong password'
        input.select()
    }
}

/* ── reading ──────────────────────────────────────────────────────────── */

/**
 * Rewrite a loopback asset URL so it works from another device.
 *
 * `reader_open` returns URLs on the local asset server, which is bound to
 * 127.0.0.1 on purpose. On a phone that address is the *phone*, so every page
 * 404'd; and pointing it at the host's LAN address does not help either --
 * the asset server rejects non-loopback callers with 403. Both measured.
 *
 * When the page itself was served from somewhere other than loopback we are
 * on the LAN, so the bytes are fetched through this origin's /stream routes
 * instead. Locally nothing changes and the URL is returned untouched.
 */
function streamUrl(url) {
    if (!url) return url
    const here = location.hostname
    if (!here || here === '127.0.0.1' || here === 'localhost') return url
    let parsed
    try { parsed = new URL(url, location.href) } catch { return url }
    if (parsed.hostname !== '127.0.0.1' && parsed.hostname !== 'localhost')
        return url
    const path = parsed.searchParams.get('path')
    if (!path) return url
    const route = parsed.pathname.startsWith('/book') ? 'book' : 'page'
    return `${location.origin}/stream/${route}?path=${encodeURIComponent(path)}`
}

async function openPath(path) {
    if (!path) return
    const res = await call('reader_open', path)
    if (!res?.ok) return toast(res?.error || 'Could not open that')

    if (Array.isArray(res.pages)) res.pages = res.pages.map(streamUrl)
    if (res.url) res.url = streamUrl(res.url)
    if (res.cover) res.cover = streamUrl(res.cover)
    state.book = res
    $('#r-title').textContent = res.title || 'Untitled'
    $('#reader').hidden = false
    document.body.style.overflow = 'hidden'

    const mv = $('#mv')
    if (res.kind === 'pages') {
        await mv.open({ pages: res.pages })
    } else {
        // Packaged file: hand it to the foliate-js engine, streaming instant
        // HTTP ranges so a 500MB CBZ opens in milliseconds without full download.
        try {
            const { makeBook } = await import('../foliate/view.js')
            const ext = res.format || (res.path ? res.path.split('.').pop() : 'cbz')
            const baseName = res.title || 'book'
            const filename = baseName.toLowerCase().endsWith('.' + ext.toLowerCase()) ? baseName : `${baseName}.${ext}`
            const file = await openRemoteBookFile(res.url, filename)
            const book = await makeBook(file)
            await mv.open(book)
        } catch (e) {
            toast(`Could not read ${res.format || 'file'}: ${e.message}`)
            console.error('open failed', res.url, e)
            return
        }
    }

    pages.names = res.names || []
    applyReadingPrefs()
    startAutosave()
    renderPagesHeader()
    await loadChapters()
    await loadMarks()
    await loadPageMarks()
    if (!$('#r-pagelist').hidden) renderPages()

    const pos = res.position
    if (pos && state.settings.reader_keep_position !== false) {
        if (pos.fraction) mv.setFraction(pos.fraction)
        else if (pos.index) mv.goTo(pos.index)
        if (pos.index || pos.fraction) toast(`Resumed at ${Math.round((pos.fraction || 0) * 100)}%`)
    }
}

function makeHttpRangeFile(url, size, name) {
    const token = typeof location !== 'undefined' && location.search ? new URLSearchParams(location.search).get('token') : ''
    const headers = token ? { 'X-Mangasurf-Token': token, 'X-ReaderM-Token': token } : {}

    return {
        name: name || 'book.cbz',
        type: 'application/vnd.comicbook+zip',
        size: size,
        slice(start = 0, end = size) {
            const actualStart = start < 0 ? Math.max(0, size + start) : start
            const actualEnd = Math.min(size, end < 0 ? Math.max(0, size + end) : end)
            const sliceLength = Math.max(0, actualEnd - actualStart)

            return {
                size: sliceLength,
                type: 'application/octet-stream',
                slice(s = 0, e = sliceLength) {
                    return this
                },
                async arrayBuffer() {
                    if (sliceLength === 0) return new ArrayBuffer(0)
                    const rangeHeader = `bytes=${actualStart}-${actualEnd - 1}`
                    const res = await fetch(url, {
                        headers: {
                            ...headers,
                            Range: rangeHeader
                        }
                    })
                    if (res.status === 206 || res.status === 200) {
                        return await res.arrayBuffer()
                    }
                    throw new Error(`Range request failed: HTTP ${res.status}`)
                }
            }
        }
    }
}

async function openRemoteBookFile(url, name) {
    const token = typeof location !== 'undefined' && location.search ? new URLSearchParams(location.search).get('token') : ''
    const headers = token ? { 'X-Mangasurf-Token': token, 'X-ReaderM-Token': token } : {}

    try {
        const headRes = await fetch(url, { method: 'HEAD', headers })
        const len = headRes.headers.get('Content-Length')
        const acceptRanges = headRes.headers.get('Accept-Ranges')
        const size = len ? parseInt(len, 10) : 0

        if (headRes.ok && size > 0 && acceptRanges === 'bytes') {
            return makeHttpRangeFile(url, size, name)
        }
    } catch (e) {
        console.debug('Fast HEAD range check failed, falling back:', e)
    }

    return await fetchAsFile(url, name)
}

async function fetchAsFile(url, name, attempts = 3) {
    const token = typeof location !== 'undefined' && location.search ? new URLSearchParams(location.search).get('token') : ''
    const headers = token ? { 'X-Mangasurf-Token': token, 'X-ReaderM-Token': token } : {}
    let last = null
    for (let attempt = 1; attempt <= attempts; attempt++) {
        try {
            const res = await fetch(url, { cache: 'no-store', headers })
            if (!res.ok) throw new Error(`server said ${res.status}`)
            const blob = await res.blob()
            if (!blob.size) throw new Error('the file came back empty')
            return new File([blob], name || 'book.cbz', { type: blob.type || 'application/vnd.comicbook+zip' })
        } catch (err) {
            last = err
            if (attempt < attempts) {
                await new Promise(done => setTimeout(done, 250 * attempt))
            }
        }
    }
    throw new Error(`${last?.message || last}. Tried ${attempts} times.`)
}

function applyReadingPrefs() {
    const mv = $('#mv'), s = state.settings
    mv.setAttribute('mode', s.reader_mode || 'webtoon')
    mv.setAttribute('fit', s.reader_fit || 'contain')
    mv.setAttribute('gap', String(s.reader_gap ?? 0))
    mv.setAttribute('max-width', s.reader_max_width || '100%')
    mv.setAttribute('zoom', String(s.reader_zoom ?? 1))
    if (s.reader_spread) mv.setAttribute('spread', ''); else mv.removeAttribute('spread')
    applyFilter(s.reader_filter || 'none', { fromTheme: false })
    $('#tapzones').hidden = s.reader_tap_zones === false
    $$('#mode-seg button').forEach(b => b.classList.toggle('on', b.dataset.mode === (s.reader_mode || 'webtoon')))
    const f = $('#r-fit'); if (f) f.value = s.reader_fit || 'contain'
    const w = $('#r-width'); if (w) w.value = parseInt(s.reader_max_width) || 100
    const g = $('#r-gap'); if (g) g.value = s.reader_gap ?? 0
    const sp = $('#r-spread'); if (sp) sp.checked = !!s.reader_spread
}

function closeReader() {
    $('#mv').stopAutoScroll?.()
    stopAutosave()
    savePosition(true)
    $('#reader').hidden = true
    $('#r-panel').hidden = true
    $('#r-chaplist').hidden = true
    $('#mv').destroy?.()
    state.book = null
    document.body.style.overflow = ''
    refreshLibrary()
}

/* Reading position is written on a debounce as you scroll, but a crash or a
 * hard quit could still lose the last stretch. A 30-second heartbeat and a
 * flush on exit close that gap. Both are silent: no toast, because saving is
 * not news. */
let autosaveTimer = null

function startAutosave() {
    stopAutosave()
    autosaveTimer = setInterval(() => {
        if (!state.book || $('#reader').hidden) return
        savePosition(true, { quiet: true })
    }, 30000)
}

function stopAutosave() {
    if (autosaveTimer) clearInterval(autosaveTimer)
    autosaveTimer = null
}

function flushPosition() {
    // pagehide fires when the window really goes away; the callback must not
    // await anything, so this fires and forgets.
    if (state.book && !$('#reader').hidden) savePosition(true, { quiet: true })
}

function savePosition(now = false, { quiet = false } = {}) {
    const mv = $('#mv'), book = state.book
    if (!book || state.settings.reader_keep_position === false) return
    const send = () => call('reader_save_position', book.path, mv.index,
                            mv.fraction, mv.length, mv.mode, book.title)
    clearTimeout(state.saveTimer)
    if (now) send(); else state.saveTimer = setTimeout(send, 800)
}

async function loadChapters() {
    if (!state.book) return
    const dir = state.book.kind === 'pages'
        ? state.book.path.replace(/[\\/][^\\/]+$/, '')
        : ''
    const res = await call('reader_chapters', '', dir)
    state.chapters = res?.chapters || []
    $('#chap-items').innerHTML = state.chapters.map(c => `
        <div class="chap ${c.path === state.book.path ? 'on' : ''}" data-open="${esc(c.path)}">
          ${esc(c.label)}
          <span class="cs">${c.pages} pages${c.position ? ` · ${Math.round((c.position.fraction || 0) * 100)}%` : ''}</span>
        </div>`).join('') || '<p class="empty">No sibling chapters.</p>'
}

async function loadMarks() {
    if (!state.book) return
    const res = await call('reader_annotations', state.book.path)
    state.marks = res?.annotations?.bookmarks || []
    $('#r-marks').innerHTML = state.marks.map(m => `
        <div class="mark" data-goto="${m.index}">
          <span>${esc(m.label || `Page ${m.index + 1}`)}</span>
          <button data-del="${esc(m.id)}" title="Remove">×</button>
        </div>`).join('') || '<p class="empty" style="font-size:12px">No bookmarks yet.</p>'
}

/* ── find in book (EPUB/PDF text) ─────────────────────────────────────── */

async function findInBook(query) {
    const box = $('#r-find-results')
    if (!query || query.length < 2) { box.innerHTML = ''; return }
    const mv = $('#mv')
    if (!mv.book?.sections || state.book?.kind === 'pages') {
        box.innerHTML = '<p class="empty" style="font-size:12px">Image chapters have no text to search. Use the Search tab to find a series.</p>'
        return
    }
    box.innerHTML = '<p class="empty" style="font-size:12px">Searching…</p>'
    try {
        const { searchMatcher } = await import('../foliate/search.js')
        const { textWalker } = await import('../foliate/text-walker.js')
        const matcher = searchMatcher(textWalker, { defaultLocale: 'en' })
        const hits = []
        for (const [index, section] of mv.book.sections.entries()) {
            if (!section.createDocument) continue
            const doc = await section.createDocument()
            for (const { excerpt } of matcher(doc, query)) {
                hits.push({ index, excerpt })
                if (hits.length >= 40) break
            }
            if (hits.length >= 40) break
        }
        box.innerHTML = hits.length
            ? hits.map(h => `<div class="find-hit" data-goto="${h.index}">${esc(h.excerpt?.pre || '')}<b>${esc(h.excerpt?.match || '')}</b>${esc(h.excerpt?.post || '')}</div>`).join('')
            : '<p class="empty" style="font-size:12px">No matches.</p>'
    } catch (e) {
        box.innerHTML = `<p class="empty" style="font-size:12px">Search unavailable: ${esc(e.message)}</p>`
    }
}

/* ── helpers ──────────────────────────────────────────────────────────── */

function esc(value) {
    return String(value ?? '').replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}

let toastTimer = null
function toast(message) {
    const el = $('#r-toast')
    el.textContent = message
    el.hidden = false
    clearTimeout(toastTimer)
    toastTimer = setTimeout(() => { el.hidden = true }, 2400)
}

/* ── wiring ───────────────────────────────────────────────────────────── */

function wire() {
    $$('.rail-btn[data-view]').forEach(b =>
        b.addEventListener('click', () => showView(b.dataset.view)))

    // The rail's Theme button is gone -- it duplicated Settings › Appearance.
    // The behaviour stays, reachable from the T shortcut.
    $('#theme-cycle')?.addEventListener('click', cycleTheme)

    $('#lib-filter').addEventListener('input', renderLibrary)
    $('#lib-refresh').addEventListener('click', refreshLibrary)
    $('#lib-scan-header-btn')?.addEventListener('click', async () => {
        const btn = $('#lib-scan-header-btn')
        if (btn) { btn.disabled = true; btn.innerHTML = '<span class="mi">sync</span>Scanning…' }
        const res = await call('scan_library_folders')
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="mi">sync</span>Scan Folders' }
        const found = res?.discovered ?? 0
        const total = res?.total_series ?? 0
        toast(`Library scanned: ${total} series indexed (${found} new)`)
        await refreshLibrary()
        await refreshLibraryFolders()
    })

    $('#search-layout-btn')?.addEventListener('click', () => {
        const next = searchLayout === 'grid' ? 'list' : 'grid'
        updateSearchLayout(next)
        pushSettings({ search_layout: next })
        toast(`Search view: ${next === 'list' ? 'List' : 'Grid'}`)
    })

    $('#search-go').addEventListener('click', () => doSearch(false))
    $('#search-input').addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault()
            doSearch(false)
        }
    })
    $('#search-input').addEventListener('input', e => {
        const val = e.target.value.trim()
        const heroBox = $('#search-hero')
        if (val.length > 0) {
            heroBox?.classList.add('query-active')
            searchWave?.setOpacity(0)
        } else {
            heroBox?.classList.remove('query-active')
            searchWave?.setOpacity(1)
        }
    })
    $('#queue-clear').addEventListener('click', async () => { await call('queue_clear'); refreshQueue() })
    $('#queue-pause').addEventListener('click', async () => {
        const r = await call('set_queue_paused', true); toast(r?.ok ? 'Queue paused' : 'Could not pause'); refreshQueue()
    })
    $('#btn-cart-download-all')?.addEventListener('click', async () => {
        toast('Starting all downloads in cart…')
        await call('set_queue_paused', false)
        refreshQueue()
    })
    $('#btn-cart-clear-all')?.addEventListener('click', async () => {
        await call('queue_clear')
        toast('Cart cleared')
        refreshQueue()
    })
    $('#d-cart-btn')?.addEventListener('click', async () => {
        await startDetailDownload(true)
        toast('Added series to Cart for bulk download')
    })

    // ── custom card context menu (Library & Marks) ──
    let activeContextManga = null
    const contextMenu = $('#card-context-menu')

    const closeContextMenu = () => {
        if (contextMenu) contextMenu.hidden = true
        activeContextManga = null
    }

    document.addEventListener('contextmenu', e => {
        const card = e.target.closest('#library-grid .card, #marks-grid .card')
        if (!card || !contextMenu) return
        e.preventDefault()
        activeContextManga = {
            key: card.dataset.key || card.dataset.manga || card.dataset.directory || '',
            url: card.dataset.manga || '',
            directory: card.dataset.directory || '',
            openPath: card.dataset.open || '',
            source: card.dataset.source || '',
            title: card.dataset.title || card.querySelector('.name')?.textContent || 'Manga',
            cardEl: card,
        }
        $('#cmenu-title').textContent = activeContextManga.title
        
        const x = Math.min(e.clientX, window.innerWidth - 270)
        const y = Math.min(e.clientY, window.innerHeight - 340)
        contextMenu.style.left = `${Math.max(10, x)}px`
        contextMenu.style.top = `${Math.max(10, y)}px`
        contextMenu.hidden = false
    })

    document.addEventListener('click', e => {
        if (!e.target.closest('#card-context-menu')) closeContextMenu()
    })
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeContextMenu()
    })

    $('#cmenu-read')?.addEventListener('click', async () => {
        const item = activeContextManga
        closeContextMenu()
        if (!item) return
        if (item.openPath) { openPath(item.openPath); return }
        const lib = await call('get_library_entry', item.url)
        const entry = lib?.entry || lib
        const first = (entry?.items || [])[0]
        if (first?.path) openPath(first.path)
        else openDetail(item.url, item.source)
    })

    $('#cmenu-info')?.addEventListener('click', () => {
        const item = activeContextManga
        closeContextMenu()
        if (item?.url) openDetail(item.url, item.source)
    })

    $('#cmenu-folder')?.addEventListener('click', async () => {
        const item = activeContextManga
        closeContextMenu()
        if (!item) return
        const lib = await call('get_library_entry', item.url)
        const dir = lib?.entry?.directory || lib?.directory
        if (dir) call('open_folder', dir)
        else toast('Folder path not found')
    })

    $('#cmenu-colors')?.addEventListener('click', async e => {
        const btn = e.target.closest('[data-color]')
        if (!btn || !activeContextManga) return
        const color = btn.dataset.color || ''
        const item = activeContextManga
        closeContextMenu()
        await call('set_book_color', item.url, color)
        if (item.cardEl) {
            if (color) {
                item.cardEl.setAttribute('data-card-color', color)
                item.cardEl.style.setProperty('--card-color', color)
            } else {
                item.cardEl.removeAttribute('data-card-color')
                item.cardEl.style.removeProperty('--card-color')
            }
        }
        toast(color ? 'Color tag set' : 'Color tag cleared')
    })

    $('#cmenu-sync-meta')?.addEventListener('click', async () => {
        closeContextMenu()
        const res = await call('rebuild_library_metadata')
        toast(`Metadata synced for ${res?.total_series || 0} series`)
        await refreshLibrary()
    })

    $('#cmenu-del-meta')?.addEventListener('click', async () => {
        const item = activeContextManga
        closeContextMenu()
        if (!item) return
        const key = item.key || item.url || item.directory || item.openPath
        if (!key && !item.title) return
        libraryCache = libraryCache.filter(b => b.url !== key && b.key !== key && b.directory !== key && b.title !== item.title)
        renderLibrary()
        await call('delete_library_entry', key, false)
        toast(`Removed "${item.title}" from library records`)
        await refreshLibrary()
    })

    $('#cmenu-del-all')?.addEventListener('click', async () => {
        const item = activeContextManga
        closeContextMenu()
        if (!item) return
        const key = item.key || item.url || item.directory || item.openPath
        if (!key && !item.title) return
        if (!confirm(`Are you sure you want to permanently delete "${item.title}" and all its files from disk?`)) return
        libraryCache = libraryCache.filter(b => b.url !== key && b.key !== key && b.directory !== key && b.title !== item.title)
        renderLibrary()
        await call('delete_library_entry', key, true)
        toast(`Deleted "${item.title}" and files from disk`)
        await refreshLibrary()
    })

    // open anything with data-open, anywhere
    document.addEventListener('click', e => {
        // The info button sits *inside* a card that carries data-open, so the
        // more specific target has to win -- otherwise closest() walks up to
        // the card and opens the reader instead of the series page.
        const manga = e.target.closest('[data-manga]')
        const opener = e.target.closest('[data-open]')
        if (manga && (!opener || manga.contains(opener) === false)) {
            openDetail(manga.dataset.manga, manga.dataset.source)
            return
        }
        if (opener) { openPath(opener.dataset.open); $('#r-chaplist').hidden = true; return }
        const goto = e.target.closest('[data-goto]')
        if (goto) { $('#mv').goTo(Number(goto.dataset.goto)); return }
        const del = e.target.closest('[data-del]')
        if (del) {
            e.stopPropagation()
            call('reader_delete_annotation', state.book?.path, 'bookmark', del.dataset.del).then(loadMarks)
        }
    })

    // reader chrome
    $('#r-close').addEventListener('click', closeReader)
    $('#r-settings').addEventListener('click', () => {
        $('#r-panel').hidden = !$('#r-panel').hidden
        $('#r-chaplist').hidden = true
    })
    $('#r-chapters').addEventListener('click', () => {
        $('#r-chaplist').hidden = !$('#r-chaplist').hidden
        $('#r-panel').hidden = true
    })
    $('#r-fullscreen').addEventListener('click', toggleFullscreen)
    $('#r-bookmark').addEventListener('click', async () => {
        if (!state.book) return
        const mv = $('#mv')
        await togglePageMark(mv.index)
        $('#r-bookmark').classList.toggle('on', pages.marks.has(mv.index))
        toast(pages.marks.has(mv.index) ? 'Bookmarked' : 'Bookmark removed')
    })
    $('#r-prev-ch').addEventListener('click', () => hopChapter('reader_open_previous'))
    $('#r-next-ch').addEventListener('click', () => hopChapter('reader_open_next'))

    $('#r-slider').addEventListener('input', e => {
        $('#mv').setFraction(Number(e.target.value) / 100)
    })

    $$('#mode-seg button').forEach(b => b.addEventListener('click', () => {
        $('#mv').setAttribute('mode', b.dataset.mode)
        pushSettings({ reader_mode: b.dataset.mode })
        $$('#mode-seg button').forEach(x => x.classList.toggle('on', x === b))
    }))
    $('#r-fit').addEventListener('change', e => {
        $('#mv').setAttribute('fit', e.target.value); pushSettings({ reader_fit: e.target.value })
    })
    $('#r-filter').addEventListener('change', e => applyFilter(e.target.value))
    $('#r-theme').addEventListener('change', e => setTheme(e.target.value))
    // These four went through raw addEventListener and so never repainted
    // their track: dragging zoom to 250 left --fill stuck at the value it had
    // when the panel was built. bindSlider owns the fill, the value chip and
    // the save, so every slider in the app behaves the same way.
    bindSlider('#r-width', 'reader_max_width', {
        value: raw => `${raw}%`,
        label: raw => `${raw}%`,
        apply: raw => $('#mv').setAttribute('max-width', `${raw}%`),
    })
    bindSlider('#r-gap', 'reader_gap', {
        label: raw => `${raw}px`,
        apply: raw => $('#mv').setAttribute('gap', raw),
    })
    $('#r-spread').addEventListener('change', e => {
        const mv = $('#mv')
        if (e.target.checked) mv.setAttribute('spread', ''); else mv.removeAttribute('spread')
        pushSettings({ reader_spread: e.target.checked })
    })
    bindSlider('#r-zoom', 'reader_zoom', {
        value: raw => Number(raw) / 100,
        label: raw => `${raw}%`,
        apply: raw => $('#mv').setAttribute('zoom', String(Number(raw) / 100)),
    })
    // auto-scroll
    const autoToggle = () => {
        const mv = $('#mv')
        if (mv.autoScrolling) { mv.stopAutoScroll(); return }
        if (mv.paged) return toast('Auto-scroll needs a continuous mode (W to switch)')
        mv.startAutoScroll(state.settings.reader_autoscroll_speed || 60)
    }
    $('#r-auto').addEventListener('click', autoToggle)
    $('#r-auto-top').addEventListener('click', autoToggle)
    bindSlider('#r-auto-speed', 'reader_autoscroll_speed', {
        label: raw => `${raw} px/s`,
        apply: raw => $('#mv').setAutoScrollSpeed(Number(raw)),
    })
    bindSlider('#set-auto-speed', 'reader_autoscroll_speed', {
        label: raw => `${raw} px/s`,
    })

    // shortcuts sheet
    const showShortcuts = show => { $('#r-shortcuts').hidden = !show }
    $('#r-help').addEventListener('click', () => showShortcuts(true))
    $('#r-shortcuts-close').addEventListener('click', () => showShortcuts(false))
    $('#r-shortcuts').addEventListener('click', e => {
        if (e.target.id === 'r-shortcuts') showShortcuts(false)
    })

    let findTimer = null
    $('#r-find').addEventListener('input', e => {
        clearTimeout(findTimer)
        const q = e.target.value
        findTimer = setTimeout(() => findInBook(q), 300)
    })

    // ---- settings: collapse toggle
    let allSettingsCollapsed = false
    $('#settings-collapse-toggle')?.addEventListener('click', () => {
        allSettingsCollapsed = !allSettingsCollapsed
        for (const g of $$('.view[data-view="settings"] .set-group')) {
            g.open = !allSettingsCollapsed
        }
        const btn = $('#settings-collapse-toggle')
        if (btn) {
            btn.innerHTML = allSettingsCollapsed
                ? '<span class="mi">unfold_more</span>Expand all'
                : '<span class="mi">unfold_less</span>Collapse all'
        }
    })

    // ---- settings: quick navigation tabs
    $('#settings-nav-tabs')?.addEventListener('click', e => {
        const tab = e.target.closest('.tab')
        if (!tab) return
        const targetId = tab.dataset.setTarget
        for (const other of $$('#settings-nav-tabs .tab')) {
            other.classList.toggle('on', other === tab)
        }
        if (targetId === 'all') {
            for (const g of $$('.view[data-view="settings"] .set-group')) g.open = true
            return
        }
        const targetGroup = $(`#${targetId}`)
        if (targetGroup) {
            targetGroup.open = true
            targetGroup.scrollIntoView({ behavior: 'smooth', block: 'start' })
        }
    })
    $('#r-panel-collapse')?.addEventListener('click', () => {
        $('#r-panel').hidden = true
        $('#r-settings')?.classList.remove('on')
    })

    // ---- settings: appearance
    $('#set-corners').addEventListener('change', e => setCorners(e.target.checked))
    // The frame is chosen when pywebview creates the window, so this cannot
    // apply live -- say so rather than let it look broken.
    $('#set-titlebar')?.addEventListener('change', e => {
        pushSettings({ custom_titlebar: e.target.checked })
        toast(e.target.checked
            ? 'Custom titlebar on — restart Mangasurf to see it'
            : 'Native window frame — restart Mangasurf to see it')
    })
    $('#set-matrix').addEventListener('change', e => setMatrix(e.target.checked))
    $('#set-animations').addEventListener('change', e => setAnimations(e.target.checked))
    bindSlider('#set-columns', null, {
        label: raw => (Number(raw) === 0 ? 'Auto' : String(raw)),
        apply: raw => setColumns(raw),
    })

    $('#set-layout-padding')?.addEventListener('change', e => {
        document.documentElement.setAttribute('data-padding', e.target.value || 'normal')
        pushSettings({ layout_padding: e.target.value })
        toast(`Margins set to ${e.target.value}`)
    })

    $('#set-layout-density')?.addEventListener('change', e => {
        document.documentElement.setAttribute('data-density', e.target.value || 'comfortable')
        pushSettings({ layout_density: e.target.value })
        toast(`Density set to ${e.target.value}`)
    })

    $('#set-search-wave')?.addEventListener('change', e => {
        const on = e.target.checked
        pushSettings({ search_wave_enabled: on })
        if (on) {
            searchWave?.start()
            searchWave?.setOpacity(1)
        } else {
            searchWave?.setOpacity(0)
            searchWave?.stop()
        }
    })

    $('#r-theme').addEventListener('change', e => setTheme(e.target.value))
    $('#r-accent').addEventListener('change', e => setAccent(e.target.value))
    $('#r-corners').addEventListener('change', e => setCorners(e.target.checked))

    // ---- settings: reading
    $('#set-mode').addEventListener('change', e => pushSettings({ reader_mode: e.target.value }))
    $('#set-fit').addEventListener('change', e => pushSettings({ reader_fit: e.target.value }))
    $('#set-filter').addEventListener('change', e => applyFilter(e.target.value))
    bindSlider('#set-width', 'reader_max_width', {
        value: raw => `${raw}%`, label: raw => `${raw}%`,
    })
    bindSlider('#set-gap', 'reader_gap', { label: raw => `${raw}px` })
    bindSlider('#set-preload', 'reader_preload')
    bindSlider('#set-bundle', 'bundle', {
        label: raw => (Number(raw) === 0 ? 'One per chapter' : String(raw)),
    })
    $('#set-spread').addEventListener('change', e => pushSettings({ reader_spread: e.target.checked }))
    $('#set-keep').addEventListener('change', e => pushSettings({ reader_keep_position: e.target.checked }))
    $('#set-tap').addEventListener('change', e => {
        pushSettings({ reader_tap_zones: e.target.checked })
        $('#tapzones').hidden = !e.target.checked
    })

    $('#set-reader-animate').addEventListener('change', e => pushSettings({ reader_animate: e.target.checked }))
    $('#set-fullscreen-default').addEventListener('change', e =>
        pushSettings({ reader_fullscreen_default: e.target.checked }))
    $('#set-reader-path').addEventListener('change', e => pushSettings({ reader_path: e.target.value }))
    $('#set-reader-browse').addEventListener('click', async () => {
        const res = await call('choose_file')
        const path = res?.path || res?.file
        if (path) { $('#set-reader-path').value = path; pushSettings({ reader_path: path }) }
    })

    // ---- settings: sources
    $('#sources-reset').addEventListener('click', async () => {
        const res = await call('reset_source_config')
        const updated = res?.sources || (await call('get_source_config'))?.sources || []
        renderSourceRanks(updated)
        fillSources()
        toast('Source order reset')
    })
    $('#set-dedupe').addEventListener('change', e => pushSettings({ dedupe_results: e.target.checked }))
    $('#set-interleave').addEventListener('change', e => pushSettings({ interleave_results: e.target.checked }))
    $('#set-downloaded').addEventListener('change', e => pushSettings({ downloaded_results: e.target.value }))
    $('#set-default-source').addEventListener('change', e => {
        pushSettings({ default_source: e.target.value })
        toast(`Default source set to ${e.target.value}`)
    })
    $('#set-language').addEventListener('change', e => pushSettings({ language: e.target.value }))
    $('#set-scanlator').addEventListener('change', e => pushSettings({ scanlator: e.target.value }))
    $('#set-interleave-browse').addEventListener('change', e =>
        pushSettings({ interleave_browse: e.target.checked }))
    $('#set-data-saver').addEventListener('change', e => pushSettings({ data_saver: e.target.checked }))

    // ---- settings: downloads
    $('#set-output').addEventListener('change', e => pushSettings({ output_dir: e.target.value }))
    $('#set-output-browse').addEventListener('click', async () => {
        const res = await call('choose_folder')
        const dir = res?.path || res?.folder
        if (dir) { $('#set-output').value = dir; pushSettings({ output_dir: dir }) }
    })
    for (const btn of $$('#set-format button'))
        btn.addEventListener('click', () => {
            for (const other of $$('#set-format button')) other.classList.toggle('on', other === btn)
            pushSettings({ format: btn.dataset.format })
        })
    $('#set-name-single').addEventListener('change', e => pushSettings({ name_single: e.target.value }))
    $('#set-name-chapter').addEventListener('change', e => pushSettings({ name_chapter: e.target.value }))
    $('#set-name-range').addEventListener('change', e => pushSettings({ name_range: e.target.value }))
    $('#set-keep-images').addEventListener('change', e => pushSettings({ keep_images: e.target.checked }))
    $('#set-open-done').addEventListener('change', e => pushSettings({ open_folder_when_done: e.target.checked }))
    $('#set-confirm-large').addEventListener('change', e => pushSettings({ confirm_large: e.target.checked }))
    $('#set-large-threshold').addEventListener('change', e =>
        pushSettings({ large_threshold: Number(e.target.value) || 100 }))

    // ---- settings: performance
    bindSlider('#set-max-jobs', 'max_concurrent_jobs')
    bindSlider('#set-chapter-workers', 'chapter_workers')
    bindSlider('#set-image-workers', 'image_workers')
    bindSlider('#set-retries', 'retries')
    bindSlider('#set-delay', 'delay', {
        value: raw => Number(raw) / 10,
        label: raw => `${(Number(raw) / 10).toFixed(1)}s`,
    })

    // ---- settings: lock
    $('#set-lock-enabled').addEventListener('change', async e => {
        const isChecked = e.target.checked
        if (!isChecked) {
            await call('lock_disable')
            toast('Password lock turned off')
            $('#lock-fields').hidden = true
            $('#lock-actions').hidden = true
            await refreshLock()
        } else {
            $('#lock-fields').hidden = false
            $('#lock-actions').hidden = false
            const stateEl = $('#lock-state')
            if (stateEl) stateEl.textContent = 'Enter password below and click Set password'
            $('#set-lock-pass')?.focus()
        }
    })
    $('#lock-save').addEventListener('click', async () => {
        const password = $('#set-lock-pass').value
        if (!password || password.length < 4) return toast('Use at least 4 characters')
        const res = await call('lock_set', password, $('#set-lock-hint').value)
        toast(res?.ok ? 'Password set' : (res?.error || 'Could not set the password'))
        $('#set-lock-pass').value = ''
        await refreshLock()
    })
    $('#set-lock-start').addEventListener('change', e =>
        call('lock_options', { lock_on_start: e.target.checked }))
    $('#set-blur-covers').addEventListener('change', e =>
        call('lock_options', { blur_covers: e.target.checked }))
    $('#set-safe-mode').addEventListener('change', e =>
        call('lock_options', { safe_mode: e.target.checked }))
    $('#lock-unlock').addEventListener('click', tryUnlock)
    $('#lock-input').addEventListener('keydown', e => { if (e.key === 'Enter') tryUnlock() })

    // ---- settings: servers & opds hub
    wireServersHub()

    // ---- settings: library & folders & database
    $('#lib-page-prev')?.addEventListener('click', () => {
        currentLibPage -= 1
        renderLibrary()
    })
    $('#lib-page-next')?.addEventListener('click', () => {
        currentLibPage += 1
        renderLibrary()
    })
    $('#lib-page-numbers')?.addEventListener('click', e => {
        const btn = e.target.closest('.lib-page-btn')
        if (!btn) return
        const p = Number(btn.dataset.page)
        if (p) {
            currentLibPage = p
            renderLibrary()
        }
    })
    $('#set-lib-paginate')?.addEventListener('change', e => {
        pushSettings({ lib_paginate: e.target.checked })
        currentLibPage = 1
        renderLibrary()
    })
    $('#set-lib-page-size')?.addEventListener('change', e => {
        pushSettings({ lib_page_size: Number(e.target.value) })
        currentLibPage = 1
        renderLibrary()
    })

    $('#set-lib-display-mode')?.addEventListener('change', e => {
        pushSettings({ lib_display_mode: e.target.value })
        renderLibrary()
    })
    $('#set-db-enabled')?.addEventListener('change', e =>
        pushSettings({ db_enabled: e.target.checked }))
    $('#set-db-sfw-enabled')?.addEventListener('change', e =>
        pushSettings({ db_sfw_enabled: e.target.checked }))
    $('#set-db-nsfw-enabled')?.addEventListener('change', e =>
        pushSettings({ db_nsfw_enabled: e.target.checked }))

    // FlareSolverr Controls
    const updateFlareSolverrStatus = async () => {
        try {
            const res = await call('flaresolverr_status')
            const badge = $('#flaresolverr-status-badge')
            if (badge) {
                const isConn = res?.status === 'connected'
                badge.className = `srv-pill ${isConn ? 'online' : 'offline'}`
                const txt = badge.querySelector('.status-txt')
                if (txt) txt.textContent = isConn ? `Connected (${res.version || 'v3'})` : 'Offline'
            }
        } catch (e) {
            console.debug('FlareSolverr status check failed:', e)
        }
    }

    $('#btn-flaresolverr-test')?.addEventListener('click', async () => {
        const url = ($('#set-flaresolverr-url')?.value || '').trim()
        toast('Testing FlareSolverr connection…')
        const res = await call('flaresolverr_test', url)
        toast(res?.message || (res?.ok ? 'Connected' : 'Offline'))
        await updateFlareSolverrStatus()
    })

    $('#btn-flaresolverr-toggle')?.addEventListener('click', async () => {
        await updateFlareSolverrStatus()
        toast('FlareSolverr status refreshed')
    })

    $('#set-flaresolverr-url')?.addEventListener('change', e => {
        call('set_flaresolverr_config', { url: e.target.value })
    })

    // Password / Token reveal toggle & copy
    $('#btn-toggle-token-reveal')?.addEventListener('click', () => {
        const input = $('#set-server-token')
        const icon = $('#token-reveal-icon')
        if (input && icon) {
            const isPass = input.type === 'password'
            input.type = isPass ? 'text' : 'password'
            icon.textContent = isPass ? 'visibility_off' : 'visibility'
        }
    })

    $('#btn-copy-token-main')?.addEventListener('click', () => {
        const val = $('#set-server-token')?.value
        if (val) {
            navigator.clipboard.writeText(val)
            toast('Access Token / Password copied to clipboard')
        }
    })

    $('#lib-scan-now-btn')?.addEventListener('click', async () => {
        const btn = $('#lib-scan-now-btn')
        if (btn) { btn.disabled = true; btn.innerHTML = '<span class="mi">sync</span>Scanning…' }
        const res = await call('scan_library_folders')
        if (btn) { btn.disabled = false; btn.innerHTML = '<span class="mi">sync</span>Scan Folders Now' }
        const found = res?.discovered ?? 0
        const total = res?.total_series ?? 0
        const statusEl = $('#lib-scan-status')
        if (statusEl) statusEl.textContent = `Scanned ${res?.folders?.length || 1} folders: ${total} series indexed (${found} new)`
        toast(`Library scan complete: ${total} series (${found} new)`)
        await refreshLibrary()
        await refreshLibraryFolders()
    })

    $('#lib-add-folder-browse')?.addEventListener('click', async () => {
        const res = await call('choose_folder')
        const dir = res?.path || res?.folder
        if (dir) {
            const input = $('#lib-add-folder-input')
            if (input) input.value = dir
        }
    })

    const handleAddFolder = async () => {
        const input = $('#lib-add-folder-input')
        const path = (input?.value || '').trim()
        if (!path) return toast('Please enter a folder path')
        const res = await call('add_library_folder', path)
        if (res?.ok === false) return toast(res.error || 'Failed to add folder')
        if (input) input.value = ''
        toast(`Added folder: ${res.discovered || 0} series discovered`)
        await refreshLibrary()
        await refreshLibraryFolders()
    }

    $('#lib-add-folder-btn')?.addEventListener('click', handleAddFolder)
    $('#lib-add-folder-input')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
            e.preventDefault()
            handleAddFolder()
        }
    })

    $('#lib-folders-list')?.addEventListener('click', async e => {
        const scanBtn = e.target.closest('[data-scan-folder]')
        if (scanBtn) {
            const folderPath = scanBtn.dataset.scanFolder
            scanBtn.disabled = true
            const res = await call('scan_library_folders', [folderPath])
            scanBtn.disabled = false
            toast(`Rescanned folder: ${res?.total_series || 0} series indexed`)
            await refreshLibrary()
            await refreshLibraryFolders()
            return
        }

        const removeBtn = e.target.closest('[data-remove-folder]')
        if (removeBtn) {
            const folderPath = removeBtn.dataset.removeFolder
            await call('remove_library_folder', folderPath)
            toast('Monitored folder removed')
            await refreshLibraryFolders()
            await refreshLibrary()
            return
        }
    })

    $('#set-lib-autoscan')?.addEventListener('change', e =>
        pushSettings({ lib_autoscan: e.target.checked }))
    $('#set-lib-autodiscover')?.addEventListener('change', e =>
        pushSettings({ lib_autodiscover: e.target.checked }))

    // ---- queue
    $('#q-explore-btn')?.addEventListener('click', () => showView('search'))
    $('#q-lib-btn')?.addEventListener('click', () => showView('library'))

    // ---- stats
    $('#stats-tabs').addEventListener('click', e => {
        const tab = e.target.closest('.tab')
        if (tab) showTab($('#stats-tabs'), tab.dataset.tab)
    })
    $('#stats-range').addEventListener('change', refreshStats)
    $('#stats-reset').addEventListener('click', async () => {
        await call('reset_stats')
        refreshStats()
        toast('Statistics reset')
    })

    // ---- settings: background
    $('#set-tray').addEventListener('change', e => pushSettings({ minimize_to_tray: e.target.checked }))
    $('#set-tray-notify').addEventListener('change', e => pushSettings({ tray_notifications: e.target.checked }))
    $('#set-log-advanced').addEventListener('change', e => pushSettings({ queue_log_advanced: e.target.checked }))
    $('#set-advanced').addEventListener('change', e => pushSettings({ advanced_info: e.target.checked }))
    $('#set-confirm-delete').addEventListener('change', e => pushSettings({ confirm_delete: e.target.checked }))
    $('#set-auto-snapshot').addEventListener('change', e => pushSettings({ auto_snapshot: e.target.checked }))

    // manga-view events
    const mv = $('#mv')
    mv.addEventListener('relocate', e => {
        const { index, total, fraction } = e.detail
        $('#r-count').textContent = `${index + 1} / ${total}`
        const slider = $('#r-slider')
        if (document.activeElement !== slider) slider.value = String(Math.round(fraction * 100))
        if (!$('#r-pagelist').hidden) renderPages()
        savePosition()
    })
    mv.addEventListener('end', e => {
        if (e.detail.edge === 'end') toast('End of chapter — → for the next one')
    })
    mv.addEventListener('page-error', e => toast(`Page ${e.detail.index + 1} failed to load`))
    mv.addEventListener('autoscroll', e => {
        const running = !!e.detail.running
        $('#r-auto').textContent = running ? 'Stop' : 'Start'
        $('#r-auto-top').classList.toggle('on', running)
        if (running) toast(`Auto-scroll ${e.detail.speed} px/s`)
    })

    // Tap zones.
    //
    // Listening on #tapzones itself no longer works: that layer is
    // `pointer-events: none` so the wheel reaches the page strip underneath,
    // and an inert element receives no clicks either. So the click is caught
    // on the reader and the zone worked out from where the pointer is, which
    // is what the overlay was really encoding anyway.
    $('#reader').addEventListener('click', e => {
        if (state.settings.reader_tap_zones === false) return
        if ($('#tapzones').hidden) return
        // Ignore clicks on the chrome: toolbars, drawers and the sheets.
        if (e.target.closest('#r-top, #r-bottom, #r-panel, #r-chaplist, #r-toast')) return

        const bounds = $('#reader').getBoundingClientRect()
        const third = bounds.width / 3
        const x = e.clientX - bounds.left
        if (x < third) $('#mv').goLeft()
        else if (x > bounds.width - third) $('#mv').goRight()
        else {
            // A centre tap toggles the toolbars. In minimalist mode they are
            // already hidden, so toggling `immersive` on top of it only
            // resized the open sidebar -- the reported "sidebar gets smaller
            // even when the bars are still hidden". Leave it alone there.
            if (!$('#reader').classList.contains('zen'))
                $('#reader').classList.toggle('immersive')
        }
    })

    // keyboard
    document.addEventListener('keydown', e => {
        // The settings page is capturing a new binding: swallow the keystroke
        // so rebinding "f" does not also toggle fullscreen behind the dialog.
        if (keymap.capturing) {
            e.preventDefault()
            if (keymap.finishCapture(e)) { renderKeysTable(); keymap.save() }
            return
        }
        if (!$('#detail').hidden && e.key === 'Escape') { closeDetail(); return }
        if ($('#reader').hidden) return
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')
        if (typing && e.key !== 'Escape') return
        if (keymap.handle(e)) return
    })
}

/* ── shortcuts ────────────────────────────────────────────────────────── */

const keymap = createKeymap({ call, esc, toast })

/** Point every action id at the thing it does. One place, so the settings
 *  page can list an action without also knowing how to perform it. */
function bindActions() {
    const mv = () => $('#mv')
    keymap
        .on('close', () => {
            if (!$('#r-shortcuts').hidden) { $('#r-shortcuts').hidden = true; return }
            closeReader()
        })
        .on('pageLeft', () => mv().goLeft())
        .on('pageRight', () => mv().goRight())
        .on('next', e => { mv().next(); e?.preventDefault() })
        .on('prev', () => mv().prev())
        .on('first', () => mv().goTo(0))
        .on('last', () => mv().goTo(mv().length - 1))
        .on('prevChapter', () => hopChapter('reader_open_previous'))
        .on('nextChapter', () => hopChapter('reader_open_next'))
        .on('jumpPage', () => {
            const total = mv().length || 0
            const answer = prompt(`Jump to page (1–${total})`)
            const n = Number(answer)
            if (Number.isFinite(n) && n >= 1 && n <= total) mv().goTo(n - 1)
        })
        .on('bookmark', () => $('#r-bookmark')?.click())
        .on('markedTab', () => {
            $('#r-pages')?.click()
            $('#pl-tab-marked')?.click()
        })
        .on('pages', () => $('#r-pages')?.click())
        .on('chapters', () => $('#r-chapters')?.click())
        .on('shortcuts', () => {
            const sheet = $('#r-shortcuts')
            sheet.hidden = !sheet.hidden
            if (!sheet.hidden) renderShortcutSheet()
        })
        .on('mode', () => cycleMode())
        .on('fullscreen', () => toggleFullscreen())
        .on('immersive', () => $('#reader').classList.toggle('immersive'))
        .on('zen', () => setZen(!$('#reader').classList.contains('zen')))
        .on('theme', () => cycleTheme())
        .on('zoomIn', e => { e?.preventDefault(); bumpZoom(0.1) })
        .on('zoomOut', e => { e?.preventDefault(); bumpZoom(-0.1) })
        .on('zoomReset', e => { e?.preventDefault(); setZoom(1) })
        .on('autoScroll', () => $('#r-auto')?.click())
        .on('faster', () => bumpAutoSpeed(20))
        .on('slower', () => bumpAutoSpeed(-20))
}

/** The help sheet, generated from the live map rather than hand-written. */
function renderShortcutSheet() {
    const list = $('#r-shortcuts-list')
    if (!list) return
    list.innerHTML = ACTIONS.map(action => {
        const keys = keymap.map[action.id] || []
        if (!keys.length) return ''
        return `<dt>${keys.map(k => `<kbd>${esc(pretty(k))}</kbd>`).join(' ')}</dt>`
             + `<dd>${esc(action.label)}</dd>`
    }).join('')
}

/* ── window titlebar ──────────────────────────────────────────────────── */

/**
 * Wire the app's own titlebar, but only when there is a native window.
 *
 * In a browser -- the LAN server, or a test harness -- `window_state`
 * reports `available: false`, and drawing minimise/maximise/close buttons
 * that silently do nothing would be worse than not drawing them.
 */
async function setupTitlebar() {
    const bar = $('#titlebar')
    if (!bar) return
    const state = await call('window_state')
    if (!state?.available || state.custom_titlebar === false) {
        bar.hidden = true
        document.body.classList.remove('has-titlebar')
        return
    }
    bar.hidden = false
    document.body.classList.add('has-titlebar')
    bar.classList.toggle('maximized', !!state.maximized)

    $('#tb-min')?.addEventListener('click', () => call('window_minimize'))
    $('#tb-max')?.addEventListener('click', async () => {
        const res = await call('window_maximize')
        if (res?.ok) bar.classList.toggle('maximized', !!res.maximized)
    })
    $('#tb-close')?.addEventListener('click', () => call('window_close'))
    // Double-clicking the drag strip maximises, which is the convention on
    // every desktop and the first thing anyone tries.
    bar.querySelector('.tb-drag')?.addEventListener('dblclick', () => {
        $('#tb-max')?.click()
    })
}

/** Step to the next theme. Bound to T; also used to be the rail button. */
function cycleTheme() {
    const order = THEME_ORDER
    const i = order.indexOf(document.documentElement.dataset.theme || 'midnight')
    const next = order[(i + 1) % order.length]
    setTheme(next)
    toast(`Theme: ${THEMES[next]?.label || next}`)
}

/** The preset row. Highlights whichever layout the current map matches. */
function renderKeyPresets() {
    const box = $('#keys-presets')
    if (!box) return
    const active = keymap.matchingPreset()
    box.innerHTML = PRESET_ORDER.map(name => `
        <button class="preset-chip${active === name ? ' on' : ''}" role="radio"
                aria-checked="${active === name}" data-preset="${esc(name)}"
        >${esc(PRESETS[name].label)}</button>`).join('')
        + (active ? '' : '<span class="preset-custom">Custom</span>')
}

/** The rebinding table in Settings. */
function renderKeysTable() {
    const table = $('#keys-table')
    if (!table) return
    const term = ($('#keys-filter')?.value || '').toLowerCase().trim()
    const clashes = new Map()
    for (const { key, actions } of keymap.conflicts())
        for (const id of actions) clashes.set(id, key)

    let group = ''
    let html = ''
    for (const action of ACTIONS) {
        if (term && !action.label.toLowerCase().includes(term)
            && !action.group.toLowerCase().includes(term)) continue
        if (action.group !== group) {
            group = action.group
            html += `<h4 class="keys-group">${esc(group)}</h4>`
        }
        const keys = keymap.map[action.id] || []
        html += `
        <div class="keys-row${clashes.has(action.id) ? ' clash' : ''}">
          <span class="keys-label">${esc(action.label)}</span>
          <span class="keys-caps">${
              keys.length
                  ? keys.map(k => `<kbd>${esc(pretty(k))}</kbd>`).join('')
                  : '<em class="keys-none">unbound</em>'}</span>
          <button class="btn sm" data-rebind="${esc(action.id)}">Change</button>
          <button class="btn icon sm" data-clearkey="${esc(action.id)}"
                  title="Reset to default"><span class="mi">restart_alt</span></button>
        </div>`
    }
    table.innerHTML = html
    renderKeyPresets()

    const warn = $('#keys-conflict')
    if (warn) {
        const list = keymap.conflicts()
        warn.hidden = !list.length
        warn.textContent = list.length
            ? `${list.map(c => pretty(c.key)).join(', ')} ${
                list.length === 1 ? 'is' : 'are'} bound to more than one action.`
            : ''
    }
}

function wireKeysPage() {
    const table = $('#keys-table')
    if (!table) return
    table.addEventListener('click', async e => {
        const rebind = e.target.closest('[data-rebind]')
        if (rebind) {
            const row = rebind.closest('.keys-row')
            row?.classList.add('capturing')
            rebind.textContent = 'Press a key…'
            keymap.capture(rebind.dataset.rebind, () => {
                row?.classList.remove('capturing')
                rebind.textContent = 'Change'
            })
            return
        }
        const clear = e.target.closest('[data-clearkey]')
        if (clear) {
            keymap.reset(clear.dataset.clearkey)
            renderKeysTable()
            await keymap.save()
        }
    })
    $('#keys-presets')?.addEventListener('click', async e => {
        const chip = e.target.closest('[data-preset]')
        if (!chip) return
        keymap.preset(chip.dataset.preset)
        renderKeysTable()
        await keymap.save()
        toast(`Shortcuts: ${PRESETS[chip.dataset.preset].label}`)
    })
    $('#keys-filter')?.addEventListener('input', renderKeysTable)
    $('#keys-reset')?.addEventListener('click', async () => {
        keymap.reset()
        renderKeysTable()
        await keymap.save()
        toast('Shortcuts reset')
    })
    $('#r-shortcuts-edit')?.addEventListener('click', () => {
        $('#r-shortcuts').hidden = true
        showView('settings')
        const group = $('#keys-group')
        if (group) { group.open = true; group.scrollIntoView({ block: 'center' }) }
    })
}

/** Zoom from the keyboard.
 *
 * Drives the existing `#r-zoom` slider rather than setting the attribute
 * directly, so the control, the saved setting and the pixels stay in step --
 * setting the attribute alone left the slider showing the old value.
 */
function setZoom(factor) {
    const slider = $('#r-zoom')
    const percent = Math.max(50, Math.min(300, Math.round(factor * 100)))
    if (slider) {
        slider.value = String(percent)
        slider.dispatchEvent(new Event('input', { bubbles: true }))
        slider.dispatchEvent(new Event('change', { bubbles: true }))
    } else {
        $('#mv')?.setAttribute('zoom', String(percent / 100))
        pushSettings({ reader_zoom: percent / 100 })
    }
    toast(`Zoom ${percent}%`)
    return percent / 100
}

function bumpZoom(delta) {
    const current = Number(state.settings.reader_zoom ?? 1) || 1
    return setZoom(current + delta)
}

function bumpAutoSpeed(delta) {
    const mv = $('#mv')
    const next = Math.max(10, Math.min(400, (mv.autoScrollSpeed || 60) + delta))
    mv.setAutoScrollSpeed(next)
    pushSettings({ reader_autoscroll_speed: next })
    $('#r-auto-speed').value = String(next)
    toast(`Auto-scroll ${next} px/s`)
}

function renderStats(books, recent) {
    const chapters = books.reduce((n, b) => n + (b.chapters || 0), 0)
    const items = books.reduce((n, b) => n + b.items.length, 0)
    const inProgress = recent.filter(r => (r.fraction || 0) > 0.01 && (r.fraction || 0) < 0.99).length
    const finished = recent.filter(r => (r.fraction || 0) >= 0.99).length
    const strip = $('#stats-strip') || $('#stats-totals')
    const tiles = [
        [books.length, books.length === 1 ? 'Series' : 'Series'],
        [chapters, 'Chapters'],
        [items, 'Readable items'],
        [inProgress, 'In progress'],
        [finished, 'Finished'],
    ]
    if (strip) {
        strip.innerHTML = tiles.map(([n, label]) =>
            `<div class="stat"><b>${n}</b><span>${esc(label)}</span></div>`).join('')
        strip.hidden = !books.length
    }
}

function cycleMode() {
    const order = ['webtoon', 'vertical', 'ltr', 'rtl']
    const next = order[(order.indexOf(state.settings.reader_mode || 'webtoon') + 1) % order.length]
    $('#mv').setAttribute('mode', next)
    pushSettings({ reader_mode: next })
    $$('#mode-seg button').forEach(b => b.classList.toggle('on', b.dataset.mode === next))
    toast(`Mode: ${next}`)
}

async function hopChapter(method) {
    if (!state.book) return
    savePosition(true)
    const res = await call(method, state.book.path)
    if (!res?.ok) return toast(res?.error || 'No chapter that way')
    await openPath(res.path)
}

function toggleFullscreen() {
    if (document.fullscreenElement) document.exitFullscreen?.()
    else document.documentElement.requestFullscreen?.().catch(() => toast('Fullscreen refused'))
}

/* ── boot ─────────────────────────────────────────────────────────────── */

async function boot() {
    useBridge = await ready()

    // Icons are ligatures: until Material Symbols arrives the browser paints
    // the literal word ("settings"), so theme.css hides them and this reveals
    // them. It must never block -- a slow font CDN once stalled the old head
    // for over 45 seconds.
    const revealIcons = () => document.documentElement.classList.add('icons-ready')
    if (document.fonts?.load) {
        document.fonts.load('20px "Material Symbols Rounded"')
            .then(revealIcons).catch(revealIcons)
        setTimeout(revealIcons, 2500)       // never leave the UI blank
    } else {
        revealIcons()
    }

    matrix = createMatrix($('#matrix'))
    await loadSettings()

    const s = state.settings
    applyTheme(s.theme || 'midnight')
    applyAccent(s.accent || 'blue')
    applyCorners(s.corners === 'square')
    applyAnimations(s.animations !== false)
    applyColumns(s.columns || 0)
    buildAppearancePickers()
    syncAppearanceControls()
    setColumns(s.columns || 0, { persist: false })
    matrix.set(s.matrix !== false)
    $('#set-matrix').checked = s.matrix !== false
    $('#set-animations').checked = s.animations !== false
    const titlebarToggle = $('#set-titlebar')
    if (titlebarToggle) titlebarToggle.checked = s.custom_titlebar !== false
    document.documentElement.setAttribute('data-padding', s.layout_padding || 'normal')
    document.documentElement.setAttribute('data-density', s.layout_density || 'comfortable')
    const padSelect = $('#set-layout-padding')
    if (padSelect) padSelect.value = s.layout_padding || 'normal'
    const denSelect = $('#set-layout-density')
    if (denSelect) denSelect.value = s.layout_density || 'comfortable'
    const waveCheck = $('#set-search-wave')
    if (waveCheck) waveCheck.checked = s.search_wave_enabled !== false

    // reading
    $('#set-mode').value = s.reader_mode || 'webtoon'
    $('#set-fit').value = s.reader_fit || 'contain'
    $('#set-filter').value = s.reader_filter || 'none'
    $('#set-width').value = parseInt(s.reader_max_width) || 100
    $('#set-width-out').textContent = s.reader_max_width || '100%'
    $('#set-gap').value = s.reader_gap ?? 0
    $('#set-gap-out').textContent = `${s.reader_gap ?? 0}px`
    $('#set-spread').checked = !!s.reader_spread
    $('#set-keep').checked = s.reader_keep_position !== false
    $('#set-tap').checked = s.reader_tap_zones !== false
    $('#set-reader-animate').checked = s.reader_animate !== false
    $('#set-fullscreen-default').checked = !!s.reader_fullscreen_default
    $('#set-reader-path').value = s.reader_path || ''
    $('#set-preload').value = String(s.reader_preload ?? 3)
    const autoSpeed = s.reader_autoscroll_speed || 60
    $('#set-auto-speed').value = String(autoSpeed)
    $('#r-auto-speed').value = String(autoSpeed)

    // results
    $('#set-dedupe').checked = s.dedupe_results !== false
    $('#set-interleave').checked = !!s.interleave_results
    $('#set-downloaded').value = s.downloaded_results || 'darken'
    $('#set-language').value = s.language || 'en'
    $('#set-scanlator').value = s.scanlator || ''
    $('#set-interleave-browse').checked = s.interleave_browse !== false
    $('#set-data-saver').checked = !!s.data_saver

    // downloads
    $('#set-output').value = s.output_dir || ''
    for (const btn of $$('#set-format button'))
        btn.classList.toggle('on', btn.dataset.format === (s.format || 'cbz'))
    $('#set-name-single').value = s.name_single || ''
    $('#set-name-chapter').value = s.name_chapter || ''
    $('#set-name-range').value = s.name_range || ''
    $('#set-keep-images').checked = !!s.keep_images
    $('#set-open-done').checked = !!s.open_folder_when_done
    $('#set-confirm-large').checked = s.confirm_large !== false
    $('#set-large-threshold').value = s.large_threshold ?? 100
    $('#set-bundle').value = String(s.bundle ?? 0)

    // performance
    const fill = (id, value) => {
        $(id).value = String(value)
        const out = $(`${id}-out`)
        if (out) out.textContent = String(value)
    }
    // Values are written *before* wire() runs, so bindSlider's initial render
    // picks them up and every fill is painted from the saved value rather
    // than from the markup default.
    fill('#set-max-jobs', s.max_concurrent_jobs ?? 2)
    fill('#set-chapter-workers', s.chapter_workers ?? 3)
    fill('#set-image-workers', s.image_workers ?? 6)
    fill('#set-retries', s.retries ?? 5)
    $('#set-delay').value = String(Math.round((s.delay ?? 0.5) * 10))

    // background
    $('#set-tray').checked = !!s.minimize_to_tray
    $('#set-tray-notify').checked = s.tray_notifications !== false
    $('#set-log-advanced').checked = !!s.queue_log_advanced
    $('#set-advanced').checked = !!s.advanced_info
    $('#set-confirm-delete').checked = s.confirm_delete !== false
    $('#set-auto-snapshot').checked = !!s.auto_snapshot

    // servers
    $('#set-server-token').value = s.server_token || ''
    $('#set-server-port').value = s.server_port ?? 8577
    $('#set-server-verbose').checked = !!s.server_verbose
    const autoSrvEl = $('#set-server-autostart')
    if (autoSrvEl) autoSrvEl.checked = !!s.server_autostart
    $('#set-opds-port').value = s.opds_port ?? 8578
    $('#set-opds-autostart').checked = !!s.opds_autostart
    $('#set-opds-cover-root').value = s.opds_cover_root || ''
    const autoScanEl = $('#set-lib-autoscan')
    if (autoScanEl) autoScanEl.checked = s.lib_autoscan !== false
    const autoDiscEl = $('#set-lib-autodiscover')
    if (autoDiscEl) autoDiscEl.checked = s.lib_autodiscover !== false
    const libDispSelect = $('#set-lib-display-mode')
    if (libDispSelect) libDispSelect.value = s.lib_display_mode || 'carousel'
    const libPagCheck = $('#set-lib-paginate')
    if (libPagCheck) libPagCheck.checked = !!s.lib_paginate
    const libPagSize = $('#set-lib-page-size')
    if (libPagSize) libPagSize.value = s.lib_page_size || 24
    const dbEnCheck = $('#set-db-enabled')
    if (dbEnCheck) dbEnCheck.checked = s.db_enabled !== false
    const dbSfwCheck = $('#set-db-sfw-enabled')
    if (dbSfwCheck) dbSfwCheck.checked = s.db_sfw_enabled !== false
    const dbNsfwCheck = $('#set-db-nsfw-enabled')
    if (dbNsfwCheck) dbNsfwCheck.checked = s.db_nsfw_enabled !== false

    $('#d-out').value = s.output_dir || ''
    for (const button of $$('#d-format button'))
        button.classList.toggle('on', button.dataset.format === (s.format || 'cbz'))
    for (const button of $$('#d-bundle button'))
        button.classList.toggle('on', button.dataset.bundle === '0')

    wire()
    wireFilters()
    wireDetail()
    wireMarks()
    wireRefine()
    wirePages()
    wireZen()
    mountHeroIslands()
    // Both, because browsers fire them in different situations and a missed
    // save is the whole point of having this.
    window.addEventListener('pagehide', flushPosition)
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'hidden') flushPosition()
    })
    if (s.reader_zen) setZen(true)
    repaintSliders()
    await fillSources()
    refreshSources()
    refreshFilters()
    refreshLock()
    refreshLibraryFolders()
    refreshServersStatus()
    pollServerLogs()
    updateSearchLayout(s.search_layout || 'grid')
    searchWave = createSearchGridWave($('#search-wave-canvas'))
    shelves.wire()
    wireCarousel()
    wireSearchSuggestions()
    setupTitlebar()
    keymap.load(s)
    bindActions()
    renderKeysTable()
    wireKeysPage()
    renderShortcutSheet()
    showView('library')
    $('#boot').hidden = true
    state.booted = true
    window.__readerReady = true
}

boot().catch(e => {
    const boot = document.getElementById('boot')
    boot.textContent = `Reader failed to start: ${e.message}`
    window.__readerError = String(e?.stack || e)
})

// exposed for tests
window.__reader = {
    state, call, openPath, showView, applyFilter,
    setTheme, setAccent, setCorners, setAnimations, setColumns, setMatrix,
    renderSourceRanks, refreshLock, showLock,
    refreshStats, showTab, paintSlider, repaintSliders, streaks,
    refreshFilters, describeFilters, splitList,
    openDetail, closeDetail, refreshMarks, refreshGenres,
    renderChapters, visibleChapters, resetChapterFilters,
    needsProxy, resolveCover, coverAttrs, hydrateCovers,
    mountHeroIslands, heroSelect, heroSlider,
    renderPages, renderPagesHeader, togglePageMark, setZen, pages,
    startAutosave, stopAutosave, flushPosition,
    parseRanges, chapterNumber, detail,
    shelves, renderLibrary, refreshLibraryFolders,
    keymap, renderKeysTable, renderShortcutSheet, renderKeyPresets,
    setupTitlebar, streamUrl,
    setZoom, bumpZoom,
    get matrix() { return matrix },
}

// The shelf tree is reached often enough from tests and the console to be
// worth its own handle rather than going through __reader every time.
window.__shelves = shelves
