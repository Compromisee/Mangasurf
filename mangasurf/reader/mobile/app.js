/* Mangasurf mobile — a dedicated, phone-first PWA.
 *
 * Talks to the host's Api through the same POST /api/<method> bridge the
 * desktop UI uses, so every endpoint works and nothing extra has to exist on
 * the host. All scraping/downloading stays on the computer; the phone is a
 * beautiful remote control, reachable over Tailscale or the LAN.
 *
 * Animation & effects settings are shared with the desktop app (same keys),
 * so tuning the carousel here also tunes it there.
 */

const $ = s => document.querySelector(s)
const $$ = s => [...document.querySelectorAll(s)]
const esc = s => s == null ? '' : String(s)
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

/* ── bridge ──────────────────────────────────────────────────────────── */
let TOKEN = window.__MANGASURF_TOKEN__ || localStorage.getItem('msf_token') || ''
if (TOKEN) localStorage.setItem('msf_token', TOKEN)

async function call(method, ...args) {
  try {
    const r = await fetch('/api/' + method, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Mangasurf-Token': TOKEN },
      body: JSON.stringify({ args, _token: TOKEN }),
    })
    const p = await r.json().catch(() => ({}))
    return p && 'result' in p ? p.result : (p || { ok: false, error: 'no response' })
  } catch (e) {
    return { ok: false, error: String(e) }
  }
}

let settingsTimer = null
let settingsPending = {}
function pushSettings(changes) {
  Object.assign(settings, changes)
  Object.assign(settingsPending, changes)
  clearTimeout(settingsTimer)
  settingsTimer = setTimeout(() => { const b = settingsPending; settingsPending = {}; call('set_settings', b) }, 250)
}

/* ── settings / motion ───────────────────────────────────────────────── */
let settings = {}
const THEMES = [
  ['midnight', 'Midnight'], ['oled', 'OLED'], ['mocha', 'Mocha'], ['forest', 'Forest'],
  ['plum', 'Plum'], ['ocean', 'Ocean'], ['light', 'Light'], ['paper', 'Paper'],
]
const ACCENTS = [['blue', '#3b82f6'], ['violet', '#a78bfa'], ['teal', '#2dd4bf'], ['rose', '#fb7185'], ['amber', '#fbbf24'], ['mint', '#34d399']]

function applyMotion() {
  const s = settings
  const ms = Number(s.motion_speed) || 1
  const cSpeed = Number(s.carousel_speed) || 1
  const tilt = Number(s.carousel_tilt) ?? 16
  const depth = Number(s.carousel_depth) ?? 140
  const shine = Number(s.cover_shine_speed) || 1.8
  const shineI = Number(s.cover_shine_intensity) ?? 0.10
  const root = document.documentElement
  root.style.setProperty('--dur', (0.18 / ms).toFixed(3) + 's')
  root.style.setProperty('--motion', String(ms))
  root.style.setProperty('--carousel-t', (0.5 / cSpeed).toFixed(3) + 's')
  root.style.setProperty('--carousel-tilt', String(tilt))
  root.style.setProperty('--carousel-depth', depth + 'px')
  root.style.setProperty('--shine-t', shine + 's')
  root.style.setProperty('--shine-i', String(shineI))
  root.dataset.shine = s.cover_shine === false ? 'off' : 'on'
}
const applyTheme = n => { document.documentElement.dataset.theme = THEMES.some(t => t[0] === n) ? n : 'midnight' }
const applyAccent = n => { document.documentElement.dataset.accent = ACCENTS.some(a => a[0] === n) ? n : 'blue' }

/* ── state & views ───────────────────────────────────────────────────── */
let library = []
let carouselIndex = 0
let carouselBooks = []
let currentView = 'home'

function showView(name) {
  currentView = name
  $$('.view').forEach(v => v.classList.toggle('on', v.id === 'view-' + name))
  $$('.tab').forEach(t => t.classList.toggle('on', t.dataset.view === name))
  if (name === 'home') refreshLibrary()
  if (name === 'downloads') refreshQueue()
}

/* ── library ─────────────────────────────────────────────────────────── */
function streamUrl(url) {
  if (!url) return url
  const here = location.hostname
  if (!here || here === '127.0.0.1' || here === 'localhost') return url
  let parsed
  try { parsed = new URL(url, location.href) } catch { return url }
  if (parsed.hostname !== '127.0.0.1' && parsed.hostname !== 'localhost') return url
  const path = parsed.searchParams.get('path')
  if (!path) return url
  const route = parsed.pathname.startsWith('/book') ? 'book' : 'page'
  // Re-inject the token so images load even when the app was opened via SW cache.
  return `${location.origin}/stream/${route}?path=${encodeURIComponent(path)}&token=${encodeURIComponent(TOKEN)}`
}
function coverSrc(dir, cover) {
  if (cover && /^(https?:|data:)/.test(cover)) return cover
  if (cover && cover.startsWith('/stream/')) return cover + (cover.includes('?') ? '&' : '?') + (TOKEN ? 'token=' + encodeURIComponent(TOKEN) : '')
  return cover || ''
}
function progress(item) {
  if (!item) return { pct: 0, read: 0, total: 0, status: 'Unread' }
  const items = item.items || []
  if (!items.length) return { pct: 0, read: 0, total: 0, status: '0 chapters' }
  let read = 0, frac = 0
  for (const it of items) {
    if (it.read) { read++; frac += 1 }
    else if (it.position) {
      const f = it.position.fraction || 0
      if (f >= 0.85) { read++; frac += 1 } else if (f > 0) frac += f
    }
  }
  const pct = Math.min(100, Math.round((frac / items.length) * 100))
  const status = pct >= 100 ? 'Completed' : (pct > 0 ? `Reading ${read}/${items.length}` : 'Unread')
  return { pct, read, total: items.length, status }
}

function sortCarousel(books, mode) {
  const list = [...(books || [])]
  if (mode === 'title') list.sort((a, b) => String(a.title || '').localeCompare(String(b.title || '')))
  else if (mode === 'progress') list.sort((a, b) => progress(b).pct - progress(a).pct)
  else if (mode === 'source') list.sort((a, b) => String(a.source_name || a.source || '').localeCompare(String(b.source_name || b.source || '')))
  else list.sort((a, b) => String(b.last_download || b.added || '').localeCompare(String(a.last_download || a.added || '')))
  return list
}

function renderCarousel() {
  const wrap = $('#carousel-wrap'), track = $('#carousel-track')
  if (!wrap || !track) return
  if (!carouselBooks.length) { wrap.style.display = 'none'; return }
  wrap.style.display = 'block'
  if (carouselIndex >= carouselBooks.length) carouselIndex = Math.max(0, carouselBooks.length - 1)
  const visible = []
  for (let i = 0; i < carouselBooks.length; i++) if (Math.abs(i - carouselIndex) <= 2) visible.push(i)
  track.innerHTML = visible.map(idx => {
    const b = carouselBooks[idx], diff = idx - carouselIndex
    let cls = 'carousel-card'
    if (diff === 0) cls += ' active'
    else if (diff === -1) cls += ' prev-1'
    else if (diff === 1) cls += ' next-1'
    else if (diff === -2) cls += ' prev-2'
    else if (diff === 2) cls += ' next-2'
    const src = coverSrc(b.directory, b.cover)
    const style = src ? `background-image:url('${esc(src)}')` : ''
    return `<div class="${cls}" data-idx="${idx}" style="${style}"></div>`
  }).join('')
}

function renderGrid() {
  const grid = $('#grid')
  grid.innerHTML = library.map(b => {
    const src = coverSrc(b.directory, b.cover)
    const p = progress(b)
    const img = src ? `<img class="thumb" loading="lazy" src="${esc(src)}" alt="">` : `<div class="thumb" style="display:grid;place-items:center;color:var(--dim)">📖</div>`
    return `<div class="grid-card" data-open="${esc(b.path || '')}" data-url="${esc(b.url || '')}">
      ${img}
      <div class="g-title">${esc(b.title || 'Untitled')}</div>
      <div class="g-sub">${esc(p.status)}${p.total ? ' · ' + p.total + ' ch' : ''}</div>
    </div>`
  }).join('')
  $('#library-count').textContent = library.length ? `${library.length} title${library.length === 1 ? '' : 's'}` : ''
}

function renderContinue(recent) {
  const wrap = $('#continue-wrap'), strip = $('#continue-strip')
  const items = (recent || []).filter(i => i.readable !== false)
  if (!items.length) { wrap.hidden = true; return }
  wrap.hidden = false
  strip.innerHTML = items.slice(0, 12).map(i => {
    const src = coverSrc(i.directory, i.cover)
    const pct = Math.round((i.fraction || 0) * 100)
    const img = src ? `<img class="thumb" loading="lazy" src="${esc(src)}" alt="">` : `<div class="thumb" style="display:grid;place-items:center;color:var(--dim)">📖</div>`
    const title = (i.title || 'Untitled').replace(/\.(cbz|cbr|epub|pdf|zip)$/i, '')
    return `<div class="continue-card" data-open="${esc(i.path)}">
      ${img}
      <div class="meta"><div class="cc-title">${esc(title)}</div><div class="cc-sub">${pct}%</div>
        <div class="bar"><i style="width:${pct}%"></i></div></div>
    </div>`
  }).join('')
}

async function refreshLibrary() {
  const res = await call('reader_library')
  library = res?.books || []
  const mode = ($('#carousel-sort')?.value || 'downloaded')
  carouselBooks = sortCarousel(library, mode)
  renderCarousel()
  renderGrid()
  const recent = await call('reader_recent', 12)
  renderContinue(recent?.items || [])
}

/* ── search ──────────────────────────────────────────────────────────── */
let searchTimer = null
async function doSearch(q) {
  const grid = $('#search-grid'), hint = $('#search-hint')
  if (!q.trim()) { grid.innerHTML = ''; hint.hidden = false; return }
  hint.hidden = true
  grid.innerHTML = `<div class="empty">Searching…</div>`
  const res = await call('search', { query: q, page: 1 })
  const results = res?.results || res?.items || []
  grid.innerHTML = results.length ? results.map(r => {
    const src = r.cover || ''
    return `<div class="grid-card" data-url="${esc(r.url || '')}" data-source="${esc(r.source || '')}">
      ${src ? `<img class="thumb" loading="lazy" src="${esc(src)}" alt="">` : `<div class="thumb" style="display:grid;place-items:center;color:var(--dim)">🔍</div>`}
      <div class="g-title">${esc(r.title || 'Untitled')}</div>
      <div class="g-sub">${esc(r.source_name || r.source || '')}</div>
    </div>`
  }).join('') : `<div class="empty">No results.</div>`
}

/* ── queue ───────────────────────────────────────────────────────────── */
let queueTimer = null
async function refreshQueue() {
  const res = await call('get_queue')
  const jobs = res?.jobs || res?.items || res || []
  const list = $('#queue-list'), empty = $('#queue-empty')
  list.innerHTML = (jobs || []).map(j => {
    const pct = j.total ? Math.round((j.done / j.total) * 100) : (j.percent || 0)
    return `<div class="queue-item">
      <div class="q-title">${esc(j.title || j.name || 'Job')}</div>
      <div class="q-sub">${esc(j.status || 'queued')} · ${j.done || 0}/${j.total || '–'}</div>
      <div class="q-bar"><i style="width:${pct}%"></i></div>
    </div>`
  }).join('')
  empty.hidden = !!(jobs && jobs.length)
}

/* ── reader (loose page chapters) ────────────────────────────────────── */
let readerPages = [], readerIndex = 0
async function openPath(path) {
  if (!path) return
  readerPath = path
  const res = await call('reader_open', path)
  if (!res?.ok) return toast(res?.error || 'Could not open that')
  if (Array.isArray(res.pages)) res.pages = res.pages.map(streamUrl)
  if (res.url) res.url = streamUrl(res.url)
  if (res.kind === 'file') {
    // Packaged books need the full engine; hand off to the desktop reader.
    toast('This is a packaged book — opening in the full reader')
    window.open(location.pathname.replace(/\/pwa.*/, '/') || '/', '_blank')
    return
  }
  if (!res.pages || !res.pages.length) return toast('No page images')
  readerPages = res.pages
  readerIndex = 0
  $('#reader-title').textContent = res.title || 'Reading'
  $('#reader-slider').max = String(Math.max(0, readerPages.length - 1))
  $('#reader').hidden = false
  renderPage()
}
function renderPage() {
  if (readerPages.length > 1) {
    $('#reader-slider').value = String(readerIndex)
    $('#reader-count').textContent = `${readerIndex + 1} / ${readerPages.length}`
  } else {
    $('#reader-count').textContent = ''
  }
  const img = $('#reader-img')
  img.style.opacity = '0'
  img.onload = () => { img.style.opacity = '1' }
  img.src = readerPages[readerIndex]
  try { call('reader_save_position', readerPath, readerIndex, 0, readerPages.length, 'webtoon', $('#reader-title').textContent) } catch {}
}
let readerPath = ''

/* ── engine events (live progress for queue) ─────────────────────────── */
window.onEngineEvents = (events) => {
  if (currentView === 'downloads') refreshQueue()
}

/* ── boot ────────────────────────────────────────────────────────────── */
function buildThemeTiles() {
  const el = $('#theme-tiles')
  el.innerHTML = THEMES.map(([id, label]) => `<div class="theme-tile ${settings.theme === id ? 'on' : ''}" data-t="${id}">${label}</div>`).join('')
  el.querySelectorAll('.theme-tile').forEach(t => t.addEventListener('click', () => {
    settings.theme = t.dataset.t
    applyTheme(t.dataset.t)
    pushSettings({ theme: t.dataset.t })
    buildThemeTiles()
  }))
}
function buildSwatches() {
  const el = $('#accent-swatches')
  el.innerHTML = ACCENTS.map(([id, col]) => `<div class="swatch ${settings.accent === id ? 'on' : ''}" data-a="${id}" style="background:${col}"></div>`).join('')
  el.querySelectorAll('.swatch').forEach(s => s.addEventListener('click', () => {
    settings.accent = s.dataset.a
    applyAccent(s.dataset.a)
    pushSettings({ accent: s.dataset.a })
    buildSwatches()
  }))
}
function wireSliders() {
  const map = [
    ['#set-motion-speed', 'motion_speed', 'motion-speed-out', v => Number(v).toFixed(1) + '×', v => Number(v)],
    ['#set-carousel-speed', 'carousel_speed', 'carousel-speed-out', v => Number(v).toFixed(1) + '×', v => Number(v)],
    ['#set-carousel-tilt', 'carousel_tilt', 'carousel-tilt-out', v => Math.round(Number(v)) + '°', v => Number(v)],
    ['#set-carousel-depth', 'carousel_depth', 'carousel-depth-out', v => Math.round(Number(v)) + 'px', v => Number(v)],
    ['#set-cover-shine-speed', 'cover_shine_speed', 'cover-shine-speed-out', v => Number(v).toFixed(1) + 's', v => Number(v)],
    ['#set-cover-shine-intensity', 'cover_shine_intensity', 'cover-shine-intensity-out', v => Math.round(Number(v)) + '%', v => Number(v) / 100],
  ]
  for (const [sel, key, outSel, fmt, toVal] of map) {
    const el = $(sel), out = $(outSel)
    if (!el) continue
    el.value = String(settings[key] ?? TO_RAW[key])
    if (out) out.textContent = fmt(el.value)
    const apply = () => { settings[key] = toVal(el.value); if (out) out.textContent = fmt(el.value); applyMotion(); renderCarousel() }
    el.addEventListener('input', apply)
    el.addEventListener('change', () => { pushSettings({ [key]: toVal(el.value) }) })
  }
  const shine = $('#set-cover-shine')
  if (shine) {
    shine.checked = settings.cover_shine !== false
    shine.addEventListener('change', () => { pushSettings({ cover_shine: shine.checked }); settings.cover_shine = shine.checked; applyMotion() })
  }
  const sc = $('#set-session-clear')
  if (sc) {
    sc.addEventListener('change', async () => {
      const res = await call('set_session_clear', sc.checked)
      sc.checked = !!(res?.cleared ?? sc.checked)
      refreshLibrary()
      toast(sc.checked ? 'Library cleared for this session (nothing deleted)' : 'Library restored')
    })
  }
}
const TO_RAW = { motion_speed: 1, carousel_speed: 1, carousel_tilt: 16, carousel_depth: 140, cover_shine_speed: 1.8, cover_shine_intensity: 10 }

function wireTabs() {
  $$('.tab').forEach(t => t.addEventListener('click', () => showView(t.dataset.view)))
  $('#carousel-sort')?.addEventListener('change', () => { carouselIndex = 0; carouselBooks = sortCarousel(library, $('#carousel-sort').value); renderCarousel() })
  $('#carousel-prev')?.addEventListener('click', () => { if (carouselBooks.length) { carouselIndex = (carouselIndex - 1 + carouselBooks.length) % carouselBooks.length; renderCarousel() } })
  $('#carousel-next')?.addEventListener('click', () => { if (carouselBooks.length) { carouselIndex = (carouselIndex + 1) % carouselBooks.length; renderCarousel() } })
  $('#carousel')?.addEventListener('click', e => {
    const card = e.target.closest('.carousel-card'); if (!card) return
    const idx = Number(card.dataset.idx)
    if (idx === carouselIndex) {
      const b = carouselBooks[idx]; if (b) openPath((b.items || [])[0]?.path || b.path || b.url)
    } else { carouselIndex = idx; renderCarousel() }
  })
  $('#grid')?.addEventListener('click', e => {
    const card = e.target.closest('.grid-card'); if (!card) return
    if (card.dataset.open) openPath(card.dataset.open)
    else if (card.dataset.url) openPath(card.dataset.url)
  })
  $('#continue-strip')?.addEventListener('click', e => {
    const card = e.target.closest('.continue-card'); if (card?.dataset.open) openPath(card.dataset.open)
  })
  $('#search-input')?.addEventListener('input', e => {
    clearTimeout(searchTimer)
    searchTimer = setTimeout(() => doSearch(e.target.value), 320)
  })
  $('#search-clear')?.addEventListener('click', () => { const i = $('#search-input'); i.value = ''; i.focus(); doSearch(''); $('#search-clear').hidden = true })
  $('#search-input').addEventListener('input', e => { $('#search-clear').hidden = !e.target.value.trim() })
  $('#btn-theme')?.addEventListener('click', () => { settings.theme = settings.theme === 'light' ? 'midnight' : 'light'; applyTheme(settings.theme); pushSettings({ theme: settings.theme }); buildThemeTiles() })
  $('#reader-back')?.addEventListener('click', () => { $('#reader').hidden = true; $('#reader-img').src = '' })
  $('#reader-slider')?.addEventListener('input', e => { readerIndex = Number(e.target.value); renderPage() })
  $('#reader-body')?.addEventListener('click', e => {
    const x = e.clientX, w = window.innerWidth
    if (x < w * 0.33) readerIndex = Math.max(0, readerIndex - 1)
    else if (x > w * 0.66) readerIndex = Math.min(readerPages.length - 1, readerIndex + 1)
    else { $('#reader').hidden = true; return }
    renderPage()
  })
  // swipe on reader
  let touchX = 0
  $('#reader-body').addEventListener('touchstart', e => { touchX = e.touches[0].clientX }, { passive: true })
  $('#reader-body').addEventListener('touchend', e => {
    const dx = e.changedTouches[0].clientX - touchX
    if (Math.abs(dx) > 50) { if (dx < 0) readerIndex = Math.min(readerPages.length - 1, readerIndex + 1); else readerIndex = Math.max(0, readerIndex - 1); renderPage() }
  }, { passive: true })
  $('#search-grid')?.addEventListener('click', e => {
    const card = e.target.closest('.grid-card'); if (card?.dataset.url) openPath(card.dataset.url)
  })
}
function toast(msg) {
  let t = $('#toast')
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t) }
  t.textContent = msg
  t.classList.add('show')
  clearTimeout(t._h)
  t._h = setTimeout(() => t.classList.remove('show'), 2600)
}

function startEventPoll() {
  let cursor = 0
  let stopped = false
  function poll() {
    if (stopped) return
    fetch('/api/_events?since=' + cursor + '&token=' + encodeURIComponent(TOKEN))
      .then(r => r.json()).then(d => {
        if (d && d.ok) {
          cursor = d.cursor
          if (d.events && d.events.length && typeof window.onEngineEvents === 'function') window.onEngineEvents(d.events)
        }
        setTimeout(poll, 300)
      }).catch(() => setTimeout(poll, 2500))
  }
  poll()
  window.addEventListener('beforeunload', () => { stopped = true })
}

async function boot() {
  const res = await call('get_settings')
  settings = res?.settings || res || {}
  applyTheme(settings.theme || 'midnight')
  applyAccent(settings.accent || 'blue')
  applyMotion()
  buildThemeTiles()
  buildSwatches()
  wireSliders()
  wireTabs()
  $('#boot').hidden = true
  $('#app').hidden = false
  const sc = $('#set-session-clear')
  if (sc) { const st = await call('session_clear_state'); sc.checked = !!(st?.cleared) }
  await refreshLibrary()
  refreshQueue()
  startEventPoll()
}

window.addEventListener('DOMContentLoaded', boot)
// exposed for tests
window.__mobile = { call, showView, refreshLibrary, renderCarousel, applyMotion, openPath }
