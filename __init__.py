#!/usr/bin/env python
# coding: utf-8

from urllib.parse import urlencode, quote_plus
import re, xml.etree.ElementTree as ET

from calibre.ebooks.metadata.sources.base import Source
from calibre.ebooks.metadata.book.base import Metadata
from calibre.utils.date import parse_date
from calibre.utils.config import JSONConfig

# clickable identifiers
from calibre.ebooks.metadata.book.base import identifier_to_link_map

identifier_to_link_map.update(
    {
        "aladin": "https://www.aladin.co.kr/shop/wproduct.aspx?ItemId=%s",
        "aladinseries": "https://www.aladin.co.kr/shop/common/wseriesitem.aspx?SRID=%s",
    }
)

prefs = JSONConfig("plugins/AladinOpenAPI")
prefs.defaults["ttb_key"] = ""


class AladinMetadata(Source):

    name = "Aladin Metadata"
    description = "aladin.co.kr에서 한국어 책 메타데이터와 표지를 가져옵니다."
    author = "Subin Song"
    version = (1, 0, 0)
    minimum_calibre_version = (8, 0, 0)
    supported_platforms = ["windows", "osx", "linux"]
    languages = frozenset(["kor"])
    capabilities = frozenset(["identify", "cover"])
    touched_fields = frozenset(
        [
            "title",
            "authors",
            "identifier:isbn",
            "identifier:aladin",
            "identifier:aladinseries",
            "series",
            "publisher",
            "pubdate",
            "comments",
            "rating",
            "language",
            "tags",
        ]
    )
    prefs = prefs

    _OPT = "authors,fullDescription,seriesInfo"
    _ROLE_OK = ("지은이", "저자", "글")

    def _fetch_xml(self, url, params, log):
        full = f"{url}?{urlencode(params, quote_via=quote_plus)}"
        log.debug("Aladin request → %s", full)
        try:
            raw = self.browser.open(full, timeout=self.timeout).read()
            root = ET.fromstring(raw)
            for el in root.iter():
                if "}" in el.tag:
                    el.tag = el.tag.split("}", 1)[1]
            return root
        except Exception as e:
            log.exception("Aladin request failed: %s", e)
            return None

    def _lookup(self, key, **kw):
        return self._fetch_xml(
            "http://www.aladin.co.kr/ttb/api/ItemLookUp.aspx",
            {
                "ttbkey": key,
                "itemIdType": kw.get("id_type", "ISBN13"),
                "ItemId": kw.get("isbn") or kw.get("item_id"),
                "output": "xml",
                "Version": "20131101",
                "Cover": "Big",
                "OptResult": self._OPT,
            },
            kw["log"],
        )

    def _search(self, q, key, target, log):
        return self._fetch_xml(
            "http://www.aladin.co.kr/ttb/api/ItemSearch.aspx",
            {
                "ttbkey": key,
                "Query": q,
                "QueryType": "Keyword",
                "SearchTarget": target,
                "MaxResults": 10,
                "start": 1,
                "output": "xml",
                "Version": "20131101",
                "Cover": "Big",
                "OptResult": self._OPT,
            },
            log,
        )

    def _parse_items(self, root, queue, abort, log):
        if root is None:
            return
        for it in root.findall("item"):
            if abort.is_set():
                return
            title = it.findtext("title", "").strip()

            # authors
            authors = []
            for tok in re.split(r"[;,]", it.findtext("author", "")):
                tok = tok.strip()
                if not tok:
                    continue
                m = re.match(r"^(.*?)\s*\(([^)]+)\)", tok)
                if m:
                    name, role = m.groups()
                    if any(r in role for r in self._ROLE_OK):
                        authors.append(name.strip())
                else:
                    authors.append(tok)

            mi = Metadata(title, authors or None)
            mi.isbn = it.findtext("isbn13") or it.findtext("isbn")
            mi.publisher = it.findtext("publisher")
            mi.pubdate = (
                parse_date(it.findtext("pubDate") or it.findtext("pubdate") or "")
                or None
            )
            mi.language = "kor"
            mi.comments = it.findtext("description")

            item_id = it.get("itemId") or it.findtext("itemId")
            if item_id:
                mi.set_identifier("aladin", item_id)

            s = it.find("seriesInfo")
            if s is not None:
                if s.findtext("seriesName"):
                    mi.series = s.findtext("seriesName").strip()
                if s.findtext("seriesId"):
                    mi.set_identifier("aladinseries", s.findtext("seriesId"))

            cat = it.findtext("categoryName")
            if cat:
                parts = [p.strip() for p in cat.split(">") if p.strip()]
                mi.tags = list(dict.fromkeys(parts))

            rank = it.findtext("customerReviewRank")
            if rank:
                try:
                    mi.rating = float(rank) / 2.0
                except:
                    pass

            cv = it.findtext("cover")
            if cv and cv.lower().startswith("http"):
                mi.cover_url = cv

            log.debug("→ %s", mi)
            queue.put(mi)

    def identify(
        self, log, queue, abort, title=None, authors=None, identifiers={}, timeout=30
    ):

        self.timeout = timeout
        key = self.prefs["ttb_key"].strip()
        if not key:
            return

        isbn = identifiers.get("isbn") if identifiers else None
        if not isbn:
            isbn = identifiers.get("isbn13") if identifiers else None
        if isbn:
            self._parse_items(self._lookup(key, isbn=isbn, log=log), queue, abort, log)
            return

        q = " ".join(filter(None, [title] + (authors or [])))
        if not q:
            return
        for t in ("Book", "Ebook"):
            self._parse_items(self._search(q, key, t, log), queue, abort, log)

    def download_cover(
        self, log, queue, abort, title=None, authors=None, identifiers={}, timeout=30
    ):

        self.timeout = timeout
        key = self.prefs["ttb_key"].strip()
        if not key or abort.is_set():
            return

        cover_url = None
        if identifiers.get("aladin"):
            item = self._lookup(
                key, item_id=identifiers["aladin"], id_type="ItemId", log=log
            ).find("item")
            cover_url = item.findtext("cover") if item is not None else None

        if not cover_url and (identifiers.get("isbn") or identifiers.get("isbn13")):
            isbn = identifiers.get("isbn") or identifiers.get("isbn13")
            item = self._lookup(key, isbn=isbn, log=log).find("item")
            cover_url = item.findtext("cover") if item is not None else None

        if not cover_url:
            q = " ".join(filter(None, [title] + (authors or [])))
            if q:
                item = self._search(q, key, "Book", log).find("item")
                cover_url = item.findtext("cover") if item is not None else None

        if not (cover_url and cover_url.startswith("http")):
            return
        cover_url = re.sub(r"/coversum/", "/cover500/", cover_url)
        cover_url = re.sub(r"/cover\d{3}/", "/cover500/", cover_url)

        try:
            img = self.browser.open(cover_url, timeout=self.timeout).read()
            if img:
                queue.put((self, img))
        except Exception as e:
            log.exception("Cover download failed: %s", e)

    def config_widget(self):
        from PyQt5.Qt import QWidget, QVBoxLayout, QLabel, QLineEdit

        w = QWidget()
        l = QVBoxLayout(w)
        l.addWidget(QLabel("알라딘 OpenAPI key:"))
        le = QLineEdit(w)
        le.setText(self.prefs["ttb_key"])
        le.setEchoMode(QLineEdit.Password)
        l.addWidget(le)
        w.le = le
        return w

    def save_settings(self, w):
        self.prefs["ttb_key"] = w.le.text().strip()


class_ = AladinMetadata
