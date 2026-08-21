"""Built-in offline Manga, Manhwa, and Hentai database index for Mangasurf.

Provides instant search suggestions, offline browsing, and metadata lookup.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# Comprehensive curated seed database covering popular SFW and NSFW series
DATABASE_ENTRIES: List[Dict[str, Any]] = [
    # --- SFW Manga & Manhwa ---
    {
        "id": "db_sfw_01",
        "title": "Solo Leveling",
        "alt_titles": ["Na Honjaman Rebeleop", "Only I Level Up", "나 혼자만 레벨업"],
        "type": "Manhwa",
        "status": "Completed",
        "is_nsfw": False,
        "authors": ["Chugong", "h-goon"],
        "artists": ["DUBU (REDICE STUDIO)"],
        "genres": ["Action", "Adventure", "Fantasy", "Supernatural", "System"],
        "description": "10 years ago, after 'the Gate' that connected the real world with the monster world opened, some of the ordinary, everyday people received the power to hunt monsters within the Gate. They are known as 'Hunters'. However, not all Hunters are powerful. My name is Sung Jin-Woo, an E-rank Hunter.",
        "cover": "https://uploads.mangadex.org/covers/32d76d19-8a05-4db0-9fc2-e0b0648fe9d0/35687796-f00e-436d-b8e7-ff8736d5fc2a.jpg",
        "url": "https://mangadex.org/title/32d76d19-8a05-4db0-9fc2-e0b0648fe9d0",
        "source": "mangadex",
    },
    {
        "id": "db_sfw_02",
        "title": "One Piece",
        "alt_titles": ["ワンピース", "海贼王"],
        "type": "Manga",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["Eiichiro Oda"],
        "artists": ["Eiichiro Oda"],
        "genres": ["Action", "Adventure", "Comedy", "Fantasy", "Shounen"],
        "description": "Gol D. Roger was known as the 'Pirate King', the strongest and most infamous being to have sailed the Grand Line. Monkey D. Luffy, a 17-year-old boy who defies your standard definition of a pirate, sets off in search of the legendary treasure One Piece.",
        "cover": "https://uploads.mangadex.org/covers/a1c7c817-4e59-43b7-9365-09675a149a6f/1c3bc6ef-59ee-4731-8f55-22d7ad475f41.jpg",
        "url": "https://mangadex.org/title/a1c7c817-4e59-43b7-9365-09675a149a6f",
        "source": "mangadex",
    },
    {
        "id": "db_sfw_03",
        "title": "Omniscient Reader's Viewpoint",
        "alt_titles": ["ORV", "Jeonjijeok Dokja Sijeom", "전지적 독자 시점"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["sing N song", "UMI"],
        "artists": ["Sleepy-C (REDICE STUDIO)"],
        "genres": ["Action", "Adventure", "Fantasy", "Psychological", "Supernatural"],
        "description": "Dokja was an average office worker whose sole interest was reading his favorite web novel 'Three Ways to Survive the Apocalypse'. But when the novel suddenly becomes reality, he is the only person who knows how the world will end.",
        "cover": "https://uploads.mangadex.org/covers/c5167b54-7ef8-4909-8800-4b95d03a111b/78f24ea1-aa0a-4fb4-a5ff-b31c261e4695.jpg",
        "url": "https://mangadex.org/title/c5167b54-7ef8-4909-8800-4b95d03a111b",
        "source": "mangadex",
    },
    {
        "id": "db_sfw_04",
        "title": "The Beginning After The End",
        "alt_titles": ["TBATE"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["TurtleMe"],
        "artists": ["Fuyuki23"],
        "genres": ["Action", "Adventure", "Drama", "Fantasy", "Isekai", "Magic"],
        "description": "King Grey has unrivaled strength, wealth, and prestige in a world governed by martial ability. However, solitude lingers closely behind those with great power. Beneath the glamorous exterior of a powerful king lies the shell of a man, devoid of purpose and will.",
        "cover": "https://uploads.mangadex.org/covers/98906be7-8d05-4ab2-8e10-3ae8e68cfb70/36b801a6-8e5a-4cb7-827d-0125867160df.jpg",
        "url": "https://mangadex.org/title/98906be7-8d05-4ab2-8e10-3ae8e68cfb70",
        "source": "mangadex",
    },
    {
        "id": "db_sfw_05",
        "title": "Berserk",
        "alt_titles": ["ベルセルク"],
        "type": "Manga",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["Kentarou Miura", "Studio Gaga"],
        "artists": ["Kentarou Miura", "Kouji Mori"],
        "genres": ["Action", "Adventure", "Dark Fantasy", "Drama", "Horror", "Seinen"],
        "description": "Guts, a former mercenary now known as the 'Black Swordsman', is out for revenge. After a tumultuous childhood, he finally finds someone he respects and believes he can trust in Griffith, the charismatic leader of the mercenary band of the Hawk.",
        "cover": "https://uploads.mangadex.org/covers/801513ba-a712-4985-8cdd-c6977626524d/c6395b28-cd19-4824-a740-ee7b8f9e0eb6.jpg",
        "url": "https://mangadex.org/title/801513ba-a712-4985-8cdd-c6977626524d",
        "source": "mangadex",
    },
    {
        "id": "db_sfw_06",
        "title": "The Bastard of Swordborne",
        "alt_titles": ["Swordborne Bastard", "검술명가의 막내아들"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["AZI", "Emperor Penguin"],
        "artists": ["COBY"],
        "genres": ["Action", "Adventure", "Drama", "Fantasy", "Shounen"],
        "description": "Theo Ragnar, the 31st son of the mighty Swordborne clan, was deemed talentless and banished. Given a second chance through rebirth, he awakens the primordial dragon power.",
        "cover": "https://cdn.chikari.moe/series/33/cover.webp",
        "url": "https://chikari.moe/series/the-bastard-of-swordborne",
        "source": "chikari",
    },
    {
        "id": "db_sfw_07",
        "title": "Dungeon Odyssey",
        "alt_titles": ["던전 오디세이"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["Glim-goon"],
        "artists": ["Son Min-woo"],
        "genres": ["Action", "Adventure", "Comedy", "Fantasy", "Supernatural"],
        "description": "The descendants of humanity who were born in the labyrinth of the underground dungeons. Jinwoo embarks on an expedition into the unknown floors to build the ultimate dungeon floor.",
        "cover": "https://shadowabyss.com/manhwa/dungeonodyssey/cover/cover.webp",
        "url": "https://kuramanga.com/dungeonodyssey",
        "source": "kuramanga",
    },
    {
        "id": "db_sfw_08",
        "title": "Rebirth: Monarch of the Dead",
        "alt_titles": ["Monarch of the Dead"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["MangaK Studio"],
        "artists": ["MangaK Studio"],
        "genres": ["Action", "Adventure", "Fantasy", "Necromancy", "Webtoons"],
        "description": "Betrayed and slain at the peak of the cataclysm, the greatest necromancer returns to the day the apocalypse began with his complete grimoire intact.",
        "cover": "https://rx.resmk.org/covers/6cf075bd55c8.webp",
        "url": "https://mangak.io/rebirth-monarch-of-the-dead",
        "source": "mangak",
    },
    {
        "id": "db_sfw_09",
        "title": "Jujutsu Kaisen",
        "alt_titles": ["呪術廻戦", "JJK"],
        "type": "Manga",
        "status": "Completed",
        "is_nsfw": False,
        "authors": ["Gege Akutami"],
        "artists": ["Gege Akutami"],
        "genres": ["Action", "Dark Fantasy", "Supernatural", "Shounen"],
        "description": "Yuuji Itadori is a high schooler who spends his days visiting his bedridden grandfather. After swallowing a cursed finger of the King of Curses Sukuna, he enters the Tokyo Jujutsu High.",
        "cover": "https://uploads.mangadex.org/covers/c52b2ce3-7f95-469c-96b0-474fb76ecd32/57db2540-c119-450f-90ff-d5ce5f992a7e.jpg",
        "url": "https://mangadex.org/title/c52b2ce3-7f95-469c-96b0-474fb76ecd32",
        "source": "mangadex",
    },
    {
        "id": "db_sfw_10",
        "title": "Chainsaw Man",
        "alt_titles": ["チェンソーマン", "CSM"],
        "type": "Manga",
        "status": "Ongoing",
        "is_nsfw": False,
        "authors": ["Tatsuki Fujimoto"],
        "artists": ["Tatsuki Fujimoto"],
        "genres": ["Action", "Comedy", "Dark Fantasy", "Supernatural", "Shounen"],
        "description": "Denji was a small-time devil hunter just trying to survive in a harsh world. After being killed on a job, he is revived by his pet devil-dog Pochita and becomes Chainsaw Man.",
        "cover": "https://uploads.mangadex.org/covers/a7774250-d070-4211-9feb-bace66da21f6/b0e513d8-555e-47c3-8898-ad6fcf22521c.jpg",
        "url": "https://mangadex.org/title/a7774250-d070-4211-9feb-bace66da21f6",
        "source": "mangadex",
    },

    # --- Hentai & Adult Manga / Manhwa ---
    {
        "id": "db_nsfw_01",
        "title": "Silent War",
        "alt_titles": ["My Kingdom", "싸움독학"],
        "type": "Manhwa",
        "status": "Completed",
        "is_nsfw": True,
        "authors": ["Yulang"],
        "artists": ["Ghost"],
        "genres": ["Adult", "Drama", "Mature", "Romance", "Smut", "Psychological"],
        "description": "Hyun-Soo lived an oppressed life bullied by his peers. When he discovers a secret club in his university, he uses psychological warfare to claim his revenge.",
        "cover": "https://cloud-7.r2d2storage.com/2020/08/Silent-War.webp",
        "url": "https://hiperdex.com/manga/silent-war",
        "source": "hiperdex",
    },
    {
        "id": "db_nsfw_02",
        "title": "Secret Class",
        "alt_titles": ["비밀수업", "Secret Lesson"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": True,
        "authors": ["Wang Yu"],
        "artists": ["Minachan"],
        "genres": ["Adult", "Harem", "Mature", "Romance", "Smut"],
        "description": "Dae-ho became an orphan when he was 13 years old and was taken in by his father's friend. However, Dae-ho who grew up knowing nothing about relationships gets secret private lessons.",
        "cover": "https://cloud-7.r2d2storage.com/2020/08/Secret-Class.webp",
        "url": "https://hiperdex.com/manga/secret-class",
        "source": "hiperdex",
    },
    {
        "id": "db_nsfw_03",
        "title": "Boarding Diary",
        "alt_titles": ["하숙일기"],
        "type": "Manhwa",
        "status": "Completed",
        "is_nsfw": True,
        "authors": ["Kim Jun-Seok"],
        "artists": ["Park Hyeong-Jun"],
        "genres": ["Adult", "Comedy", "Ecchi", "Mature", "Romance", "Smut"],
        "description": "Jun-woo moved into a boarding house near his university run by his mother's friend Mikyung. Little did he know what exciting daily life awaited him there.",
        "cover": "https://cloud-7.r2d2storage.com/2020/08/Boarding-Diary.webp",
        "url": "https://hiperdex.com/manga/boarding-diary",
        "source": "hiperdex",
    },
    {
        "id": "db_nsfw_04",
        "title": "Stepmother's Friends",
        "alt_titles": ["새엄마의 친구들"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": True,
        "authors": ["Mankit"],
        "artists": ["Grimpan"],
        "genres": ["Adult", "Drama", "Harem", "Mature", "Romance", "Smut"],
        "description": "Seok-woo lives with his beautiful young stepmother. When her glamorous group of friends starts visiting regularly, Seok-woo finds himself surrounded by irresistible temptation.",
        "cover": "https://cloud-7.r2d2storage.com/2020/08/Stepmothers-Friends.webp",
        "url": "https://hiperdex.com/manga/stepmothers-friends",
        "source": "hiperdex",
    },
    {
        "id": "db_nsfw_05",
        "title": "Excuse me, This is my Room",
        "alt_titles": ["방주인은 전데요", "The Ark Is Me"],
        "type": "Manhwa",
        "status": "Completed",
        "is_nsfw": True,
        "authors": ["Kim Jinsoo"],
        "artists": ["Red String"],
        "genres": ["Adult", "Comedy", "Drama", "Mature", "Romance", "Smut"],
        "description": "Kim Jinsoo ends up moving in with his personal bully... Will he be able to find love behind closed doors?",
        "cover": "https://cloud-7.r2d2storage.com/2020/08/Excuse-me-This-is-my-Room.webp",
        "url": "https://hiperdex.com/manga/excuse-me-this-is-my-room-16524ba3",
        "source": "hiperdex",
    },
    {
        "id": "db_nsfw_06",
        "title": "Close Family (Uncensored)",
        "alt_titles": ["Close Family"],
        "type": "Manhwa",
        "status": "Ongoing",
        "is_nsfw": True,
        "authors": ["Madara Team"],
        "artists": ["Madara Team"],
        "genres": ["Adult", "Drama", "Ecchi", "Mature", "Romance", "Uncensored"],
        "description": "A close-knit family dynamic takes an unexpected turn when hidden desires and secrets come to light.",
        "cover": "https://madaradex.org/wp-content/uploads/2024/05/close-family.webp",
        "url": "https://madaradex.org/title/close-family-uncensored/",
        "source": "madaradex",
    },
    {
        "id": "db_nsfw_07",
        "title": "[Pirates Cat] Oshiete Ageru ~Kyonyuu Bijin Onee-san",
        "alt_titles": ["Oshiete Ageru"],
        "type": "Manga",
        "status": "Completed",
        "is_nsfw": True,
        "authors": ["Pirates Cat"],
        "artists": ["Pirates Cat"],
        "genres": ["Big Breasts", "Milf", "Sole Female", "Sole Male", "Stockings"],
        "description": "A passionate doujinshi about a beautiful neighbor giving special private tutoring lessons.",
        "cover": "https://hentai.shadowabyss.com/hentai/27290/cover/cover.webp",
        "url": "https://kurahentai.com/gallery/27290",
        "source": "kurahentai",
    },
]


def search_database(
    query: str,
    include_sfw: bool = True,
    include_nsfw: bool = True,
    limit: int = 25,
) -> List[Dict[str, Any]]:
    """Search the offline database index with fuzzy matching across titles,

    alternative titles, authors, and genres.
    """
    q = (query or "").strip().lower()
    if not q:
        results = [e for e in DATABASE_ENTRIES if (include_sfw if not e["is_nsfw"] else include_nsfw)]
        return results[:limit]

    terms = q.split()
    matched = []

    for entry in DATABASE_ENTRIES:
        # Filter by NSFW preference
        if entry["is_nsfw"] and not include_nsfw:
            continue
        if not entry["is_nsfw"] and not include_sfw:
            continue

        haystack = " ".join([
            entry["title"].lower(),
            " ".join(t.lower() for t in entry.get("alt_titles", [])),
            " ".join(a.lower() for a in entry.get("authors", [])),
            " ".join(g.lower() for g in entry.get("genres", [])),
            entry.get("type", "").lower(),
            entry.get("source", "").lower(),
        ])

        score = 0
        if entry["title"].lower() == q:
            score += 100
        elif entry["title"].lower().startswith(q):
            score += 60
        elif q in entry["title"].lower():
            score += 40

        all_terms_match = True
        for term in terms:
            if term in haystack:
                score += 10
            else:
                all_terms_match = False
                break

        if all_terms_match or score > 0:
            matched.append((score, entry))

    matched.sort(key=lambda x: -x[0])
    return [item[1] for item in matched[:limit]]


def get_search_suggestions(
    prefix: str,
    include_sfw: bool = True,
    include_nsfw: bool = True,
    limit: int = 8,
) -> List[Dict[str, str]]:
    """Generate intelligent suggestions for omnibar input:

    - Matching series titles
    - Source prefix tags (@source)
    - Genre tags (#genre)
    """
    p = (prefix or "").strip().lower()
    suggestions = []

    # 1. Source prefixes (@source)
    from .sources import SOURCES
    for src_id in sorted(SOURCES.keys()):
        if f"@{src_id}".startswith(p) or src_id.startswith(p.lstrip("@")):
            suggestions.append({
                "type": "source",
                "label": f"@{src_id}",
                "value": f"@{src_id} ",
                "icon": "lan",
                "category": "Source",
            })
            if len(suggestions) >= 3:
                break

    # 2. Genre tags (#genre)
    common_genres = [
        "action", "adventure", "comedy", "drama", "fantasy", "horror",
        "isekai", "magic", "martial-arts", "mystery", "romance", "sci-fi",
        "shounen", "supernatural", "webtoons", "adult", "smut", "mature", "harem"
    ]
    for g in common_genres:
        if f"#{g}".startswith(p) or g.startswith(p.lstrip("#")):
            suggestions.append({
                "type": "genre",
                "label": f"#{g}",
                "value": f"#{g} ",
                "icon": "tag",
                "category": "Genre Tag",
            })
            if len(suggestions) >= 6:
                break

    # 3. Matching series titles from database
    db_matches = search_database(p, include_sfw=include_sfw, include_nsfw=include_nsfw, limit=6)
    for m in db_matches:
        suggestions.append({
            "type": "series",
            "label": m["title"],
            "value": m["title"],
            "icon": "menu_book",
            "category": f"{m['type']} • {m['source'].title()}",
            "cover": m.get("cover"),
            "url": m.get("url"),
            "source": m.get("source"),
        })

    return suggestions[:limit]
