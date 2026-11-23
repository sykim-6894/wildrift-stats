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


# 가이드 사이트의 라인 그림 이름 → 통계의 포지션 번호 (2 탑, 5 정글, 1 미드, 3 원딜, 4 서폿)
LANE_POS = {"top": "2", "solo": "2", "baron": "2", "jungle": "5", "mid": "1", "middle": "1", "duo": "3", "adc": "3", "bot": "3", "support": "4"}
UNKNOWN_LANES = set()


def lane_pos(name):
    pos = LANE_POS.get(name.lower())
    if not pos:
        UNKNOWN_LANES.add(name)
    return pos


def guide_blocks(page):
    """페이지의 data-block 들을 {가이드번호: {"items": 글, "spells": 글}} 로 나눈다.

    한 챔피언 페이지에 라인별 가이드(예: 서폿 빌드, 미드 빌드)가 함께 들어 있고,
    화면에는 하나만 보이고 나머지는 inactive 로 숨겨져 있다.
    """
    starts = [(m.start(), m.group(0), m.group(1)) for m in re.finditer(r'<div class="[^"]*data-block[^"]*" data-guide-id="(\d+)"', page)]
    out = {}
    for n, (pos, tag, gid) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(page)
        text = page[pos:end]
        kind = "items" if "wf-champion__data__items" in tag else "spells" if "wf-champion__data__spells" in tag else None
        if kind:
            out.setdefault(gid, {})[kind] = text
    return out


def parse_guide(items, spells):
    out = {
        "start": names_in(section(items, "starting")),
        "core": names_in(section(items, "core")),
        "boots": names_in(section(items, "boots")),
        "final": names_in(section(items, "final")),
    }
    if spells:
        out["spells"] = names_in(section(spells, "spells"))
        out["runes"] = names_in(section(spells, "runes"))
    return out if out["core"] or out["final"] else None


def parse(page):
    """기본 가이드(화면에 처음 보이는 것)를 돌려주고, 라인별 가이드가 있으면 "lanes" 에 모두 담는다."""
    blocks = guide_blocks(page)
    if not blocks:
        return None
    m = re.search(r'<span class="title">Patch</span>\s*<span class="data">([^<]+)</span>', page)
    patch = m.group(1).strip() if m else ""
    # 가이드 선택 탭: 번호 → 라인
    tabs = re.findall(r'<span( class="active")? data-guide-id="(\d+)">\s*<img src="/images/lanes/white-([\w-]+)\.png">', page)
    lane_of = {gid: lane_pos(name) for _, gid, name in tabs}
    active = next((gid for act, gid, _ in tabs if act), None)
    if not tabs:
        r = re.search(r'Recommended Role</span>\s*<span class="data">\s*<img src="/images/lanes/white-([\w-]+)\.png"', page)
        gid0 = next(iter(blocks))
        lane_of[gid0] = lane_pos(r.group(1)) if r else None
        active = gid0
    guides = {}
    for gid, b in blocks.items():
        if "items" not in b:
            continue
        g = parse_guide(b["items"], b.get("spells", ""))
        if g:
            g["patch"] = patch
            guides[gid] = g
    if not guides:
        return None
    first = active if active in guides else next(iter(guides))
    out = dict(guides[first])
    out["lane"] = lane_of.get(first)
    lanes = {lane_of[gid]: g for gid, g in guides.items() if lane_of.get(gid)}
    if len(lanes) > 1:
        out["lanes"] = lanes
    return out


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
    if UNKNOWN_LANES:
        print("알 수 없는 라인 이름:", sorted(UNKNOWN_LANES))
    print(f"builds.json 저장: {len(builds)}명 성공, 실패 {len(failed)}: {failed}")


if __name__ == "__main__":
    main()
