# -*- coding: utf-8 -*-
"""와일드리프트 공식(한국어) 패치 노트를 받아 patches.json 으로 정리한다.

개발자 코멘트 같은 긴 설명문은 빼고, 무엇이 어떻게 바뀌었는지(이름과 수치 변경 줄)만 남긴다.
이미 받아 둔 패치는 다시 받지 않는다. 가장 최근 패치만 수정될 수 있어 매번 새로 받는다.
사용법:  python fetch_patches.py   (그 뒤 python update.py)
"""
import html
import json
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = "https://wildrift.leagueoflegends.com"
LIST_URL = BASE + "/ko-kr/news/game-updates/"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) wildrift-stats personal page"}
KEEP = 8          # 보여줄 패치 개수
LINE_MAX = 90     # 화살표(→)가 없는 줄은 이보다 짧을 때만 남긴다 (긴 설명문 제외)
GROUP_MAX = 10    # 한 항목에 남기는 줄 수


def next_data(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        page = r.read().decode("utf-8", "ignore")
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        raise ValueError("페이지 형식이 바뀌었습니다: " + url)
    return json.loads(m.group(1))["props"]["pageProps"]["page"]


def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def keep_line(s):
    return bool(s) and ("→" in s or len(s) <= LINE_MAX)


class Outline(HTMLParser):
    """본문 HTML에서 제목(h2~h5)과 목록 줄(li)만 뽑는다. 문단(p)은 버린다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events = []   # ("h", level, text) / ("li", depth, text)
        self.buf = None
        self.kind = None
        self.depth = 0

    def flush(self):
        if self.buf is not None:
            text = clean("".join(self.buf))
            if text:
                self.events.append(self.kind + (text,))
        self.buf, self.kind = None, None

    def handle_starttag(self, tag, attrs):
        if tag in ("ul", "ol"):
            self.flush()
            self.depth += 1
        elif re.fullmatch(r"h[2-5]", tag):
            self.flush()
            self.buf, self.kind = [], ("h", int(tag[1]))
        elif tag == "li":
            self.flush()
            self.buf, self.kind = [], ("li", self.depth)

    def handle_endtag(self, tag):
        if tag in ("ul", "ol"):
            self.flush()
            self.depth = max(0, self.depth - 1)
        elif tag == "li" or re.fullmatch(r"h[2-5]", tag):
            self.flush()

    def handle_data(self, data):
        if self.buf is not None:
            self.buf.append(data)


def lines_from(body):
    """HTML 조각에서 남길 줄과, 빠진 줄이 있었는지 여부."""
    p = Outline()
    p.feed(body or "")
    p.flush()
    out, cut = [], False
    for ev in p.events:
        if ev[0] != "li":
            continue
        if keep_line(ev[2]):
            out.append(ev[2])
        else:
            cut = True
    return out, cut


def parse_article(page):
    sections = []

    def section(title, kind="etc"):
        sections.append({"t": title, "k": kind, "g": []})
        return sections[-1]

    cur = None
    for blade in page.get("blades", []):
        typ = blade.get("type")
        if typ == "characterChanges":
            sec = section(clean(blade.get("title") or "챔피언"), "champ")
            for ch in blade.get("characters", []):
                g = {"n": clean(ch.get("character", {}).get("name", "")), "c": []}
                for c in ch.get("changes", []):
                    ls, cut = lines_from(c.get("description", {}).get("body", ""))
                    if ls or cut:
                        item = {"t": clean(c.get("title", "")), "l": ls}
                        if cut:
                            item["x"] = 1
                        g["c"].append(item)
                if g["n"]:
                    sec["g"].append(g)
            cur = None
        elif typ == "articleRichText":
            p = Outline()
            p.feed(blade.get("richText", {}).get("body", ""))
            p.flush()
            group = None
            for ev in p.events:
                if ev[0] == "h" and ev[1] == 2:
                    cur, group = section(ev[2]), None
                elif ev[0] == "h":
                    if cur is None:
                        cur = section("기타")
                    group = {"n": ev[2], "lv": ev[1], "c": [{"t": "", "l": []}]}
                    cur["g"].append(group)
                elif ev[0] == "li" and group is not None:
                    if keep_line(ev[2]):
                        group["c"][0]["l"].append(ev[2])
                    else:
                        group["c"][0]["x"] = 1
    for s in sections:
        for g in s["g"]:
            for c in g["c"]:
                if len(c["l"]) > GROUP_MAX:
                    c["l"], c["x"] = c["l"][:GROUP_MAX], 1
            g["c"] = [c for c in g["c"] if c["l"] or c.get("x")]
    return [s for s in sections if s["g"]]


def version_of(title, url):
    m = re.search(r"(\d+\.\d+[a-z]?)", title) or re.search(r"(\d+)-?(\d+[a-z]?)/?$", url)
    if not m:
        return title
    return m.group(1) if m.lastindex == 1 else f"{m.group(1)}.{m.group(2)}"


def find_patch_links(page):
    """목록 페이지 데이터에서 패치 노트 글만 찾는다."""
    found = {}

    def walk(o):
        if isinstance(o, dict):
            url = (o.get("action") or {}).get("payload", {}).get("url", "") if isinstance(o.get("action"), dict) else ""
            if o.get("title") and o.get("publishedAt") and "patch-notes" in url:
                found.setdefault(url, {
                    "url": url, "title": o["title"], "date": o["publishedAt"][:10],
                    "desc": clean((o.get("description") or {}).get("body", "")),
                })
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(page)
    return sorted(found.values(), key=lambda x: x["date"], reverse=True)[:KEEP]


def main():
    path = HERE / "patches.json"
    old = {p["url"]: p for p in json.loads(path.read_text(encoding="utf-8"))} if path.exists() else {}
    links = find_patch_links(next_data(LIST_URL))
    if not links:
        sys.exit("패치 노트 목록을 찾지 못했습니다.")

    out = []
    for i, item in enumerate(links):
        full = BASE + item["url"]
        if i > 0 and full in old:          # 최신 패치(i == 0)만 매번 새로 받는다
            out.append(old[full])
            continue
        try:
            page = next_data(full)
            out.append({
                "v": version_of(item["title"], item["url"]),
                "title": item["title"],
                "date": item["date"],
                "desc": item["desc"] or clean(page.get("description", "")),
                "url": full,
                "s": parse_article(page),
            })
            print(f"받음: {item['title']}")
        except Exception as e:
            print(f"실패: {item['title']}: {e}", file=sys.stderr)
            if full in old:
                out.append(old[full])
        time.sleep(1)

    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"patches.json 저장: {len(out)}개")


if __name__ == "__main__":
    main()
