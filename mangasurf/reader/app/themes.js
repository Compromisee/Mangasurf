/* themes.js — appearance: themes, accents, corners, and the dot matrix.
 *
 * These settings already existed in Python (`theme`, `accent`, `corners`,
 * `matrix`, `animations`, `columns`) and kept being saved and loaded after
 * v3.0.0 replaced the front-end. Nothing read them, so they silently did
 * nothing. This is what reads them.
 *
 * Palettes live in theme.css as `[data-theme=...]` blocks; this file only
 * flips attributes on <html>, which is why a theme change costs one style
 * recalculation and applies to the reader overlay at the same time.
 */

export const THEMES = {
    midnight: { label: 'Midnight', dark: true,  filter: 'dim' },
    mocha:    { label: 'Mocha',    dark: true,  filter: 'dim' },
    forest:   { label: 'Forest',   dark: true,  filter: 'dim' },
    plum:     { label: 'Plum',     dark: true,  filter: 'dim' },
    ocean:    { label: 'Ocean',    dark: true,  filter: 'dim' },
    oled:     { label: 'OLED',     dark: true,  filter: 'dimmer' },
    light:    { label: 'Light',    dark: false, filter: 'none' },
    paper:    { label: 'Paper',    dark: false, filter: 'none' },
}

export const THEME_ORDER = [
    'midnight', 'mocha', 'forest', 'plum', 'ocean', 'oled', 'light', 'paper',
]

export const ACCENTS = {
    blue:   'Blue',
    violet: 'Violet',
    teal:   'Teal',
    rose:   'Rose',
    amber:  'Amber',
    mint:   'Mint',
}

export const ACCENT_ORDER = ['blue', 'violet', 'teal', 'rose', 'amber', 'mint']

const root = () => document.documentElement

export const applyTheme = (name, el = root()) => {
    const theme = THEMES[name] ? name : 'midnight'
    el.dataset.theme = theme
    el.dataset.dark = String(!!THEMES[theme].dark)
    return THEMES[theme]
}

export const applyAccent = (name, el = root()) => {
    const accent = ACCENTS[name] ? name : 'blue'
    el.dataset.accent = accent
    return accent
}

export const applyCorners = (square, el = root()) => {
    el.dataset.corners = square ? 'square' : 'rounded'
    return !!square
}

export const applyAnimations = (on, el = root()) => {
    el.dataset.animations = on ? 'on' : 'off'
    return !!on
}

export const applyColumns = (count, el = root()) => {
    const n = Math.max(0, Math.min(8, parseInt(count, 10) || 0))
    if (n === 0) delete el.dataset.columns
    else el.dataset.columns = String(n)
    return n
}

/** Read a resolved custom property, for previews and tests. */
export const token = (name, el = root()) =>
    getComputedStyle(el).getPropertyValue(name).trim()

/* ─────────────────────────────────────────────────────── dot matrix ──── */

/* A decorative canvas field. Kept from the pre-v3 shell largely unchanged
 * because its costs were already thought through:
 *
 *   - 30fps, not 60: it is a background texture, and 600 arcs at 60fps is
 *     ~36,000 canvas operations a second for decoration.
 *   - MAX_DOTS caps the total; spacing widens on big screens instead of the
 *     count growing with area.
 *   - The colour is read on theme change, never inside the frame loop --
 *     getComputedStyle in a rAF callback forces a style recalc every frame.
 *   - Pauses on document.hidden and when the app is locked.
 */
export function createMatrix(canvas) {
    const ctx = canvas.getContext('2d', { alpha: true })
    let dots = []
    let raf = null
    let enabled = true
    let rgb = '255,255,255'
    let lastDraw = 0

    const TARGET_FPS = 30
    const FRAME_MS = 1000 / TARGET_FPS
    const MAX_DOTS = 420

    const readColour = () => {
        rgb = getComputedStyle(document.documentElement)
            .getPropertyValue('--matrix-dot').trim() || '255,255,255'
    }

    const resize = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
        const w = window.innerWidth
        const h = window.innerHeight
        canvas.width = Math.floor(w * dpr)
        canvas.height = Math.floor(h * dpr)
        canvas.style.width = w + 'px'
        canvas.style.height = h + 'px'
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

        let gap = 46
        const estimate = () => Math.ceil(w / gap) * Math.ceil(h / gap)
        while (estimate() > MAX_DOTS) gap += 6

        dots = []
        for (let x = gap / 2; x < w; x += gap)
            for (let y = gap / 2; y < h; y += gap)
                dots.push({ x, y, phase: Math.random() * Math.PI * 2,
                            speed: 0.4 + Math.random() * 0.8 })
        readColour()
    }

    const frame = now => {
        raf = requestAnimationFrame(frame)
        if (now - lastDraw < FRAME_MS) return
        lastDraw = now
        ctx.clearRect(0, 0, window.innerWidth, window.innerHeight)
        for (const dot of dots) {
            const alpha = 0.025 + 0.05 *
                (0.5 + 0.5 * Math.sin(dot.phase + now * 0.0006 * dot.speed))
            ctx.fillStyle = `rgba(${rgb},${alpha})`
            ctx.beginPath()
            ctx.arc(dot.x, dot.y, 1.3, 0, Math.PI * 2)
            ctx.fill()
        }
    }

    const start = () => {
        if (!enabled || raf || document.hidden) return
        resize()
        raf = requestAnimationFrame(frame)
    }

    const stop = () => {
        if (raf) cancelAnimationFrame(raf)
        raf = null
        ctx.clearRect(0, 0, window.innerWidth, window.innerHeight)
    }

    let resizeTimer = null
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimer)
        resizeTimer = setTimeout(() => { if (raf) resize() }, 160)
    })
    document.addEventListener('visibilitychange', () => {
        if (document.hidden) stop()
        else start()
    })

    return {
        set(on) {
            enabled = !!on
            canvas.hidden = !on
            if (on) start()
            else stop()
            return enabled
        },
        get enabled() { return enabled },
        get running() { return !!raf },
        get dotCount() { return dots.length },
        refreshColour: readColour,
        pause: stop,
        resume: start,
    }
}

/* ────────────────────────────────── search perspective grid wave ──── */

export function createSearchGridWave(canvas) {
    if (!canvas) return null
    const ctx = canvas.getContext('2d', { alpha: true })
    if (!ctx) return null
    let raf = null
    let enabled = true
    let running = false
    let lastDraw = 0
    let opacity = 1
    let targetOpacity = 1

    const TARGET_FPS = 30
    const FRAME_MS = 1000 / TARGET_FPS

    const resize = () => {
        const dpr = Math.min(window.devicePixelRatio || 1, 1.5)
        const parent = canvas.parentElement || document.querySelector('#search-view')
        const w = parent ? parent.clientWidth || window.innerWidth : window.innerWidth
        const h = parent ? parent.clientHeight || window.innerHeight : 600
        canvas.width = Math.floor(w * dpr)
        canvas.height = Math.floor(h * dpr)
        canvas.style.width = `${w}px`
        canvas.style.height = `${h}px`
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }

    const frame = now => {
        if (!running) return
        raf = requestAnimationFrame(frame)
        if (now - lastDraw < FRAME_MS) return
        lastDraw = now

        opacity += (targetOpacity - opacity) * 0.08
        if (opacity < 0.01 && targetOpacity === 0) {
            ctx.clearRect(0, 0, canvas.width, canvas.height)
            return
        }

        const parent = canvas.parentElement || document.querySelector('#search-view')
        const w = parent ? parent.clientWidth || window.innerWidth : window.innerWidth
        const h = parent ? parent.clientHeight || window.innerHeight : 600
        ctx.clearRect(0, 0, w, h)

        const rows = 18
        const cols = 32
        const horizonY = h * 0.20

        const accent = getComputedStyle(document.documentElement)
            .getPropertyValue('--accent').trim() || '#38bdf8'

        // Fullscreen 3D Perspective Wave Grid (Horizontal Waves)
        for (let r = 0; r < rows; r++) {
            const zNorm = (r + 1) / rows
            const yBase = horizonY + (h - horizonY) * (zNorm * zNorm)
            const scale = 0.25 + 0.75 * zNorm
            const rowAlpha = (0.04 + 0.22 * zNorm) * opacity

            ctx.beginPath()
            for (let c = 0; c < cols; c++) {
                const xNorm = (c / (cols - 1) - 0.5) * 2
                const x = w / 2 + xNorm * (w * 0.75) * scale
                const waveY = Math.sin(c * 0.38 + now * 0.0018) * Math.cos(r * 0.35 + now * 0.0014) * (20 * zNorm)
                const y = yBase + waveY

                if (c === 0) ctx.moveTo(x, y)
                else ctx.lineTo(x, y)
            }
            ctx.strokeStyle = `color-mix(in srgb, ${accent} ${Math.round(rowAlpha * 100)}%, transparent)`
            ctx.lineWidth = 1 + zNorm * 0.8
            ctx.stroke()
        }

        // Longitudinal Depth Grid Lines across full screen
        for (let c = 0; c < cols; c += 2) {
            const xNorm = (c / (cols - 1) - 0.5) * 2
            ctx.beginPath()
            for (let r = 0; r < rows; r++) {
                const zNorm = (r + 1) / rows
                const yBase = horizonY + (h - horizonY) * (zNorm * zNorm)
                const scale = 0.25 + 0.75 * zNorm
                const x = w / 2 + xNorm * (w * 0.75) * scale
                const waveY = Math.sin(c * 0.38 + now * 0.0018) * Math.cos(r * 0.35 + now * 0.0014) * (20 * zNorm)
                const y = yBase + waveY
                if (r === 0) ctx.moveTo(x, y)
                else ctx.lineTo(x, y)
            }
            ctx.strokeStyle = `color-mix(in srgb, ${accent} ${Math.round(0.10 * opacity * 100)}%, transparent)`
            ctx.lineWidth = 0.8
            ctx.stroke()
        }
    }

    const start = () => {
        if (!enabled || running || document.hidden) return
        running = true
        resize()
        raf = requestAnimationFrame(frame)
    }

    const stop = () => {
        running = false
        if (raf) cancelAnimationFrame(raf)
        raf = null
    }

    window.addEventListener('resize', () => { if (running) resize() })

    return {
        start,
        stop,
        setOpacity(val) { targetOpacity = Math.max(0, Math.min(1, val)) },
        get running() { return running },
    }
}
