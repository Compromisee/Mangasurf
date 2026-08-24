export const makeComicBook = ({ entries, loadBlob, getSize }, file) => {
    const cache = new Map()
    const urls = new Map()
    const load = async name => {
        if (cache.has(name)) return cache.get(name)
        const blob = await loadBlob(name)
        const src = URL.createObjectURL(blob)
        urls.set(name, src)
        cache.set(name, src)
        return src
    }
    const unload = name => {
        if (urls.has(name)) {
            URL.revokeObjectURL(urls.get(name))
            urls.delete(name)
        }
        cache.delete(name)
    }

    const exts = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.jxl', '.avif']
    const files = entries
        .map(entry => entry.filename)
        .filter(name => exts.some(ext => name.toLowerCase().endsWith(ext)))
        .sort(new Intl.Collator([], { numeric: true }).compare)
    if (!files.length) throw new Error('No supported image files in archive')

    // Parse chapter groupings from internal archive folders (e.g. "0001 - Chapter 1/001.jpg")
    const toc = []
    const chapterMap = new Map()

    for (const name of files) {
        const parts = name.split(/[\/\\]/)
        let chapterTitle = 'Chapter 1'
        if (parts.length >= 2 && parts[0]) {
            chapterTitle = parts[0].replace(/^\d+\s*[-–—:]\s*/, '').trim() || parts[0]
        }
        if (!chapterMap.has(chapterTitle)) {
            chapterMap.set(chapterTitle, name)
            toc.push({ label: chapterTitle, href: name })
        }
    }

    const book = {}
    book.getCover = () => load(files[0])
    book.metadata = { title: file.name }
    
    // Detailed sections with chapter groupings
    book.sections = files.map((name, idx) => {
        const parts = name.split(/[\/\\]/)
        let cleanLabel = `Page ${idx + 1}`
        let chapterName = ''
        if (parts.length >= 2 && parts[0]) {
            chapterName = parts[0].replace(/^\d+\s*[-–—:]\s*/, '').trim() || parts[0]
            const pageFile = parts[parts.length - 1].replace(/\.[^.]+$/, '')
            cleanLabel = `${chapterName} • ${pageFile}`
        }
        return {
            id: name,
            label: cleanLabel,
            chapter: chapterName,
            load: () => load(name),
            unload: () => unload(name),
            size: getSize(name),
        }
    })

    book.toc = toc.length > 1 ? toc : files.map(name => ({ label: name, href: name }))
    book.pageNames = book.sections.map(s => s.label)
    book.rendition = { layout: 'pre-paginated' }
    book.resolveHref = href => ({ index: book.sections.findIndex(s => s.id === href) })
    book.splitTOCHref = href => [href, null]
    book.getTOCFragment = doc => doc.documentElement
    book.destroy = () => {
        for (const url of urls.values()) {
            try { URL.revokeObjectURL(url) } catch {}
        }
        urls.clear()
        cache.clear()
    }
    return book
}
