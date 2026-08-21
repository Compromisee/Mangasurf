/* keys.js — named actions, a rebindable keymap, and the settings editor.
 *
 * The reader used to dispatch keys from a `switch (e.key)` with the bindings
 * written into the case labels. That works right up until someone wants a
 * different key: the binding, the action and the help text lived in three
 * places that had to be edited together, and the help sheet had already
 * drifted (it advertised keys the switch did not handle).
 *
 * Here there is one list of ACTIONS. It is the single source of the defaults,
 * the settings page, the help sheet and the dispatcher, so the three cannot
 * disagree again.
 *
 * A binding is stored as a normalised string like `ctrl+shift+k`, `arrowleft`
 * or `?`. Modifier order is fixed at ctrl+alt+shift+meta so `shift+ctrl+k`
 * and `ctrl+shift+k` are the same binding rather than two that silently
 * conflict.
 */

/** Every rebindable action, in the order the settings page lists them. */
export const ACTIONS = [
    { id: 'close',        group: 'Reader',    label: 'Close the reader',        keys: ['Escape'] },
    { id: 'pageLeft',     group: 'Navigate',  label: 'Page left',               keys: ['ArrowLeft', 'a'] },
    { id: 'pageRight',    group: 'Navigate',  label: 'Page right',              keys: ['ArrowRight', 'd'] },
    { id: 'next',         group: 'Navigate',  label: 'Next page / scroll down', keys: ['ArrowDown', 'j', ' '] },
    { id: 'prev',         group: 'Navigate',  label: 'Previous page / up',      keys: ['ArrowUp', 'k'] },
    { id: 'first',        group: 'Navigate',  label: 'First page',              keys: ['Home'] },
    { id: 'last',         group: 'Navigate',  label: 'Last page',               keys: ['End'] },
    { id: 'prevChapter',  group: 'Navigate',  label: 'Previous chapter',        keys: ['['] },
    { id: 'nextChapter',  group: 'Navigate',  label: 'Next chapter',            keys: [']'] },
    { id: 'jumpPage',     group: 'Navigate',  label: 'Jump to page…',           keys: ['g'] },
    { id: 'bookmark',     group: 'Marks',     label: 'Bookmark this page',      keys: ['b'] },
    { id: 'markedTab',    group: 'Marks',     label: 'Show bookmarked pages',   keys: ['B'] },
    { id: 'pages',        group: 'Panels',    label: 'Toggle the page list',    keys: ['p'] },
    { id: 'chapters',     group: 'Panels',    label: 'Toggle the chapter list', keys: ['c'] },
    { id: 'shortcuts',    group: 'Panels',    label: 'Keyboard shortcuts',      keys: ['?'] },
    { id: 'mode',         group: 'View',      label: 'Cycle reading mode',      keys: ['w'] },
    { id: 'fullscreen',   group: 'View',      label: 'Fullscreen',              keys: ['f'] },
    { id: 'immersive',    group: 'View',      label: 'Hide the toolbars',       keys: ['i'] },
    { id: 'zen',          group: 'View',      label: 'Minimalist mode',         keys: ['m'] },
    { id: 'theme',        group: 'View',      label: 'Cycle theme',             keys: ['t'] },
    { id: 'zoomIn',       group: 'View',      label: 'Zoom in',                 keys: ['ctrl+='] },
    { id: 'zoomOut',      group: 'View',      label: 'Zoom out',                keys: ['ctrl+-'] },
    { id: 'zoomReset',    group: 'View',      label: 'Reset zoom',              keys: ['ctrl+0'] },
    { id: 'autoScroll',   group: 'Auto',      label: 'Start / stop auto-scroll', keys: ['s'] },
    { id: 'faster',       group: 'Auto',      label: 'Auto-scroll faster',      keys: ['+', '='] },
    { id: 'slower',       group: 'Auto',      label: 'Auto-scroll slower',      keys: ['-', '_'] },
]

export const ACTION_BY_ID = Object.fromEntries(ACTIONS.map(a => [a.id, a]))

/**
 * Ready-made layouts. Each holds only what it changes; everything else falls
 * back to the default binding, so a preset can never leave an action unbound.
 *
 * The names are the conventions they copy, not inventions: `vim` is hjkl,
 * `wasd` is the gamepad-style layout people already use in comic readers, and
 * `oneHand` keeps every common action reachable from the arrow-key cluster
 * for reading with one hand on a laptop.
 */
export const PRESETS = {
    default: { label: 'Mangasurf default', keys: {} },
    vim: {
        label: 'Vim (hjkl)',
        keys: {
            pageLeft: ['h'], pageRight: ['l'], next: ['j', ' '], prev: ['k'],
            first: ['g'], last: ['G'], jumpPage: [':'],
            prevChapter: ['['], nextChapter: [']'],
        },
    },
    wasd: {
        label: 'WASD',
        keys: {
            pageLeft: ['a'], pageRight: ['d'], next: ['s', ' '], prev: ['w'],
            mode: ['m'], zen: ['q'], autoScroll: ['e'],
        },
    },
    oneHand: {
        label: 'One hand (arrows only)',
        keys: {
            pageLeft: ['ArrowLeft'], pageRight: ['ArrowRight'],
            next: ['ArrowDown', ' '], prev: ['ArrowUp'],
            prevChapter: ['shift+arrowleft'], nextChapter: ['shift+arrowright'],
            first: ['ctrl+arrowup'], last: ['ctrl+arrowdown'],
        },
    },
}

export const PRESET_ORDER = ['default', 'vim', 'wasd', 'oneHand']

const MODIFIER_ORDER = ['ctrl', 'alt', 'shift', 'meta']

/** Keys that are a modifier themselves and can never be a binding alone. */
const BARE_MODIFIERS = new Set(['Control', 'Alt', 'Shift', 'Meta'])

/**
 * Canonical text for a binding.
 *
 * Single printable characters keep their case, because `b` and `B` are two
 * different bindings a user can reasonably want. Named keys are lowercased so
 * `ArrowLeft` and `arrowleft` cannot both exist.
 */
export function normalise(binding) {
    if (binding === ' ') return ' '          // the spacebar is a binding
    if (!binding) return ''
    const text = String(binding)
    // Splitting on "+" and dropping empties turned a lone " " into "+",
    // which silently merged Space with the auto-scroll-faster binding: both
    // ended up as the same key and the conflict list flagged them. Trimming
    // is what destroys the space, so the two literal keys are handled first.
    if (text === '+') return '+'
    const parts = text.split('+').map(p => p.trim()).filter(Boolean)
    if (!parts.length) return '+'
    const key = parts.pop()
    const mods = new Set(parts.map(p => p.toLowerCase()))
    // "ctrl+space" is written out, so turn the word back into the character.
    const base = /^space$/i.test(key) ? ' '
        : (key.length === 1 ? key : key.toLowerCase())
    return [...MODIFIER_ORDER.filter(m => mods.has(m)), base].join('+')
}

/** The binding for a real KeyboardEvent, or '' if it is only a modifier. */
export function bindingFor(event) {
    if (!event || BARE_MODIFIERS.has(event.key)) return ''
    const mods = []
    if (event.ctrlKey) mods.push('ctrl')
    if (event.altKey) mods.push('alt')
    // Shift is folded into the character for printable keys -- `?` is already
    // shift+/ and asking users to press ctrl+shift+? would be wrong.
    if (event.shiftKey && event.key.length > 1) mods.push('shift')
    if (event.metaKey) mods.push('meta')
    const base = event.key.length === 1 ? event.key : event.key.toLowerCase()
    return [...mods, base].join('+')
}

const PRETTY = {
    arrowleft: '←', arrowright: '→', arrowup: '↑', arrowdown: '↓',
    ' ': 'Space', escape: 'Esc', enter: 'Enter', home: 'Home', end: 'End',
    pageup: 'PgUp', pagedown: 'PgDn', backspace: '⌫', tab: 'Tab',
    ctrl: 'Ctrl', alt: 'Alt', shift: 'Shift', meta: 'Meta',
}

/** Human-readable form for a keycap.
 *
 * An uppercase letter is spelled "Shift + B", not "B". Both `b` and `B` are
 * real bindings -- bookmark and show-bookmarks use exactly that pair -- and
 * uppercasing every single character rendered the two rows identically, so
 * the settings page showed the same keycap twice and looked like a bug.
 */
export function pretty(binding) {
    if (binding === ' ') return 'Space'
    const parts = String(binding || '').split('+')
    const out = []
    for (const part of parts) {
        if (part === '') continue
        if (part === ' ') { out.push('Space'); continue }
        const named = PRETTY[part.toLowerCase()] || PRETTY[part]
        if (named && part.length > 1) { out.push(named); continue }
        if (part.length === 1 && /[A-Z]/.test(part)) {
            out.push('Shift', part)
        } else {
            out.push(part.length === 1 ? part.toUpperCase() : (named || part))
        }
    }
    // A trailing empty part means the binding ended in "+", i.e. the key is
    // literally the plus sign.
    if (!out.length) return '+'
    return out.join(' + ')
}

export const defaults = () =>
    Object.fromEntries(ACTIONS.map(a => [a.id, a.keys.map(normalise)]))

/**
 * Merge a saved map over the defaults.
 *
 * A saved map only holds what the user changed, so an action added in a later
 * version still arrives with its default binding instead of no binding at
 * all -- which is what happens if the stored object is simply used as-is.
 */
export function resolve(saved) {
    const map = defaults()
    for (const [id, keys] of Object.entries(saved || {})) {
        if (!ACTION_BY_ID[id]) continue          // dropped in a later version
        map[id] = (Array.isArray(keys) ? keys : [keys])
            .map(normalise).filter(Boolean)
    }
    return map
}

/** binding -> [actionId], for dispatch and for spotting conflicts. */
export function index(map) {
    const out = new Map()
    for (const [id, keys] of Object.entries(map || {}))
        for (const key of keys) {
            if (!out.has(key)) out.set(key, [])
            out.get(key).push(id)
        }
    return out
}

/** Every binding claimed by more than one action. */
export function conflicts(map) {
    return [...index(map)]
        .filter(([, ids]) => ids.length > 1)
        .map(([key, ids]) => ({ key, actions: ids }))
}

/* ── the controller ───────────────────────────────────────────────────── */

export function createKeymap({ call, esc, toast, settingsKey = 'reader_keymap' }) {
    let map = defaults()
    let lookup = index(map)
    const handlers = new Map()
    let capturing = null

    const setMap = next => {
        map = next
        lookup = index(map)
    }

    return {
        get map() { return map },
        get lookup() { return lookup },

        /** Point an action id at a function. */
        on(id, fn) { handlers.set(id, fn); return this },

        load(settings) {
            setMap(resolve(settings?.[settingsKey]))
            return map
        },

        async save() {
            // Only the differences are persisted, so defaults can change in a
            // later release without every user being pinned to the old ones.
            const base = defaults()
            const diff = {}
            for (const [id, keys] of Object.entries(map))
                if (keys.join('|') !== (base[id] || []).join('|')) diff[id] = keys
            await call('set_settings', { [settingsKey]: diff })
            return diff
        },

        /** Run whatever is bound to this event. Returns true if it handled it. */
        handle(event) {
            const binding = bindingFor(event)
            if (!binding) return false
            const ids = lookup.get(binding)
            if (!ids || !ids.length) return false
            let ran = false
            for (const id of ids) {
                const fn = handlers.get(id)
                if (fn) { fn(event); ran = true }
            }
            return ran
        },

        rebind(id, keys) {
            if (!ACTION_BY_ID[id]) return { ok: false, error: 'No such action' }
            setMap({ ...map, [id]: keys.map(normalise).filter(Boolean) })
            return { ok: true }
        },

        reset(id) {
            if (id) setMap({ ...map, [id]: defaults()[id] })
            else setMap(defaults())
            return map
        },

        /** Apply a named preset over the defaults. */
        preset(name) {
            const chosen = PRESETS[name]
            if (!chosen) return { ok: false, error: 'No such preset' }
            setMap(resolve(chosen.keys))
            return { ok: true, map }
        },

        /** Which preset the current map matches, or '' when it is custom. */
        matchingPreset() {
            const now = JSON.stringify(
                Object.entries(map).sort(([a], [b]) => a < b ? -1 : 1))
            for (const name of PRESET_ORDER) {
                const candidate = resolve(PRESETS[name].keys)
                const text = JSON.stringify(
                    Object.entries(candidate).sort(([a], [b]) => a < b ? -1 : 1))
                if (text === now) return name
            }
            return ''
        },

        conflicts: () => conflicts(map),

        /** Capture the next keystroke into an action. */
        capture(id, onDone) { capturing = { id, onDone } },
        get capturing() { return capturing },
        cancelCapture() { capturing = null },
        finishCapture(event) {
            if (!capturing) return false
            const binding = bindingFor(event)
            if (!binding) return true            // a lone modifier: keep waiting
            const { id, onDone } = capturing
            capturing = null
            if (binding === 'escape') { onDone?.(null); return true }
            setMap({ ...map, [id]: [binding] })
            onDone?.(binding)
            return true
        },
    }
}
