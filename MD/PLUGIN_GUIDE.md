# 🧩 Modular Scraper Plugin Guide for Mangasurf

How to write, test, and install custom Python manga scraper plugins for **Mangasurf**.

---

## 📂 Plugin Directory Locations

Mangasurf automatically discovers and hot-reloads scraper plugins from:
1. **Workspace / Built-in**: `mangasurf/sources/customsources/*.py`
2. **User Data Folder**: `~/.mangasurf/sources/*.py`

Any `.py` file containing a subclass of `Source` placed in these directories will **automatically appear in the GUI, TUI, CLI, and OPDS server without needing to restart the app**!

---

## 🛠️ Writing a Custom Source (`mysource.py`)

Create a file named `mysource.py` (e.g. `~/.mangasurf/sources/mysource.py`):

```python
"""Custom Scraper Plugin for Example Manga."""

import json
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

from mangasurf.sources.base import Source, ScrapeError, classify_type

SITE = "https://example-manga.com"

class ExampleMangaSource(Source):
    # Unique identifier (lowercase alphanumeric)
    id = "examplemanga"
    name = "Example Manga"
    base_url = SITE
    domains = ("example-manga.com", "www.example-manga.com")

    # Capabilities
    supports_search = True
    supports_browse = True
    supports_genres = True
    adult_only = False
    needs_flaresolverr = False
    cover_needs_referer = True  # True if cover CDN needs Referer header

    def search(self, query: str, limit: int = 24, page: int = 1, **kwargs) -> list:
        """Search the website for manga matching query."""
        url = f"{self.base_url}/search?q={quote(query)}&page={page}"
        resp = self.fetch(url, timeout=12)
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for card in soup.select(".manga-card"):
            link_el = card.select_one("a[href]")
            if not link_el:
                continue
            title = card.select_one(".title").get_text(strip=True)
            cover = card.select_one("img")["src"]
            href = urljoin(self.base_url, link_el["href"])
            
            results.append(self._result(
                title=title,
                url=href,
                cover=cover,
                series_type=classify_type(text=title) or "Manga"
            ))
            if len(results) >= limit:
                break
        return results

    def browse(self, sort: str = "Trending", genre: str = None, page: int = 1, limit: int = 24, **kwargs) -> list:
        """Browse trending or genre feeds."""
        url = f"{self.base_url}/popular?page={page}"
        resp = self.fetch(url, timeout=12)
        if resp.status_code != 200:
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for card in soup.select(".manga-card"):
            title = card.select_one(".title").get_text(strip=True)
            cover = card.select_one("img")["src"]
            href = urljoin(self.base_url, card.select_one("a")["href"])
            results.append(self._result(title=title, url=href, cover=cover))
            if len(results) >= limit:
                break
        return results

    def get_manga_info(self, manga_url: str) -> dict:
        """Extract series metadata (synopsis, authors, tags, cover)."""
        resp = self.fetch(manga_url, timeout=12)
        if resp.status_code != 200:
            raise ScrapeError(f"HTTP {resp.status_code}")
        
        soup = BeautifulSoup(resp.text, "html.parser")
        title = soup.select_one("h1").get_text(strip=True)
        cover = soup.select_one(".cover img")["src"]
        desc = soup.select_one(".synopsis").get_text(strip=True)
        tags = [t.get_text(strip=True) for t in soup.select(".genres a")]
        
        return {
            "url": manga_url,
            "title": title,
            "cover": cover,
            "description": desc,
            "tags": tags,
            "status": "Ongoing",
            "authors": ["Author Name"],
            "artists": [],
            "source": self.id,
            "source_name": self.name,
        }

    def get_chapters(self, manga_url: str) -> list:
        """List all available chapters (oldest first)."""
        resp = self.fetch(manga_url, timeout=12)
        if resp.status_code != 200:
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        chapters = []
        for a in soup.select(".chapter-list a[href]"):
            name = a.get_text(strip=True)
            href = urljoin(self.base_url, a["href"])
            chapters.append({
                "url": href,
                "name": name,
                "referer": manga_url,
                "source": self.id,
            })
        
        chapters.reverse()  # Ensure oldest first
        return chapters

    def get_chapter_images(self, chapter) -> list:
        """Return full list of high-res image URLs for a chapter."""
        chapter_url = self._chapter_url(chapter)
        resp = self.fetch(chapter_url, timeout=12)
        if resp.status_code != 200:
            return []
        
        soup = BeautifulSoup(resp.text, "html.parser")
        images = []
        for img in soup.select(".reader img[src]"):
            u = img["src"].strip()
            if u.startswith("//"):
                u = "https:" + u
            images.append(u)
        return images
```

---

## ⚡ Hot-Reloading in Mangasurf GUI

1. Open Mangasurf Desktop GUI.
2. Go to **Settings → Sources**.
3. Click the **"Reload Plugins & Sources"** button (`#btn-reload-sources`).
4. Your custom source will immediately show up with its active indicator and will participate in omnibar search, discovery, and downloading!
