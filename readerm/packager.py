"""Packaging downloaded chapters into CBZ / PDF / EPUB volumes."""
import sys

# Allow running this file directly (python readerm/packager.py, or an IDE's
# "Run file"). Without this the relative imports below have no parent package
# and raise ImportError before the module can do anything.
if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import readerm  # noqa: F401
    __package__ = "readerm"



import logging
import os
import re
import zipfile

from .utils import natural_sort_key, sanitize

logger = logging.getLogger(__name__)

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif")


def _chapter_images(chapter_dir):
    try:
        files = [
            os.path.join(chapter_dir, f)
            for f in os.listdir(chapter_dir)
            if f.lower().endswith(IMAGE_EXTS)
        ]
    except FileNotFoundError:
        return []
    return sorted(files, key=natural_sort_key)


def create_cbz(chapter_dirs, out_path):
    """Create a CBZ from one or more (chapter_dir, chapter_name) pairs.

    Multiple chapters are stored in per-chapter subfolders inside the archive
    so readers keep the correct page order.
    """
    pairs = [(d, n) for d, n in chapter_dirs if _chapter_images(d)]
    if not pairs:
        logger.warning("No images to pack into %s", out_path)
        return None

    single = len(pairs) == 1
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as zf:
        for idx, (chapter_dir, chapter_name) in enumerate(pairs, 1):
            prefix = "" if single else f"{idx:04d} - {sanitize(chapter_name)}/"
            for image in _chapter_images(chapter_dir):
                zf.write(image, prefix + os.path.basename(image))
    logger.info("Created CBZ: %s", out_path)
    return out_path


def create_pdf(chapter_dirs, out_path):
    """Create a PDF sized exactly to each page image (no borders)."""
    from fpdf import FPDF
    from PIL import Image

    pdf = FPDF()
    pdf.set_auto_page_break(auto=False)
    pages = 0

    for chapter_dir, _name in chapter_dirs:
        for image_file in _chapter_images(chapter_dir):
            try:
                with Image.open(image_file) as img:
                    if img.mode not in ("RGB", "L"):
                        img = img.convert("RGB")
                        source = image_file + "_rgb.jpg"
                        img.save(source, "JPEG", quality=95)
                    else:
                        source = image_file
                    w_px, h_px = img.size

                dpi = 96
                w_mm, h_mm = (w_px / dpi) * 25.4, (h_px / dpi) * 25.4
                pdf.add_page(format=(w_mm, h_mm))
                pdf.set_margins(0, 0, 0)
                pdf.image(source, x=0, y=0, w=w_mm, h=h_mm)
                pages += 1

                if source != image_file and os.path.exists(source):
                    os.remove(source)
            except Exception as e:
                logger.error("Failed to add %s to PDF: %s", image_file, e)

    if not pages:
        logger.warning("No images to pack into %s", out_path)
        return None
    pdf.output(out_path)
    logger.info("Created PDF: %s", out_path)
    return out_path


def create_epub(chapter_dirs, out_path, title):
    """Create an EPUB with one XHTML page per image, chapters in the TOC."""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(re.sub(r"\W+", "-", title.lower()))
    book.set_title(title)
    book.set_language("en")
    book.add_author("Mangasurf")

    spine, toc, page_no = ["nav"], [], 0
    media_types = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".gif": "image/gif", ".webp": "image/webp",
    }

    for chapter_dir, chapter_name in chapter_dirs:
        first_page = None
        for image_file in _chapter_images(chapter_dir):
            page_no += 1
            ext = os.path.splitext(image_file)[1].lower()
            with open(image_file, "rb") as f:
                data = f.read()
            book.add_item(epub.EpubItem(
                uid=f"img_{page_no}",
                file_name=f"images/page_{page_no:04d}{ext}",
                media_type=media_types.get(ext, "image/jpeg"),
                content=data,
            ))
            page = epub.EpubHtml(title=f"Page {page_no}", file_name=f"page_{page_no:04d}.xhtml")
            page.content = (
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                f"<title>Page {page_no}</title>"
                "<style>body{margin:0;padding:0;text-align:center;background:#000}"
                "img{max-width:100%;max-height:100vh;object-fit:contain}</style></head>"
                f'<body><img src="images/page_{page_no:04d}{ext}" alt="Page {page_no}"/></body></html>'
            )
            book.add_item(page)
            spine.append(page)
            if first_page is None:
                first_page = page

        if first_page is not None:
            toc.append(epub.Link(first_page.file_name, chapter_name, f"ch_{len(toc)}"))

    if page_no == 0:
        logger.warning("No images to pack into %s", out_path)
        return None

    book.toc = toc
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine
    epub.write_epub(out_path, book, {})
    logger.info("Created EPUB: %s", out_path)
    return out_path


PACKAGERS = {
    "cbz": lambda dirs, path, title: create_cbz(dirs, path),
    "pdf": lambda dirs, path, title: create_pdf(dirs, path),
    "epub": create_epub,
}

EXTENSIONS = {"cbz": ".cbz", "pdf": ".pdf", "epub": ".epub"}
