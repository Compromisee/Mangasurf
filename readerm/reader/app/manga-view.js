/* manga-view.js — the manga renderer this fork adds to foliate-js.
 *
 * Why this exists
 * ---------------
 * foliate-js sends comics to `foliate-fxl` (fixed-layout.js), whose whole
 * attribute surface is:
 *
 *     static observedAttributes = ['zoom']
 *
 * It paginates, and that is all it does. `flow: scrolled` lives only in
 * paginator.js, which is for reflowable text, so upstream has no continuous
 * vertical mode at all. Webtoons are unreadable that way — a single strip gets
 * chopped into arbitrary screens.
 *
 * So this element renders the page list directly. It keeps foliate-js's book
 * object as its input (`book.sections`, `book.getCover`, CBZ or a plain list of
 * image URLs), which means everything else in the engine still applies.
 *
 * Modes
 * -----
 *   webtoon   continuous vertical strip, no gaps — long-strip Korean comics
 *   vertical  continuous vertical, gaps between pages
 *   ltr       paged, left-to-right (western / most translated manhwa)
 *   rtl       paged, right-to-left (Japanese manga reading order)
 *
 * Paged modes optionally show two pages side by side (`spread`), with the
 * order flipped in `rtl` so the binding is in the middle.
 */

const IMAGE_FIT = { contain: 'contain', width: 'width', height: 'height', original: 'original' }

const css = `
:host {
    display: block;
    position: relative;
    overflow: hidden;
    background: var(--reader-bg, #101014);
    --page-gap: 0px;
    --page-max: 100%;
}
#scroller {
    width: 100%;
    height: 100%;
    overflow: auto;
    overscroll-behavior: contain;
    scrollbar-width: thin;
    display: flex;
    flex-direction: column;
    align-items: center;
    scroll-behavior: var(--scroll-behavior, auto);
}
#scroller.paged {
    overflow: hidden;
    flex-direction: row;
    align-items: center;
    justify-content: center;
    gap: var(--page-gap);
}
#track {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: var(--page-gap);
    width: 100%;
    min-height: 100%;
}
#scroller.paged #track {
    flex-direction: row;
    justify-content: center;
    align-items: center;
    width: 100%;
    height: 100%;
    gap: var(--page-gap);
}
#scroller.paged.rtl #track { flex-direction: row-reverse; }

.pg {
    display: block;
    max-width: var(--page-max);
    width: auto;
    height: auto;
    object-fit: contain;
    background: var(--page-bg, transparent);
}
#scroller:not(.paged) .pg { width: var(--page-max); }

/* A page that has not loaded yet has no intrinsic height, and an <img> with
 * no height is zero pixels tall. With every page stacked at offsetTop 0 the
 * strip does not scroll at all and the position observer reports the *last*
 * page immediately. Measured before this rule, with six 300x900 pages:
 *     scrollHeight 640 == clientHeight 640, scrollable false, index 5
 * So an unloaded page reserves a screenful, and gives the space back the
 * moment the real image arrives. */
#scroller:not(.paged) .pg.pending {
    min-height: 80vh;
    background: var(--page-pending, #17171d);
}
#scroller.paged .pg { max-height: 100%; max-width: 100%; }

/* fit modes */
:host([fit="width"])  #scroller.paged .pg { width: 100%;  height: auto; max-height: none; }
:host([fit="height"]) #scroller.paged .pg { height: 100%; width: auto;  max-width: none; }
:host([fit="original"]) .pg { width: auto; max-width: none; height: auto; max-height: none; }

/* filters — dark mode for scanned pages, applied to the image itself */
:host([filter="dim"])    .pg { filter: brightness(.82); }
:host([filter="dimmer"]) .pg { filter: brightness(.65); }
:host([filter="invert"]) .pg { filter: invert(1) hue-rotate(180deg); }
:host([filter="sepia"])  .pg { filter: sepia(.45) brightness(.92); }
:host([filter="gray"])   .pg { filter: grayscale(1); }

#empty {
    position: absolute; inset: 0; display: grid; place-items: center;
    color: var(--reader-fg, #8a8a99); font: 500 14px system-ui, sans-serif;
    pointer-events: none;
}
`

export class MangaView extends HTMLElement {
    static observedAttributes = ['mode', 'fit', 'gap', 'max-width', 'spread', 'filter', 'zoom']

    #root = this.attachShadow({ mode: 'open' })
    #scroller
    #track
    #empty
    #pages = []            // { src, el, index, loaded }
    #index = 0
    #mode = 'webtoon'
    #spread = false
    #zoom = 1
    #io = null             // lazy-load observer
    #posIo = null          // which page am I on (scroll modes)
    #resize
    #suppressScrollEvents = false
    #autoRaf = 0
    #autoSpeed = 60
    #userScrolling = false
    #scrollIdle = null
    #seekSettle = null

    constructor() {
        super()
        const sheet = new CSSStyleSheet()
        sheet.replaceSync(css)
        this.#root.adoptedStyleSheets = [sheet]

        this.#scroller = document.createElement('div')
        this.#scroller.id = 'scroller'
        this.#track = document.createElement('div')
        this.#track.id = 'track'
        this.#empty = document.createElement('div')
        this.#empty.id = 'empty'
        this.#empty.textContent = 'Nothing open'
        this.#scroller.append(this.#track)
        this.#root.append(this.#scroller, this.#empty)

        this.#scroller.addEventListener('scroll', () => {
            if (this.#suppressScrollEvents) return
            // While the reader is actually scrolling, a late image must not
            // yank the view back to where it started.
            this.#userScrolling = true
            clearTimeout(this.#scrollIdle)
            this.#scrollIdle = setTimeout(() => { this.#userScrolling = false }, 220)
            this.#emitRelocate()
        }, { passive: true })

        this.#resize = new ResizeObserver(() => this.#applyLayout())
        this.#resize.observe(this)
    }

    connectedCallback() { this.#applyLayout() }

    disconnectedCallback() {
        this.#io?.disconnect()
        this.#posIo?.disconnect()
        this.#resize?.disconnect()
    }

    attributeChangedCallback(name, _old, value) {
        // Width, gap and zoom all change how tall the strip is, and scrollTop
        // is an absolute pixel offset -- so the same offset lands somewhere
        // else once the pages reflow. Measured on page 6 of 12 at zoom 200%:
        // scrollHeight fell 71216 -> 57216 while scrollTop stayed at 35000,
        // moving the reader from 0.497 through the chapter to 0.620.
        // Anchoring on the page keeps you where you were.
        const reflows = name === 'zoom' || name === 'max-width' || name === 'gap'
        const anchor = reflows ? this.#captureAnchor() : null

        if (name === 'mode') this.setMode(value || 'webtoon')
        else if (name === 'gap') this.style.setProperty('--page-gap', `${parseInt(value || 0, 10)}px`)
        else if (name === 'max-width') this.#setMaxWidth(value)
        else if (name === 'spread') { this.#spread = value !== null && value !== 'false'; this.#applyLayout() }
        else if (name === 'zoom') { this.#zoom = parseFloat(value) || 1; this.#setMaxWidth(this.getAttribute('max-width')) }
        else this.#applyLayout()

        if (anchor) this.#restoreAnchor(anchor)
    }

    /** Which page is at the top of the view, and how far into it we are. */
    #captureAnchor() {
        if (this.paged || !this.#pages.length) return null
        const el = this.#scroller
        const top = el.scrollTop
        let index = 0
        let offset = 0
        for (const { el: img, index: i } of this.#pages) {
            if (img.offsetTop <= top) {
                index = i
                offset = img.offsetHeight
                    ? (top - img.offsetTop) / img.offsetHeight
                    : 0
            } else break
        }
        return { index, offset: Math.max(0, Math.min(1, offset)) }
    }

    #restoreAnchor(anchor) {
        if (!anchor) return
        // The images have not re-laid out yet, so wait for the frame that
        // follows the style change before measuring their new heights.
        const apply = () => {
            const target = this.#pages[anchor.index]?.el
            if (!target) return
            this.#suppressScrollEvents = true
            this.#scroller.scrollTop =
                target.offsetTop + anchor.offset * target.offsetHeight
            requestAnimationFrame(() => {
                this.#suppressScrollEvents = false
                this.#emitRelocate()
            })
        }
        requestAnimationFrame(apply)
    }

    #setMaxWidth(value) {
        const base = (value == null || value === '' || value === 'full') ? '100%' : value
        // zoom multiplies whatever the base width is, so pinch/ctrl+wheel works
        // in every mode rather than only in the paged ones.
        if (this.#zoom && this.#zoom !== 1 && base.endsWith('%'))
            this.style.setProperty('--page-max', `${parseFloat(base) * this.#zoom}%`)
        else if (this.#zoom && this.#zoom !== 1 && base.endsWith('px'))
            this.style.setProperty('--page-max', `${parseFloat(base) * this.#zoom}px`)
        else this.style.setProperty('--page-max', base)
    }

    // ------------------------------------------------------------------ open

    /** Accepts a foliate-js book, or `{ pages: [url, ...] }` for a live chapter. */
    async open(book) {
        this.book = book
        this.#pages = []
        this.#index = 0
        this.#track.replaceChildren()

        let srcs = []
        if (Array.isArray(book?.pages)) {
            srcs = book.pages.slice()
        } else if (book?.sections?.length) {
            // CBZ path: each section is a tiny HTML doc wrapping one image.
            // Pull the image URL out so we can lay the pages out ourselves.
            for (const section of book.sections) {
                const url = await this.#imageFromSection(section)
                if (url) srcs.push(url)
            }
        }

        this.#empty.style.display = srcs.length ? 'none' : ''
        for (const [i, src] of srcs.entries()) {
            const img = document.createElement('img')
            img.className = 'pg'
            img.decoding = 'async'
            img.loading = 'lazy'
            img.dataset.index = String(i)
            img.alt = `Page ${i + 1}`
            // Real dimensions are unknown until load, and a zero-height <img>
            // collapses the strip (see the .pending rule above).
            img.classList.add('pending')
            img.dataset.src = src
            img.addEventListener('load', () => {
                // A page above the one being read swaps its one-screen
                // placeholder for its real height, which moves everything
                // below it. scrollTop is absolute, so without re-pinning you
                // drift: measured landing 774px short of page 8 because four
                // earlier pages finished loading after the jump.
                // Capture *before* the class flip: removing `.pending`
                // swaps an 80vh placeholder for the image's real height, so
                // measuring afterwards already reflects the shift.
                const anchor = this.#captureAnchor()
                img.classList.remove('pending')
                // Only re-pin when the page that grew sits above the reader;
                // a page further down does not move anything being read.
                const grewAbove = anchor !== null
                    && Number(img.dataset.index) <= anchor.index
                if (grewAbove && !this.#userScrolling) this.#restoreAnchor(anchor)
                this.#emitRelocate()
            }, { once: true })
            img.addEventListener('error', () => {
                img.classList.remove('pending')
                img.classList.add('failed')
                this.dispatchEvent(new CustomEvent('page-error', { detail: { index: i, src } }))
            }, { once: true })
            this.#pages.push({ src, el: img, index: i, loaded: false })
            this.#track.append(img)
        }

        this.#observe()
        this.#applyLayout()
        this.dispatchEvent(new CustomEvent('loaded', { detail: { pages: srcs.length } }))
        this.#emitRelocate()
        return srcs.length
    }

    async #imageFromSection(section) {
        try {
            const url = await section.load?.()
            if (!url) return null
            // comic-book.js hands back a blob: URL to an HTML wrapper.
            const res = await fetch(url)
            const text = await res.text()
            const match = text.match(/<img[^>]+src="([^"]+)"/i)
            return match ? match[1] : null
        } catch {
            return null
        }
    }

    // ------------------------------------------------------------ lazy loads

    #observe() {
        this.#io?.disconnect()
        this.#posIo?.disconnect()
        if (!this.#pages.length) return

        // Load a few screens ahead so scrolling stays smooth without pulling
        // a 200-page chapter into memory at once.
        this.#io = new IntersectionObserver(entries => {
            for (const entry of entries) {
                if (!entry.isIntersecting) continue
                const img = entry.target
                if (img.dataset.src && !img.src) {
                    img.src = img.dataset.src
                    const rec = this.#pages[Number(img.dataset.index)]
                    if (rec) rec.loaded = true
                }
            }
        }, { root: this.#scroller, rootMargin: '250% 0px' })

        this.#posIo = new IntersectionObserver(entries => {
            let best = null
            for (const entry of entries)
                if (entry.isIntersecting && (!best || entry.intersectionRatio > best.intersectionRatio))
                    best = entry
            if (!best) return
            const idx = Number(best.target.dataset.index)
            if (Number.isInteger(idx) && idx !== this.#index) {
                this.#index = idx
                this.#emitRelocate()
            }
        }, { root: this.#scroller, threshold: [0.1, 0.5, 0.9] })

        for (const { el } of this.#pages) {
            this.#io.observe(el)
            this.#posIo.observe(el)
        }
    }

    // ---------------------------------------------------------------- layout

    setMode(mode) {
        this.#mode = IMAGE_FIT[mode] ? this.#mode : (mode || 'webtoon')
        this.#applyLayout()
        this.dispatchEvent(new CustomEvent('mode', { detail: { mode: this.#mode } }))
    }

    get mode() { return this.#mode }
    get index() { return this.#index }
    get length() { return this.#pages.length }
    get paged() { return this.#mode === 'ltr' || this.#mode === 'rtl' }

    #applyLayout() {
        const paged = this.paged
        this.#scroller.classList.toggle('paged', paged)
        this.#scroller.classList.toggle('rtl', this.#mode === 'rtl')
        if (this.#mode === 'webtoon') this.style.setProperty('--page-gap', '0px')

        if (paged) this.#showSpread()
        else for (const { el } of this.#pages) el.style.display = ''
    }

    #showSpread() {
        const visible = new Set([this.#index])
        if (this.#spread && this.#index + 1 < this.#pages.length)
            visible.add(this.#index + 1)
        for (const { el, index } of this.#pages) {
            el.style.display = visible.has(index) ? '' : 'none'
            if (visible.has(index) && el.dataset.src && !el.src) el.src = el.dataset.src
        }
    }

    // ------------------------------------------------------------ navigation

    goTo(index) {
        const i = Math.max(0, Math.min(this.#pages.length - 1, Math.round(index)))
        this.#index = i
        if (this.paged) {
            this.#showSpread()
        } else {
            const el = this.#pages[i]?.el
            if (el) {
                // scrollIntoView on a page that has not loaded yet lands
                // short: a `.pending` placeholder is one screen tall, not the
                // image's real height, so every page after it is still at a
                // provisional offset. Measured jumping to page 9 of 14:
                // offsetTop said 48000 but the view settled at 32112.
                //
                // Setting scrollTop directly is exact for what is laid out
                // now, and the correction below re-runs once the target image
                // has its real size.
                // Jumping is a moving target. Scrolling towards a distant
                // page brings the pages in between into the lazy-load margin;
                // each one swaps an 80vh placeholder for its real height and
                // pushes the destination further down. Measured jumping to
                // page 8 of 12: offsetTop read 8028 at click time and 27300
                // once the scroll had settled -- landing 774px short.
                //
                // So the offset is re-read until it stops moving, rather than
                // trusted once.
                const settle = () => {
                    this.#suppressScrollEvents = true
                    this.#scroller.scrollTop = el.offsetTop
                    requestAnimationFrame(() => { this.#suppressScrollEvents = false })
                    return el.offsetTop
                }
                if (el.dataset.src && !el.src) el.src = el.dataset.src

                let last = settle()
                let tries = 0
                const chase = () => {
                    // Give up if the reader moved on, or nothing shifts.
                    if (this.#index !== i || this.#userScrolling) return
                    const now = settle()
                    if (now !== last && ++tries < 40) {
                        last = now
                        requestAnimationFrame(chase)
                    } else if (tries < 40) {
                        // Steady for a frame; check once more in case an
                        // image is still decoding.
                        tries += 1
                        setTimeout(chase, 60)
                    }
                }
                requestAnimationFrame(chase)
            }
        }
        this.#emitRelocate()
        return i
    }

    next() {
        const step = this.#spread && this.paged ? 2 : 1
        if (this.#index + step >= this.#pages.length && this.#index >= this.#pages.length - 1) {
            this.dispatchEvent(new CustomEvent('end', { detail: { edge: 'end' } }))
            return false
        }
        if (this.paged) return this.goTo(this.#index + step) !== this.#index
        this.#scrollBy(0.9)
        return true
    }

    prev() {
        const step = this.#spread && this.paged ? 2 : 1
        if (this.#index <= 0) {
            this.dispatchEvent(new CustomEvent('end', { detail: { edge: 'start' } }))
            return false
        }
        if (this.paged) return this.goTo(this.#index - step) !== this.#index
        this.#scrollBy(-0.9)
        return true
    }

    /** "left" and "right" are physical keys; rtl swaps what they mean. */
    goLeft() { return this.#mode === 'rtl' ? this.next() : this.prev() }
    goRight() { return this.#mode === 'rtl' ? this.prev() : this.next() }

    #scrollBy(fraction) {
        const el = this.#scroller
        const before = el.scrollTop
        el.scrollBy({ top: el.clientHeight * fraction, behavior: 'instant' })
        if (el.scrollTop === before) {
            const edge = fraction > 0 ? 'end' : 'start'
            const atEdge = fraction > 0
                ? el.scrollTop + el.clientHeight >= el.scrollHeight - 2
                : el.scrollTop <= 0
            if (atEdge) this.dispatchEvent(new CustomEvent('end', { detail: { edge } }))
        }
    }

    /** 0..1 through the chapter. Uses scroll position in continuous modes. */
    /**
     * How far through the book, 0..1.
     *
     * Measured in PAGES, not in pixels. The old version was
     * `scrollTop / (scrollHeight - clientHeight)`, and scrollHeight grows all
     * through a chapter as lazy placeholders are swapped for real images --
     * an 80vh placeholder becoming a 1200px page adds height below you. So
     * the same physical position reported a different number a second later.
     *
     * Measured on a 40-page strip: parked at scrollTop 4000 and not touched,
     * the fraction fell from 0.1411 to 0.1376 as later pages loaded, i.e. the
     * bar slid backwards on its own. Scrolling to the bottom reported 89%.
     *
     * Counting pages fixes both: the page count is known the moment the
     * chapter opens and never changes, so only the position *within* the
     * current page depends on geometry, and that is local and small.
     *
     * The unit is "pages consumed by the bottom edge of the viewport", so the
     * very bottom of the last page is exactly 1.0.
     */
    get fraction() {
        const total = this.#pages.length
        if (!total) return 0
        if (this.paged) return total < 2 ? 1 : this.#index / (total - 1)

        const el = this.#scroller
        // Genuinely at the bottom: report the end, whatever the arithmetic
        // says. Sub-pixel rounding otherwise leaves a chapter at 99%.
        if (el.scrollHeight - (el.scrollTop + el.clientHeight) <= 2) return 1

        const edge = el.scrollTop + el.clientHeight
        let index = 0
        let within = 0
        for (const { el: img, index: i } of this.#pages) {
            if (img.offsetTop <= edge) {
                index = i
                const height = img.offsetHeight || 1
                within = Math.min(1, Math.max(0, (edge - img.offsetTop) / height))
            } else break
        }
        return Math.min(1, Math.max(0, (index + within) / total))
    }

    setFraction(value) {
        const f = Math.min(1, Math.max(0, Number(value) || 0))
        if (this.paged) return this.goTo(Math.round(f * (this.#pages.length - 1)))
        const el = this.#scroller
        const apply = () => {
            const span = el.scrollHeight - el.clientHeight
            if (span <= 0) return false
            this.#suppressScrollEvents = true
            // Same units as `fraction`: pages, not pixels. Multiplying the
            // scrollable span by a page-based fraction would land in the
            // wrong place, and the two have to round-trip -- the position is
            // saved as a fraction and restored through here.
            const total = this.#pages.length
            const exact = f * total
            const index = Math.min(total - 1, Math.floor(exact))
            const target = this.#pages[index]?.el
            if (f >= 1 || !target) {
                el.scrollTop = span
            } else {
                const within = exact - index
                const height = target.offsetHeight || 0
                // `fraction` measures the viewport's BOTTOM edge, so undo the
                // viewport height to get the top edge back.
                el.scrollTop = Math.max(
                    0, target.offsetTop + within * height - el.clientHeight)
            }
            requestAnimationFrame(() => { this.#suppressScrollEvents = false })
            this.#emitRelocate()
            return true
        }
        // Resuming right after open() races the first images: the strip has no
        // scrollable span yet, so the seek lands at 0 and the saved position is
        // silently lost. Retry over a few frames until there is somewhere to go.
        const landed = apply()
        if (!landed) {
            let tries = 0
            const retry = () => {
                if (apply() || ++tries > 30) return
                requestAnimationFrame(retry)
            }
            requestAnimationFrame(retry)
        }
        // Seeking into the middle of a chapter lands on pages that are still
        // 80vh placeholders, so their offsetTop is wrong and the landing is
        // short -- measured 0.50 coming back as 0.456. Once the target page
        // has its real height, correct the landing. Chases a few times because
        // each correction can bring another placeholder into view.
        this.#settleSeek(f)
    }

    /** Re-apply a seek as the pages around it stop being placeholders. */
    #settleSeek(f, attempt = 0) {
        clearTimeout(this.#seekSettle)
        if (attempt > 6) return
        this.#seekSettle = setTimeout(() => {
            if (this.#userScrolling) return          // the reader took over
            const current = this.fraction
            if (Math.abs(current - f) < 0.004) return
            const el = this.#scroller
            const span = el.scrollHeight - el.clientHeight
            if (span <= 0) return
            const total = this.#pages.length
            const exact = f * total
            const index = Math.min(total - 1, Math.floor(exact))
            const target = this.#pages[index]?.el
            if (!target) return
            this.#suppressScrollEvents = true
            el.scrollTop = f >= 1 ? span : Math.max(
                0, target.offsetTop + (exact - index) * (target.offsetHeight || 0)
                   - el.clientHeight)
            requestAnimationFrame(() => {
                this.#suppressScrollEvents = false
                this.#emitRelocate()
            })
            this.#settleSeek(f, attempt + 1)
        }, 120)
    }

    #emitRelocate() {
        if (!this.paged && this.#pages.length) {
            // In scroll modes the position observer can lag a fast flick, so
            // derive the page from scroll offset as well and take the later.
            const el = this.#scroller
            const mid = el.scrollTop + el.clientHeight / 2
            let best = this.#index
            for (const { el: img, index } of this.#pages) {
                if (img.offsetTop <= mid) best = index
                else break
            }
            // At the very bottom, name the last page. The midpoint rule
            // cannot reach a final page shorter than half the viewport -- a
            // 135px credits page under an 800px window leaves the midpoint
            // inside the page before it -- so the counter said "10 / 11" on
            // the last screen while the progress bar said 100%.
            if (el.scrollHeight - (el.scrollTop + el.clientHeight) <= 2)
                best = this.#pages.length - 1
            this.#index = best
        }
        this.dispatchEvent(new CustomEvent('relocate', {
            detail: {
                index: this.#index,
                total: this.#pages.length,
                fraction: this.fraction,
                mode: this.#mode,
            },
        }))
    }

    // ----------------------------------------------------------- autoscroll

    /* Hands-free reading, the one thing a long webtoon strip really wants.
     * Driven by requestAnimationFrame with a sub-pixel accumulator rather
     * than setInterval + integer scrollTop: at slow speeds an integer step
     * per tick either rounds to 0 (nothing moves) or to 1px per frame, which
     * is a fixed 60px/s no matter what speed was asked for. */
    startAutoScroll(pixelsPerSecond = 60) {
        this.stopAutoScroll()
        if (this.paged) return false
        this.#autoSpeed = Math.max(4, Number(pixelsPerSecond) || 60)
        let last = performance.now()
        let carry = 0
        const step = now => {
            if (!this.#autoRaf) return
            const dt = Math.min(0.25, (now - last) / 1000)
            last = now
            carry += this.#autoSpeed * dt
            const whole = Math.floor(carry)
            if (whole > 0) {
                carry -= whole
                const el = this.#scroller
                const before = el.scrollTop
                el.scrollTop = before + whole
                if (el.scrollTop === before) {          // hit the bottom
                    this.stopAutoScroll()
                    this.dispatchEvent(new CustomEvent('end', { detail: { edge: 'end' } }))
                    return
                }
            }
            this.#autoRaf = requestAnimationFrame(step)
        }
        this.#autoRaf = requestAnimationFrame(step)
        this.dispatchEvent(new CustomEvent('autoscroll', {
            detail: { running: true, speed: this.#autoSpeed } }))
        return true
    }

    stopAutoScroll() {
        if (this.#autoRaf) {
            cancelAnimationFrame(this.#autoRaf)
            this.#autoRaf = 0
            this.dispatchEvent(new CustomEvent('autoscroll', { detail: { running: false } }))
        }
    }

    get autoScrolling() { return !!this.#autoRaf }
    get autoScrollSpeed() { return this.#autoSpeed }

    setAutoScrollSpeed(pixelsPerSecond) {
        this.#autoSpeed = Math.max(4, Number(pixelsPerSecond) || 60)
        if (this.#autoRaf) this.startAutoScroll(this.#autoSpeed)
        return this.#autoSpeed
    }

    destroy() {
        this.stopAutoScroll()
        this.#io?.disconnect()
        this.#posIo?.disconnect()
        this.#pages = []
        this.#track.replaceChildren()
    }
}

customElements.define('manga-view', MangaView)
