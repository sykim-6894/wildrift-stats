# -*- coding: utf-8 -*-
"""와일드리프트 승률표 데이터 갱신 스크립트.

중국 서버 공식 랭크 통계(텐센트)를 받아 template.html 에 넣어 index.html 을 만든다.
사용법:  python update.py
"""
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
UA = {"User-Agent": "Mozilla/5.0"}

RANK_URL = "https://mlol.qt.qq.com/go/lgame_battle_info/hero_rank_list_v2"
HERO_URL = "https://game.gtimg.cn/images/lgamem/act/lrlib/js/heroList/hero_list.js"
DD_VERSIONS = "https://ddragon.leagueoflegends.com/api/versions.json"
DD_CHAMPS = "https://ddragon.leagueoflegends.com/cdn/{v}/data/{lang}/champion.json"
GUIDE_URL = "https://www.wildriftfire.com/guide/{slug}"

# 공식 통계의 코드값 (lolm.qq.com 통계 페이지 기준)
TIERS = ["1", "2", "3", "4"]          # 다이아+, 마스터+, 챌린저, 峡谷之巅
POSITIONS = ["2", "5", "1", "3", "4"]  # 탑, 정글, 미드, 원딜, 서폿

# PC 롤에 없는 와일드리프트 전용 챔피언
EXTRA = {"norra": {"ko": "노라", "en": "Norra", "tw": "諾拉"}}

# 빌드 가이드(wildriftfire) 주소가 영어 이름과 다르게 생긴 경우
GUIDE_SLUG_FIX = {"nunuwillump": "nunu-amp-willump"}


# 데이터 드래곤(PC 롤)에 없는 와일드리프트 전용 이름. 여기 없는 것은 영어로 표시된다.
MANUAL_KO = {
    "Lord Dominik's Regard": "도미닉 경의 인사",
    "Navori Quickblades": "나보리 신속검",
    "Infinity Orb": "무한의 구",
    "Phase Rush": "난입",
    "Aery": "콩콩이 소환",
    "Zombie Ward": "좀비 와드",
    "Eyeball Collector": "안구 수집가",
    "Courage of the Colossus": "거인의 용기",
}
DD_DATA = "https://ddragon.leagueoflegends.com/cdn/{v}/data/{lang}/{f}.json"
LRLIB = "https://game.gtimg.cn/images/lgamem/act/lrlib/js/"

# 아이콘 찾기용: 영어 이름 -> 중국 공식 자료실의 이름. 데이터 드래곤 중국어 이름과 다르거나 없는 것만 적는다.
MANUAL_ZH = {
    "Liandry's Torment": "兰德里的苦痛面具",
    "Rabadon's Deathcap": "灭世者之帽",
    "Riftmaker": "峡谷制造者",
    "Youmuu's Ghostblade": "幽梦之魂",
    "Gluttonous Greaves": "贪婪之靴",
    "Infinity Orb": "无限法球",
    "Navori Quickblades": "纳沃利迅刃",
    "Lord Dominik's Regard": "多米尼克领主的致意",
    "Amaranth's Twinguard": "永生花的双生守护",
    "Mantle of the Twelfth Hour": "午时斗篷",
    "Yordle Trap": "约德尔诱捕装置",
    "Boots of Mana": "法力之靴",
    "Harmonic Echo": "和音之律",
    # 룬
    "Electrocute": "电击",
    "Hextech Flashtraption": "海克斯闪现",
    "Legend: Alacrity": "传说：攻速",
    "Aery": "艾黎",
    "Phase Rush": "相位猛冲",
    "Ice Overlord": "冰霜领主",
    "Brutal": "残暴",
    "Battle Zeal": "战意",
    "Botanist": "植物学家",
    "Courage of the Colossus": "巨像勇气",
    "Empowered Attack": "强化攻击",
    "Eyeball Collector": "眼球收集器",
    "Zombie Ward": "僵尸守卫",
    "Chain Assault": "连破",
    "Tyrant": "凌弱",
    "Unshakeable": "坚定壁垒",
    "Perseverance": "坚韧",
    # 소환사 주문
    "Barrier": "屏障", "Flash": "闪现", "Ghost": "幽灵疾步", "Heal": "治疗术",
    "Ignite": "引燃", "Smite": "惩戒", "Teleport": "传送",
}
RUNE_ONLY_ZH = {"Hubris": "狂妄"}  # 같은 이름의 아이템이 있어 룬일 때만 적용


class Names:
    """영어 이름을 한글 이름과 아이콘 주소로 바꿔 준다. kind 는 item / rune / spell."""

    def __init__(self, ver):
        self.ko = {"item": {}, "rune": {}, "spell": {}}
        self.zh = {"item": {}, "rune": {}, "spell": {}}
        self.dd_icon = {"item": {}, "rune": {}, "spell": {}}
        for kind, f in (("item", "item"), ("spell", "summoner")):
            e = get_json(DD_DATA.format(v=ver, lang="en_US", f=f))["data"]
            k = get_json(DD_DATA.format(v=ver, lang="ko_KR", f=f))["data"]
            z = get_json(DD_DATA.format(v=ver, lang="zh_CN", f=f))["data"]
            folder = "item" if kind == "item" else "spell"
            for i in e:
                n = norm(e[i]["name"])
                if i in k:
                    self.ko[kind].setdefault(n, k[i]["name"])
                if i in z:
                    self.zh[kind].setdefault(n, z[i]["name"])
                self.dd_icon[kind].setdefault(
                    n, f"https://ddragon.leagueoflegends.com/cdn/{ver}/img/{folder}/{e[i]['image']['full']}")
        e = get_json(DD_DATA.format(v=ver, lang="en_US", f="runesReforged"))
        k = get_json(DD_DATA.format(v=ver, lang="ko_KR", f="runesReforged"))
        z = get_json(DD_DATA.format(v=ver, lang="zh_CN", f="runesReforged"))
        for te, tk, tz in zip(e, k, z):
            for se, sk, sz in zip(te["slots"], tk["slots"], tz["slots"]):
                for r_en, r_ko, r_zh in zip(se["runes"], sk["runes"], sz["runes"]):
                    n = norm(r_en["name"])
                    self.ko["rune"][n] = r_ko["name"]
                    self.zh["rune"][n] = r_zh["name"]
                    self.dd_icon["rune"][n] = "https://ddragon.leagueoflegends.com/cdn/img/" + r_en["icon"]
        # 와일드리프트 공식(중국) 아이콘: 중국어 이름 -> 주소
        self.cn_icon = {
            "item": {x["name"]: x["iconPath"] for x in get_json(LRLIB + "equip/equip.js")["equipList"]},
            "rune": {x["name"]: x["iconPath"] for x in get_json(LRLIB + "rune/rune.js")["runeList"]},
            "spell": {x["name"]: x["iconPath"] for x in get_json(LRLIB + "skill/skill.js")["skillList"]},
        }
        self.untranslated = set()
        self.no_icon = set()

    def lookup(self, kind, name):
        n = norm(name)
        ko = None
        for k2 in (kind, "item", "rune", "spell"):
            ko = ko or self.ko[k2].get(n)
        ko = MANUAL_KO.get(name) or ko
        if not ko:
            self.untranslated.add(name)
        zh = (RUNE_ONLY_ZH.get(name) if kind == "rune" else None) or MANUAL_ZH.get(name) or self.zh[kind].get(n)
        icon = self.cn_icon[kind].get(zh) or self.dd_icon[kind].get(n) or ""
        if not icon:
            self.no_icon.add(name)
        # [한국어, 영어, 중국어(간체)] 이름. 번역이 없으면 영어 이름을 쓴다.
        return [ko or name, name, zh or name], icon


def load_builds(ver, heroes):
    """fetch_builds.py 가 만든 builds.json 을 읽어 한글 이름과 아이콘을 붙인다.

    things: [[이름, 아이콘주소], ...] 목록이고, 빌드에는 그 목록의 번호만 넣어 용량을 줄인다.
    """
    path = HERE / "builds.json"
    if not path.exists():
        return {}, [], None
    raw = json.loads(path.read_text(encoding="utf-8"))
    names = Names(ver)
    things, index = [], {}

    def ref(kind, name):
        key = (kind, name)
        if key not in index:
            index[key] = len(things)
            things.append(list(names.lookup(kind, name)))
        return index[key]

    out = {}
    for hid, b in raw.items():
        if hid not in heroes:
            continue
        out[hid] = {
            "s": [ref("item", x) for x in b.get("start", [])],
            "c": [ref("item", x) for x in b.get("core", [])],
            "b": [ref("item", x) for x in b.get("boots", [])],
            "f": [ref("item", x) for x in b.get("final", [])],
            "r": [ref("rune", x) for x in b.get("runes", [])],
            "sp": [ref("spell", x) for x in b.get("spells", [])],
            "p": b.get("patch", ""),
        }
    return out, things, names


HISTORY_KEEP = 30   # history.json 에 남기는 날짜 수
HISTORY_SHOW = 14   # 페이지에 넣는 날짜 수 (추이 그래프, 변동 목록용)


def update_history(date, stats):
    """오늘 통계를 history.json 에 날짜별로 쌓고, 페이지에 넣을 승률 추이를 돌려준다.

    history.json: {날짜: {구간: {포지션: {챔피언: [승률, 픽률, 밴률]}}}}
    돌려주는 값: {"d": [날짜...], "w": {구간: {포지션: {챔피언: [날짜별 승률 또는 None]}}}}
    """
    path = HERE / "history.json"
    hist = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    hist[date] = {t: {p: {r[0]: r[1:] for r in rows} for p, rows in ps.items()} for t, ps in stats.items()}
    hist = dict(sorted(hist.items())[-HISTORY_KEEP:])
    path.write_text(json.dumps(hist, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    days = sorted(hist)[-HISTORY_SHOW:]
    wins = {}
    for t, ps in stats.items():
        wins[t] = {}
        for p, rows in ps.items():
            wins[t][p] = {}
            for r in rows:
                series = [hist[d].get(t, {}).get(p, {}).get(r[0], [None])[0] for d in days]
                wins[t][p][r[0]] = series
    return {"d": days, "w": wins}


def load_skills(heroes):
    """fetch_skills.py 가 만든 skills.json. 없으면 빈 값."""
    path = HERE / "skills.json"
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {hid: v for hid, v in raw.items() if hid in heroes}


def load_patches():
    """fetch_patches.py 가 만든 patches.json. 없으면 빈 목록."""
    path = HERE / "patches.json"
    if not path.exists():
        return []
    patches = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(patches, list):      # 예전 형식(한국어만)
        patches = {"ko": patches}
    for plist in patches.values():
        for p in plist:
            p.pop("title", None)
    return patches


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def guide_slug(en_name):
    key = norm(en_name)
    if key in GUIDE_SLUG_FIX:
        return GUIDE_SLUG_FIX[key]
    s = en_name.lower().replace("'", "").replace(".", "")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def main():
    rank = get_json(RANK_URL)["data"]
    hero_list = get_json(HERO_URL)["heroList"]
    ver = get_json(DD_VERSIONS)[0]
    ko = get_json(DD_CHAMPS.format(v=ver, lang="ko_KR"))["data"]
    en = get_json(DD_CHAMPS.format(v=ver, lang="en_US"))["data"]
    tw = get_json(DD_CHAMPS.format(v=ver, lang="zh_TW"))["data"]
    names = {k.lower(): {"ko": ko[k]["name"], "en": en[k]["name"], "tw": tw.get(k, {}).get("name", "")} for k in ko}
    names.update(EXTRA)

    heroes = {}
    unknown = []
    for hid, h in hero_list.items():
        key = re.sub(r"_\d+\.\w+$", "", h["poster"].split("/")[-1]).lower()
        n = names.get(key)
        if not n:
            unknown.append(h["name"])
            n = {"ko": h["name"], "en": ""}
        heroes[hid] = {
            # [한국어, 영어, 중국어(간체, 중국 서버 표기)]
            "n": [n["ko"], n["en"] or h["name"], h["name"]],
            # 패치 노트(번체)에서 챔피언을 찾기 위한 대만 표기
            "x": n.get("tw", ""),
            "a": h["avatar"],
            "g": GUIDE_URL.format(slug=guide_slug(n["en"])) if n["en"] else "",
        }

    stats = {}
    date = ""
    for t in TIERS:
        stats[t] = {}
        for p in POSITIONS:
            rows = []
            for x in rank.get(t, {}).get(p, []):
                if x["hero_id"] not in heroes:
                    continue
                date = max(date, x["dtstatdate"])
                rows.append([
                    x["hero_id"],
                    round(float(x["win_rate"]) * 100, 2),
                    round(float(x["appear_rate"]) * 100, 2),
                    round(float(x["forbid_rate"]) * 100, 2),
                ])
            rows.sort(key=lambda r: -r[1])
            stats[t][p] = rows

    if not date:
        sys.exit("통계 데이터를 받지 못했습니다.")

    builds, things, names = load_builds(ver, heroes)
    date = f"{date[:4]}-{date[4:6]}-{date[6:]}"

    data = {
        "date": date,
        "hist": update_history(date, stats),
        "heroes": heroes,
        "stats": stats,
        "builds": builds,
        "things": things,
        "patches": load_patches(),
        "skills": load_skills(heroes),
    }
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tpl = (HERE / "template.html").read_text(encoding="utf-8")
    if "__DATA__" not in tpl:
        sys.exit("template.html 에 __DATA__ 자리가 없습니다.")
    (HERE / "index.html").write_text(tpl.replace("__DATA__", blob), encoding="utf-8")

    total = sum(len(v) for t in stats.values() for v in t.values())
    print(f"index.html 생성 완료: 기준일 {data['date']}, 챔피언 {len(heroes)}명, 통계 {total}행")
    print(f"빌드: {len(builds)}명" if builds else "빌드: builds.json 없음 (python fetch_builds.py 로 수집)")
    if names and names.untranslated:
        print("영어로 남은 이름:", ", ".join(sorted(names.untranslated)))
    if names and names.no_icon:
        print("아이콘이 없는 것(글자로 표시됨):", ", ".join(sorted(names.no_icon)))
    if unknown:
        print("한글 이름을 찾지 못한 챔피언(중국어로 표시됨):", ", ".join(unknown))


if __name__ == "__main__":
    main()
