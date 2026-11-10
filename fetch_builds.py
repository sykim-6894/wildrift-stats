# -*- coding: utf-8 -*-
"""챔피언별 추천 빌드 수집 스크립트.

wildriftfire.com 가이드 페이지에서 추천 아이템/룬/소환사 주문을 읽어 builds.json 에 저장한다.
승률 통계가 아니라 가이드 사이트가 추천하는 빌드다. 패치가 바뀌었을 때만 다시 돌리면 된다.
사용법:  python fetch_builds.py   (약 3~4분, 그 뒤 python update.py)
"""
import html
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from update import HERO_URL, DD_VERSIONS, DD_CHAMPS, EXTRA, GUIDE_URL, get_json, guide_slug

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) wildrift-stats personal page"}
DELAY = 1.0  # 사이트에 부담을 주지 않도록 요청 사이에 쉰다


def names_in(block):
    return [html.unescape(n).strip() for n in re.findall(r'<div class="name">([^<]+)</div>', block)]


def section(mod, cls):
    """item-builds-mod / spells-mod 안에서 <div class="section cls"> 블록을 잘라낸다."""
    m = re.search(r'<div class="section %s">' % cls, mod)
    if not m:
        return ""
    rest = mod[m.end():]
    nxt = re.search(r'<div class="section ', rest)
    return rest[:nxt.start()] if nxt else rest


def parse(page):
    i = page.find('class="data-mod item-builds-mod"')
    j = page.find('class="data-mod spells-mod"')
    if i < 0:
        return None
    items = page[i:j if j > i else i + 20000]
    out = {
        "start": names_in(section(items, "starting")),
        "core": names_in(section(items, "core")),
        "boots": names_in(section(items, "boots")),
        "final": names_in(section(items, "final")),
    }
    if j > 0:
        k = page.find("data-block", j)
        spells = page[j:k if k > j else j + 8000]
        out["spells"] = names_in(section(spells, "spells"))
        out["runes"] = names_in(section(spells, "runes"))
    m = re.search(r'<span class="title">Patch</span>\s*<span class="data">([^<]+)</span>', page)
    out["patch"] = m.group(1).strip() if m else ""
    return out if out["core"] or out["final"] else None


def main():
    hero_list = get_json(HERO_URL)["heroList"]
    ver = get_json(DD_VERSIONS)[0]
    en = get_json(DD_CHAMPS.format(v=ver, lang="en_US"))["data"]
    names = {k.lower(): en[k]["name"] for k in en}
    names.update({k: v["en"] for k, v in EXTRA.items()})

    builds, failed = {}, []
    todo = sorted(hero_list.items())
    for n, (hid, h) in enumerate(todo, 1):
        key = re.sub(r"_\d+\.\w+$", "", h["poster"].split("/")[-1]).lower()
        en_name = names.get(key)
        if not en_name:
            failed.append(hid)
            continue
        url = GUIDE_URL.format(slug=guide_slug(en_name))
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                b = parse(r.read().decode("utf-8", "ignore"))
        except Exception as e:  # 한 챔피언이 실패해도 나머지는 계속
            b = None
            print(f"  실패 {en_name}: {e}", file=sys.stderr)
        if b:
            builds[hid] = b
        else:
            failed.append(en_name)
        print(f"[{n}/{len(todo)}] {en_name} {'OK' if b else '없음'}", flush=True)
        time.sleep(DELAY)

    (HERE / "builds.json").write_text(json.dumps(builds, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"builds.json 저장: {len(builds)}명 성공, 실패 {len(failed)}: {failed}")


if __name__ == "__main__":
    main()
