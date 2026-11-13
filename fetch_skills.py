# -*- coding: utf-8 -*-
"""챔피언별 스킬 정보를 받아 skills.json 으로 정리한다.

- 이름·설명·아이콘: 와일드리프트 공식 사이트 챔피언 페이지 (한국어 / 영어 / 중국어 번체)
- 재사용 대기시간·소모값: 중국 공식 자료실 (중국 서버 기준 수치)
스킬은 패치로 바뀔 수 있으니 패치 때 한 번씩 다시 돌린다.
사용법:  python fetch_skills.py   (약 2분, 그 뒤 python update.py)
"""
import html
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from update import HERO_URL, DD_VERSIONS, DD_CHAMPS, EXTRA, LRLIB, get_json, norm

HERE = Path(__file__).resolve().parent
BASE = "https://wildrift.leagueoflegends.com"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) wildrift-stats personal page"}
LOCALES = {"ko": "ko-kr", "en": "en-us", "zh": "zh-tw"}
# 공식 주소가 영어 이름과 다르게 생긴 챔피언
SLUG_FIX = {"nunuwillump": "nunu-and-willump"}
SMALL = {"of", "the", "and", "to", "in", "a", "an", "for", "on"}


def fetch(url):
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "ignore")
        except Exception:
            time.sleep(1.5)
    return None


def clean(s):
    s = re.sub(r"<br\s*/?>", " ", s or "")
    s = html.unescape(re.sub(r"<[^>]+>", "", s)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


def title_case(s):
    words = s.lower().split(" ")
    return " ".join(w if (i and w in SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def parse_page(page, lang):
    """공식 챔피언 페이지에서 스킬 5개의 [이름, 설명, 아이콘]을 뽑는다. 못 찾으면 None."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
    if not m:
        return None
    blades = json.loads(m.group(1))["props"]["pageProps"]["page"].get("blades", [])
    for b in blades:
        groups = b.get("groups") or []
        if b.get("type") != "iconTab" or len(groups) != 5:
            continue
        if not all(((g.get("content") or {}).get("description") or {}).get("body") for g in groups):
            continue
        out = []
        for g in groups:
            name = clean(g.get("label", ""))
            out.append([
                title_case(name) if lang == "en" else name,
                clean(g["content"]["description"]["body"]),
                (g.get("thumbnail") or {}).get("url", "").split("?")[0],
            ])
        return out
    return None


def cn_numbers(hid):
    """중국 공식 자료실의 [재사용 대기시간, 소모값] 5쌍. 모양이 다르면 None."""
    try:
        spells = get_json(f"{LRLIB}hero/{hid}.js")["spells"]
    except Exception:
        return None
    if len(spells) != 5:
        return None
    out = []
    for s in spells:
        cd, cost = "", ""
        for i in range(1, 21):
            t = s.get(f"variType{i}", "")
            if t == "cd":
                cd = s.get(f"variValue{i}", "")
            elif t == "Resource":
                cost = s.get(f"variValue{i}", "")
        if not cd and s.get("cdtime"):
            cd = s["cdtime"]
        out.append([cd, cost])
    return out


def main():
    hero_list = get_json(HERO_URL)["heroList"]
    ver = get_json(DD_VERSIONS)[0]
    en = get_json(DD_CHAMPS.format(v=ver, lang="en_US"))["data"]
    names = {k.lower(): v["name"] for k, v in en.items()}
    names.update({k: v["en"] for k, v in EXTRA.items()})

    listing = fetch(f"{BASE}/en-us/champions/") or ""
    slugs = {norm(s): s for s in re.findall(r"/en-us/champions/([a-z0-9-]+)/", listing)}
    if not slugs:
        sys.exit("공식 챔피언 목록을 받지 못했습니다.")

    missing = []
    path = HERE / "skills.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def work(item):
        hid, h = item
        key = re.sub(r"_\d+\.\w+$", "", h["poster"].split("/")[-1]).lower()
        en_name = names.get(key, "")
        k = norm(en_name)
        slug = SLUG_FIX.get(k) or slugs.get(k)
        if not slug:
            return hid, None, f"{en_name or h['name']}: 공식 주소 없음"
        result = {}
        for lang, loc in LOCALES.items():
            page = fetch(f"{BASE}/{loc}/champions/{slug}/")
            got = parse_page(page, lang) if page else None
            if got:
                result[lang] = got
            elif lang == "ko":
                return hid, None, f"{en_name}: 한국어 스킬을 읽지 못함"
            else:
                missing.append(f"{en_name}: {loc} 페이지 없음 (다른 언어로 대신 표시)")
        icons = [x[2] for x in result["ko"]]
        nums = cn_numbers(hid)
        item_out = {"i": icons}
        for lang in result:
            item_out[lang] = [[x[0], x[1]] for x in result[lang]]
        if nums:
            item_out["n"] = nums
        return hid, item_out, None

    new, failed = {}, []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for n, (hid, data, err) in enumerate(ex.map(work, sorted(hero_list.items())), 1):
            if data:
                new[hid] = data
            else:
                failed.append(err)
                if hid in old:
                    new[hid] = old[hid]      # 실패하면 이전 내용을 유지한다
            if n % 20 == 0:
                print(f"[{n}/{len(hero_list)}]", flush=True)

    if not new:
        sys.exit("스킬 정보를 하나도 받지 못했습니다.")
    path.write_text(json.dumps(new, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"skills.json 저장: {len(new)}명, 실패 {len(failed)}")
    for f in failed:
        print("  -", f)
    for f in missing:
        print("  ·", f)


if __name__ == "__main__":
    main()
