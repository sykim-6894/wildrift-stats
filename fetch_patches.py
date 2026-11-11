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
LIST_PATH = "/{loc}/news/game-updates/"
# 화면 언어 -> 공식 사이트 언어. 중국어는 공식 사이트에 번체(대만)만 있다.
LOCALES = {"ko": "ko-kr", "en": "en-us", "zh": "zh-tw"}
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) wildrift-stats personal page"}
KEEP = 8          # 보여줄 패치 개수
LINE_MAX = {"ko": 90, "en": 150, "zh": 60}  # 화살표(→)가 없는 줄은 이보다 짧을 때만 남긴다 (긴 설명문 제외)
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


CUR_MAX = 90      # 지금 처리 중인 언어의 기준 길이 (main 에서 바꾼다)


def keep_line(s):
    return bool(s) and ("→" in s or len(s) <= CUR_MAX)


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


def fetch_locale(lang, loc, old):
    """한 언어의 패치 노트 목록. old 는 {주소: 이미 받아 둔 패치}."""
    global CUR_MAX
    CUR_MAX = LINE_MAX[lang]
    links = find_patch_links(next_data(BASE + LIST_PATH.format(loc=loc)))
    if not links:
        raise ValueError("패치 노트 목록을 찾지 못했습니다: " + loc)
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
            print(f"받음[{lang}]: {item['title']}")
        except Exception as e:
            print(f"실패[{lang}]: {item['title']}: {e}", file=sys.stderr)
            if full in old:
                out.append(old[full])
        time.sleep(1)
    return out


def main():
    path = HERE / "patches.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if isinstance(saved, list):            # 예전 형식(한국어만)
        saved = {"ko": saved}

    result, ok = {}, 0
    for lang, loc in LOCALES.items():
        old = {p["url"]: p for p in saved.get(lang, [])}
        try:
            result[lang] = fetch_locale(lang, loc, old)
            ok += 1
        except Exception as e:             # 한 언어가 실패해도 나머지는 계속, 기존 내용 유지
            print(f"실패[{lang}]: {e}", file=sys.stderr)
            result[lang] = saved.get(lang, [])
    if not ok:
        sys.exit("패치 노트를 하나도 받지 못했습니다.")

    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("patches.json 저장: " + ", ".join(f"{k} {len(v)}개" for k, v in result.items()))


if __name__ == "__main__":
    main()
