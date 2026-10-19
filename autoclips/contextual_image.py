"""Licensed context photography for the lower half of a Portuguese Short.

Only verified Wikimedia Commons CC0/public-domain or CC BY 4.0 files are used
automatically. Search names must match the topic. A missing match is NOT an
excuse to download arbitrary images or mislabel a source frame as a real photo.
"""
from __future__ import annotations
import json
import re
import html
import hashlib
from pathlib import Path
from urllib.parse import urlencode, urlparse, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler

STOP = {
    "para", "como", "quando", "porque", "sobre", "antes", "depois",
    "video", "vídeo", "vídeos", "revela", "revelou", "conta",
    "historia", "história", "shorts", "meu", "minha", "seu", "sua",
    "mais", "essa", "esse", "com", "que", "uma", "isso", "está",
    "tem", "tudo", "pelos", "entre", "fazer", "voce", "você",
}
API = "https://commons.wikimedia.org/w/api.php"
UA = "AutoClipsAI/1.0 (context-image-lookup; Wikimedia Commons only)"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirection is not allowed for contextual images")


def topic_terms(title: str) -> list[str]:
    tokens = re.findall(r"[\wÀ-ÿ]{4,}", title.lower())
    return list(dict.fromkeys(t for t in tokens if t not in STOP and not t.isdigit()))[:6]


def choose_public_domain_image(payload: dict, title: str) -> dict | None:
    terms = topic_terms(title)
    if not terms:
        return None
    matches = []
    for page in (payload.get("query", {}).get("pages", {}) or {}).values():
        name = str(page.get("title", "")).lower()
        match = [t for t in terms if t in name]
        # At least one distinctive topical word, and two for multiword topics.
        if len(match) < min(2, len(terms)):
            continue
        if not name.endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        details = (page.get("imageinfo") or [{}])[0]
        meta = details.get("extmetadata") or {}
        license_name = str(meta.get("LicenseShortName", {}).get("value", "")).lower()
        approved = (license_name in {"cc0", "cc0 1.0", "public domain", "pd-old", "pd-usgov", "cc by 4.0"}
                    or license_name.startswith("public domain"))
        if not approved:
            continue
        url = details.get("thumburl") or details.get("url") or ""
        p = urlparse(url)
        if (p.scheme != "https" or p.hostname != "upload.wikimedia.org"
                or p.username or p.password or p.port not in (None, 443)):
            continue
        raw_artist = str(meta.get("Artist", {}).get("value", ""))
        artist = html.unescape(re.sub(r"<[^>]*>", "", raw_artist))
        artist = re.sub(r"\\s+", " ", artist).strip()[:55]
        if license_name == "cc by 4.0" and not artist:
            continue
        credit = ("Foto: " + artist + " (CC BY 4.0)" if license_name == "cc by 4.0"
                  else "Imagem: Wikimedia Commons (domínio público)")
        matches.append((len(match), {"url": url,
                                    "title": page.get("title", ""),
                                    "license": license_name,
                                    "credit": credit,
                                    "source_page": details.get("descriptionurl", ""),
                                    "license_url": ("https://creativecommons.org/licenses/by/4.0/"
                                                    if license_name == "cc by 4.0" else "")}))
    matches.sort(key=lambda v: v[0], reverse=True)
    return matches[0][1] if matches else None


def curated_context_image(title: str) -> dict | None:
    """Small vetted fallback for Portuguese sports/supplement stories.

    Photographs and their licences were verified against the Commons file
    pages. Source + attribution travel with the MP4; a generic title never
    authorises an unrelated person's portrait. Use original file URLs with
    deterministic MD5 paths, not unaudited search thumbnails.
    """
    topic = title.casefold()
    if "olympia" in topic and ("ramon" in topic or "depois" in topic or "2026" in topic):
        filename = "Ramon_Dino_shows_his_Mr._Olympia_trophy_(2025).jpg"
        lic = "cc by 4.0"
        credit = "Foto ilustrativa de 2025: FotografoWallacyFerrari (CC BY 4.0)"
        licence_url = "https://creativecommons.org/licenses/by/4.0/"
    elif "suplement" in topic or "whey" in topic or "creatina" in topic:
        filename = "Bodybuilding_supplement_high_protein_drink_mix_700g.jpg"
        lic = "public domain"
        credit = "Imagem ilustrativa: Mike1024 (domínio público)"
        licence_url = ""
    else:
        return None
    digest = hashlib.md5(filename.encode("utf-8")).hexdigest()
    return {
        "url": ("https://upload.wikimedia.org/wikipedia/commons/" +
                digest[0] + "/" + digest[:2] + "/" + quote(filename, safe="()")),
        "title": "File:" + filename.replace("_", " "),
        "license": lic,
        "credit": credit,
        "source_page": "https://commons.wikimedia.org/wiki/File:" + quote(filename, safe="()"),
        "license_url": licence_url,
    }


def fetch_public_domain_image(title: str, destination: Path) -> dict | None:
    """Fetch a size-limited, licensed photo. Failure means no external image."""
    terms = topic_terms(title)
    if not terms:
        return None
    opener = build_opener(NoRedirect())
    choice = curated_context_image(title)
    try:
        if choice is None:
            params = {
                "action": "query", "format": "json", "generator": "search",
                "gsrsearch": " ".join(terms[:2]), "gsrnamespace": "6", "gsrlimit": "20",
                "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": "1080"
            }
            req = Request(API + "?" + urlencode(params), headers={"User-Agent": UA})
            with opener.open(req, timeout=8) as response:
                if int(response.headers.get("content-length") or 0) > 256_000:
                    return None
                raw = response.read(256_001)
            if len(raw) > 256_000:
                return None
            choice = choose_public_domain_image(json.loads(raw), title)
            if not choice:
                return None
        req = Request(choice["url"], headers={"User-Agent": UA})
        with opener.open(req, timeout=15) as response:
            if int(response.headers.get("content-length") or 0) > 7_000_000:
                return None
            data = response.read(7_000_001)
        if len(data) > 7_000_000:
            return None
        # Validate encoded image bytes before trusting filename or content-type.
        if data.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            suffix = ".png"
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            suffix = ".webp"
        else:
            return None
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(suffix + ".part")
        target = destination.with_suffix(suffix)
        try:
            temp.write_bytes(data)
            temp.replace(target)
            return {**choice, "path": str(target),
                    "mode": "wikimedia_cc_by" if choice["license"] == "cc by 4.0"
                            else "wikimedia_public_domain"}
        finally:
            temp.unlink(missing_ok=True)
    except (ValueError, OSError, TimeoutError, KeyError, TypeError, json.JSONDecodeError):
        return None
