/* shelves.js — the library shelf tree: folders, tags, pins and locks.
 *
 * Kept out of app.js because app.js was already ~2400 lines and this is a
 * self-contained feature: it owns one aside, two dialogs and a handful of
 * endpoints, and talks to the rest of the app through the `call` and `toast`
 * functions it is handed.
 *
 * Two rules the Python side enforces and this file relies on rather than
 * duplicating:
 *
 *   1. A locked shelf arrives with `books: []` and `children: []`. The titles
 *      are never sent to the page, so there is nothing here to leak even if
 *      the markup were wrong. `book_count` still arrives so the row can say
 *      how much is hidden.
 *   2. Folders arrive collapsed. The user asked that folders not expand, so
 *      the open set starts empty and only grows when a twisty is clicked.
 */

const $ = sel => document.querySelector(sel)

const COLOURS = ['', '#7aa2f7', '#bb9af7', '#73daca', '#f7768e', '#e0af68', '#9ece6a']

export function createShelves({ call, esc, toast, onOpenBook, onFilter }) {
    const state = {
        tree: { shelves: [], unfiled: [], tags: [] },
        open: new Set(),        // expanded shelf ids, session only
        selected: '',           // '' = show everything
        tags: new Set(),        // active tag filter
        editing: null,          // shelf being edited, or null for "new"
        unlocking: null,
        visible: true,
    }

    /* ── data ─────────────────────────────────────────────────────────── */

    async function refresh() {
        const res = await call('shelf_tree')
        if (res?.ok) state.tree = res
        render()
        return state.tree
    }

    /** Every shelf as a flat list, for the "Inside" picker. */
    function flatten(nodes = state.tree.shelves, depth = 0, out = []) {
        for (const node of nodes) {
            out.push({ id: node.id, name: node.name, depth })
            // A locked shelf reports no children, so this stops there --
            // which is correct: you cannot file something into a shelf you
            // cannot open.
            flatten(node.children || [], depth + 1, out)
        }
        return out
    }

    /** Books on the selected shelf and everything under it. */
    function booksUnder(node) {
        const out = [...(node.books || [])]
        for (const child of node.children || []) out.push(...booksUnder(child))
        return out
    }

    function findNode(id, nodes = state.tree.shelves) {
        for (const node of nodes) {
            if (node.id === id) return node
            const hit = findNode(id, node.children || [])
            if (hit) return hit
        }
        return null
    }

    /** Which books the grid should show, given the current selection. */
    function visibleBooks(all) {
        if (!state.selected) return all
        const node = findNode(state.selected)
        if (!node) return all
        const keys = new Set(booksUnder(node).map(b => b.key))
        return all.filter(b => keys.has(b.key))
    }

    /* ── rendering ────────────────────────────────────────────────────── */

    function matchesTags(node) {
        if (!state.tags.size) return true
        const mine = new Set(node.tags || [])
        for (const tag of state.tags) if (mine.has(tag)) return true
        // A parent stays visible when a descendant matches, otherwise
        // filtering by tag would hide the path to the thing you asked for.
        return (node.children || []).some(matchesTags)
    }

    function rowFor(node) {
        const open = state.open.has(node.id)
        const kids = (node.children || []).length
        const hasKids = kids > 0 || (node.books || []).length > 0 || node.hidden
        const cls = ['tree-row', open ? 'open' : '', node.locked ? 'locked' : '',
                     state.selected === node.id ? 'on' : ''].filter(Boolean).join(' ')
        const count = node.hidden
            ? `${node.book_count || 0} hidden`
            : String(node.book_count || 0)
        return `
        <button class="${cls}" role="treeitem" data-shelf="${esc(node.id)}"
                aria-expanded="${hasKids ? open : ''}"
                aria-selected="${state.selected === node.id}"
                style="padding-left:${6 + (node.depth || 0) * 13}px">
          <span class="twisty" data-twisty="${esc(node.id)}">${
              hasKids ? '<span class="mi">chevron_right</span>' : ''}</span>
          <span class="mi fico" style="${node.colour ? `color:${esc(node.colour)}` : ''}"
                >${node.locked ? 'folder_off' : (open ? 'folder_open' : 'folder')}</span>
          <span class="tname">${esc(node.name)}</span>
          ${(node.tags || []).length
              ? `<span class="tree-tags" title="${esc((node.tags || []).join(', '))}">`
                + (node.tags || []).slice(0, 3).map(() => '<i></i>').join('') + '</span>'
              : ''}
          ${node.pinned ? '<span class="mi tpin" title="Pinned">push_pin</span>' : ''}
          ${node.locked ? '<span class="mi tlock" title="Locked">lock</span>' : ''}
          <span class="tcount">${esc(count)}</span>
        </button>`
    }

    function bookRow(book, depth) {
        return `
        <button class="tree-row tree-book" role="treeitem"
                data-book="${esc(book.items?.[0]?.path || '')}"
                style="padding-left:${6 + depth * 13}px">
          <span class="leaf-dot"></span>
          <span class="mi fico">menu_book</span>
          <span class="tname">${esc(book.title || 'Untitled')}</span>
        </button>`
    }

    function branch(nodes) {
        let html = ''
        for (const node of nodes) {
            if (!matchesTags(node)) continue
            html += rowFor(node)
            if (state.open.has(node.id) && !node.hidden) {
                html += branch(node.children || [])
                for (const book of node.books || [])
                    html += bookRow(book, (node.depth || 0) + 1)
            }
        }
        return html
    }

    function render() {
        const body = $('#tree-body')
        const shelves = state.tree.shelves || []
        if (body) {
            body.innerHTML = branch(shelves)
            const empty = $('#tree-empty')
            if (empty) empty.hidden = shelves.length > 0
        }

        const hList = $('#h-shelves-list')
        const hCount = $('#h-shelves-count')
        if (hCount) hCount.textContent = shelves.length
        if (hList) {
            hList.innerHTML = shelves.map(s => {
                const isSelected = state.selected === s.id
                const isLocked = !!s.locked
                const colour = s.colour ? `style="border-color:${esc(s.colour)}"` : ''
                return `
                <button class="h-shelf-pill ${isSelected ? 'on' : ''}" data-shelf-id="${esc(s.id)}" ${colour} type="button">
                    <span class="mi">${isLocked ? 'lock' : 'folder'}</span>
                    <span>${esc(s.name)}</span>
                    <span class="h-badge">${s.book_count ?? 0}</span>
                </button>`
            }).join('')
        }

        const bar = $('#shelf-tagbar')
        if (bar) {
            const tags = state.tree.tags || []
            bar.hidden = !tags.length
            bar.innerHTML = tags.map(t => `
                <button class="tag-pill${state.tags.has(t.tag) ? ' on' : ''}"
                        data-tag="${esc(t.tag)}" aria-pressed="${state.tags.has(t.tag)}"
                >${esc(t.tag)} ${t.count}</button>`).join('')
        }
        onFilter?.()
    }

    /* ── the editor dialog ────────────────────────────────────────────── */

    function paintColours(chosen) {
        const box = $('#shelf-colour')
        if (!box) return
        box.innerHTML = COLOURS.map(c => `
            <button type="button" role="radio" data-colour="${esc(c)}"
                    aria-checked="${c === chosen}"
                    class="${c === chosen ? 'on' : ''}"
                    title="${c ? esc(c) : 'No colour'}"
                    style="background:${c || 'var(--surface-3)'}"></button>`).join('')
    }

    function openEditor(shelf) {
        state.editing = shelf || null
        $('#shelf-dlg-title').textContent = shelf ? 'Edit shelf' : 'New shelf'
        $('#shelf-name').value = shelf?.name || ''
        $('#shelf-tags').value = (shelf?.tags || []).join(', ')
        $('#shelf-pinned').checked = !!shelf?.pinned
        $('#shelf-locked').checked = !!shelf?.locked
        $('#shelf-pin-open').checked = shelf ? !!shelf.pin_to_open : true
        $('#shelf-pass').value = ''
        $('#shelf-lock-fields').hidden = !shelf?.locked
        $('#shelf-delete').hidden = !shelf
        paintColours(shelf?.colour || '')
        setError('')

        const picker = $('#shelf-parent')
        const options = flatten().filter(o => o.id !== shelf?.id)
        picker.innerHTML = '<option value="">Top level</option>'
            + options.map(o =>
                `<option value="${esc(o.id)}">${'\u00a0'.repeat(o.depth * 2)}${esc(o.name)}</option>`).join('')
        picker.value = shelf?.parent || ''

        $('#shelf-dlg').hidden = false
        $('#shelf-name').focus()
    }

    const setError = text => {
        const box = $('#shelf-err')
        box.textContent = text || ''
        box.hidden = !text
    }

    async function save() {
        const name = $('#shelf-name').value.trim()
        if (!name) return setError('Give the shelf a name')
        const colour = $('#shelf-colour .on')?.dataset.colour || ''
        const tags = $('#shelf-tags').value
        const parent = $('#shelf-parent').value || ''
        const pinned = $('#shelf-pinned').checked
        const wantLock = $('#shelf-locked').checked
        const pass = $('#shelf-pass').value
        const pinOpen = $('#shelf-pin-open').checked

        let id = state.editing?.id
        if (!id) {
            const res = await call('shelf_create', name, parent, colour, tags, pinned)
            if (!res?.ok) return setError(res?.error || 'Could not create the shelf')
            id = res.shelf.id
        } else {
            const renamed = await call('shelf_rename', id, name)
            if (!renamed?.ok) return setError(renamed?.error || 'Could not rename')
            const moved = await call('shelf_set_parent', id, parent)
            if (!moved?.ok) return setError(moved?.error || 'Could not move the shelf')
            await call('shelf_update', id, { colour, tags, pinned })
        }

        if (wantLock && pass) {
            const res = await call('shelf_set_lock', id, pass, pinOpen)
            if (!res?.ok) return setError(res?.error || 'Could not lock the shelf')
        } else if (wantLock && !state.editing?.locked) {
            return setError('Choose a passcode, or turn the lock off')
        } else if (!wantLock && state.editing?.locked) {
            // Removing a lock needs the passcode, which is not in this form:
            // send the user through the unlock dialog instead of silently
            // leaving the lock in place.
            const res = await call('shelf_clear_lock', id, pass)
            if (!res?.ok) return setError(res?.error
                || 'Enter the current passcode to remove the lock')
        }

        $('#shelf-dlg').hidden = true
        await refresh()
        toast?.(state.editing ? 'Shelf updated' : 'Shelf created')
    }

    async function remove() {
        const shelf = state.editing
        if (!shelf) return
        const res = await call('shelf_delete', shelf.id, false)
        if (!res?.ok) return setError(res?.error || 'Could not delete')
        $('#shelf-dlg').hidden = true
        state.open.delete(shelf.id)
        if (state.selected === shelf.id) state.selected = ''
        await refresh()
        toast?.('Shelf deleted. Its books stayed in the library.')
    }

    /* ── unlocking ────────────────────────────────────────────────────── */

    function askUnlock(node) {
        state.unlocking = node
        $('#shelf-unlock-name').textContent = node.name
        $('#shelf-unlock-pass').value = ''
        const err = $('#shelf-unlock-err')
        err.hidden = true
        $('#shelf-unlock').hidden = false
        $('#shelf-unlock-pass').focus()
    }

    async function tryUnlock() {
        const node = state.unlocking
        if (!node) return
        const res = await call('shelf_unlock', node.id, $('#shelf-unlock-pass').value)
        const err = $('#shelf-unlock-err')
        if (!res?.ok) {
            err.textContent = res?.error || 'Wrong passcode'
            err.hidden = false
            return
        }
        $('#shelf-unlock').hidden = true
        state.open.add(node.id)
        await refresh()
    }

    /* ── events ───────────────────────────────────────────────────────── */

    function toggle(id) {
        if (state.open.has(id)) state.open.delete(id)
        else state.open.add(id)
        render()
    }

    function wire() {
        const body = $('#tree-body')
        if (!body) return

        // Horizontal shelves bar wiring
        $('#horizontal-shelves-bar')?.addEventListener('click', e => {
            const btn = e.target.closest('.h-shelf-pill')
            if (!btn) return
            const shelfId = btn.dataset.shelfId || ''
            if (shelfId) {
                const node = findNode(shelfId)
                if (node && node.locked && node.pin_to_open) return askUnlock(node)
            }
            state.selected = state.selected === shelfId ? '' : shelfId
            render()
        })

        body.addEventListener('click', async e => {
            const bookBtn = e.target.closest('[data-book]')
            if (bookBtn) return onOpenBook?.(bookBtn.dataset.book)

            const row = e.target.closest('[data-shelf]')
            if (!row) return
            const node = findNode(row.dataset.shelf)
            if (!node) return

            const onTwisty = !!e.target.closest('[data-twisty]')
            // A locked shelf that asks for its PIN opens the dialog however
            // it was clicked; one locked without "ask every time" simply
            // stays collapsed and marked until deliberately expanded.
            if (node.locked && node.pin_to_open) return askUnlock(node)
            if (onTwisty) return toggle(node.id)

            state.selected = state.selected === node.id ? '' : node.id
            if (state.selected && !node.locked) state.open.add(node.id)
            render()
        })

        body.addEventListener('contextmenu', e => {
            const row = e.target.closest('[data-shelf]')
            if (!row) return
            e.preventDefault()
            const node = findNode(row.dataset.shelf)
            if (node) openEditor(node)
        })

        body.addEventListener('keydown', e => {
            const row = e.target.closest('[data-shelf]')
            if (!row) return
            const node = findNode(row.dataset.shelf)
            if (!node) return
            if (e.key === 'ArrowRight' && !state.open.has(node.id)) {
                e.preventDefault(); toggle(node.id)
            } else if (e.key === 'ArrowLeft' && state.open.has(node.id)) {
                e.preventDefault(); toggle(node.id)
            } else if (e.key === 'F2') {
                e.preventDefault(); openEditor(node)
            }
        })

        $('#shelf-tagbar')?.addEventListener('click', e => {
            const pill = e.target.closest('[data-tag]')
            if (!pill) return
            const tag = pill.dataset.tag
            if (state.tags.has(tag)) state.tags.delete(tag)
            else state.tags.add(tag)
            render()
        })

        $('#shelf-new')?.addEventListener('click', () => openEditor(null))
        $('#shelf-lock-all')?.addEventListener('click', async () => {
            await call('shelf_lock_now', '')
            state.open.clear()
            await refresh()
            toast?.('Every shelf locked')
        })
        $('#shelf-cancel')?.addEventListener('click', () => { $('#shelf-dlg').hidden = true })
        $('#shelf-save')?.addEventListener('click', save)
        $('#shelf-delete')?.addEventListener('click', remove)
        $('#shelf-locked')?.addEventListener('change', e => {
            $('#shelf-lock-fields').hidden = !e.target.checked
        })
        $('#shelf-colour')?.addEventListener('click', e => {
            const swatch = e.target.closest('[data-colour]')
            if (swatch) paintColours(swatch.dataset.colour)
        })
        $('#shelf-unlock-cancel')?.addEventListener('click', () => {
            $('#shelf-unlock').hidden = true
        })
        $('#shelf-unlock-go')?.addEventListener('click', tryUnlock)
        $('#shelf-unlock-pass')?.addEventListener('keydown', e => {
            if (e.key === 'Enter') tryUnlock()
        })
        $('#shelf-name')?.addEventListener('keydown', e => {
            if (e.key === 'Enter') save()
        })

        const toggleBtn = $('#lib-tree-toggle')
        toggleBtn?.addEventListener('click', () => {
            state.visible = !state.visible
            document.querySelector('.lib-split')?.classList.toggle('no-tree', !state.visible)
            toggleBtn.setAttribute('aria-pressed', String(state.visible))
        })

        document.addEventListener('keydown', e => {
            if (e.key !== 'Escape') return
            for (const id of ['#shelf-dlg', '#shelf-unlock']) {
                const el = $(id)
                if (el && !el.hidden) { el.hidden = true; e.stopPropagation(); return }
            }
        })
    }

    return { refresh, render, wire, visibleBooks, openEditor, state, findNode }
}
