#!/usr/bin/env python3
"""검색에 잡히는 개별 페이지를 만든다.

videos.js, briefs.js, stocks.js, notes.js 를 읽어서
  brief/<날짜>/index.html   일간 브리핑
  week/<월요일날짜>/index.html  주간 브리핑
  stock/<종목>/index.html   종목 종합
  brief/index.html, week/index.html, stock/index.html  모아보기
  sitemap.xml
를 만든다. 제미나이를 쓰지 않아서 한도나 비용이 들지 않는다.
한 번 만든 페이지는 지우지 않는다. (데이터에서 빠진 옛 브리핑도 페이지로 남는다)
사용법: python scripts/pages.py
"""
import datetime
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
SITE = os.environ.get("SITE_URL", "https://econo-tube-note.github.io/econo-tube-note").rstrip("/")
BASE = "/" + SITE.split("://", 1)[1].split("/", 1)[1].strip("/") + "/" if SITE.count("/") > 2 else "/"
SITE_NAME = os.environ.get("SITE_NAME", "경제 유튜브 요약")
MANIFEST = ROOT / "pages.json"
KST = datetime.timezone(datetime.timedelta(hours=9))
WD = "월화수목금토일"


# ---------- 데이터 읽기 ----------
def read_const(path, name, default):
    try:
        t = Path(path).read_text(encoding="utf-8")
    except Exception:
        return default
    i = t.find(f"const {name}=")
    if i < 0:
        return default
    try:
        return json.JSONDecoder().raw_decode(t[i + len(f"const {name}="):].lstrip())[0]
    except Exception:
        return default


def vid_of(url):
    m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def norm(n):
    return re.sub(r"[\s·・\-_.()（）]", "", n or "").upper()


def slug(name):
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "-", name or "").strip("-")
    return s or "stock"


def secs(t):
    n = 0
    for p in (t or "").split(":"):
        if not p.isdigit():
            return 0
        n = n * 60 + int(p)
    return n


# ---------- 공통 틀 ----------
e = lambda s: html.escape(str(s or ""), quote=True)


def kdate(d):
    try:
        x = datetime.date.fromisoformat(d)
        return f"{x.year}년 {x.month}월 {x.day}일 ({WD[x.weekday()]})"
    except Exception:
        return d


def sdate(d):
    return (d or "")[5:].replace("-", ".")


def url(path):
    return SITE + "/" + path.lstrip("/")


def href(path):
    return BASE + path.lstrip("/")


CSS = """:root{--bg:#f4f5f8;--card:#fff;--ink:#14181f;--sub:#5d6573;--line:#e1e4ea;--accent:#2457f5;--chip:#eef1f7}
@media (prefers-color-scheme:dark){:root{--bg:#0f1217;--card:#181c24;--ink:#eef1f6;--sub:#9aa3b2;--line:#272d38;--accent:#7b99ff;--chip:#222833}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Noto Sans KR","Malgun Gothic",sans-serif;line-height:1.7}
a{color:var(--accent)}.wrap{max-width:860px;margin:0 auto;padding:28px 18px 56px}
.top{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:center;font-size:.9rem;margin-bottom:20px}.top a{text-decoration:none;font-weight:700}.top .home{color:var(--ink);font-size:1.05rem;margin-right:auto}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 22px 18px;margin-bottom:18px}
.eyebrow{color:var(--accent);font-weight:800;font-size:.9rem}.meta{color:var(--sub);font-size:.88rem}
h1{font-size:1.6rem;line-height:1.4;letter-spacing:-.02em;margin:8px 0 12px}
h2{font-size:1.15rem;margin:0 0 12px}
ul.kp{margin:0;padding-left:20px}ul.kp li{margin:4px 0}
.note{margin:14px 0 0;padding:10px 14px;border-left:4px solid var(--accent);background:var(--chip);border-radius:0 10px 10px 0}
.item{padding:10px 0;border-top:1px solid var(--line)}.item:first-of-type{border-top:0}.item b{display:block}
.src{font-size:.82rem;color:var(--sub)}.src a{color:var(--sub)}
.tone{display:inline-block;font-size:.76rem;font-weight:800;border-radius:99px;padding:1px 10px;color:#fff;background:#8a93a3}
.t긍정{background:#12805c}.t부정{background:#c62828}.t혼재{background:#c2410c}
.vids{display:grid;gap:10px}.v{display:grid;grid-template-columns:120px minmax(0,1fr);gap:12px;align-items:start;color:inherit;text-decoration:none}
.v img{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:var(--chip)}.v small{color:var(--sub)}.v b{display:block;font-size:.95rem;line-height:1.5}.v span{font-size:.85rem;color:var(--sub)}
.pn{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;font-size:.92rem}
.list a{display:block;padding:10px 0;border-top:1px solid var(--line);text-decoration:none;color:var(--ink)}.list a:first-child{border-top:0}.list small{display:block;color:var(--sub)}
.chips{display:flex;flex-wrap:wrap;gap:6px}.chips a{background:var(--chip);border-radius:99px;padding:2px 12px;font-size:.88rem;text-decoration:none;color:var(--ink)}
footer{color:var(--sub);font-size:.8rem;margin-top:30px}
@media(max-width:600px){.wrap{padding:18px 12px 40px}.card{padding:16px 14px}h1{font-size:1.3rem}.v{grid-template-columns:96px minmax(0,1fr)}}"""


def page(path, title, desc, body, kind="article", date=None, jsonld=True):
    canon = url(path)
    ld = ""
    if jsonld:
        data = {"@context": "https://schema.org", "@type": "Article" if kind == "article" else "CollectionPage",
                "headline": title[:110], "description": desc, "url": canon, "inLanguage": "ko",
                "publisher": {"@type": "Organization", "name": SITE_NAME}}
        if date:
            data["datePublished"] = date
        ld = '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    nav = (f'<nav class="top"><a class="home" href="{href("")}">{e(SITE_NAME)}</a>'
           f'<a href="{href("brief/")}">일간 브리핑</a><a href="{href("week/")}">주간 브리핑</a><a href="{href("stock/")}">종목</a></nav>')
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} | {e(SITE_NAME)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canon)}">
<meta property="og:type" content="{'article' if kind == 'article' else 'website'}"><meta property="og:site_name" content="{e(SITE_NAME)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(canon)}">
<style>{CSS}</style>{ld}</head>
<body><div class="wrap">{nav}{body}
<footer>AI가 경제 유튜브 영상과 그 요약을 종합한 내용이며 오류가 있을 수 있다. 투자 권유가 아니며, 정확한 내용은 원본 영상에서 확인해야 한다. 영상과 썸네일의 저작권은 각 채널에 있다.</footer>
</div></body></html>
"""


def write(path, text):
    p = ROOT / path.strip("/") / "index.html" if not path.endswith(".xml") else ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    old = p.read_text(encoding="utf-8") if p.exists() else None
    if old != text:
        p.write_text(text, encoding="utf-8")
        return True
    return False


def desc_of(*parts, n=150):
    t = " ".join(x for x in parts if x)
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# ---------- 조각 ----------
def vlink(v, t=None, label=None):
    vid = vid_of(v.get("url"))
    u = f"https://www.youtube.com/watch?v={vid}" + (f"&t={secs(t)}s" if t else "")
    return f'<a href="{e(u)}" target="_blank" rel="noopener">{e(label or v.get("channel"))}</a>'


def src_line(ids, V):
    out = []
    for i in dict.fromkeys(ids or []):
        v = V.get(i)
        if v:
            out.append(vlink(v))
    return f'<div class="src">근거 영상: {" · ".join(out)}</div>' if out else ""


def vcard(v):
    vid = vid_of(v.get("url"))
    return (f'<a class="v" href="https://www.youtube.com/watch?v={e(vid)}" target="_blank" rel="noopener">'
            f'<img src="https://img.youtube.com/vi/{e(vid)}/mqdefault.jpg" alt="" loading="lazy">'
            f'<div><small>{e(v.get("channel"))} · {e(sdate(v.get("date")))}</small><b>{e(v.get("conclusion"))}</b><span>{e(v.get("title"))}</span></div></a>')


def note_box(notes, key):
    n = (notes or {}).get(key)
    return f'<p class="note"><b>편집자 한마디</b> {e(n)}</p>' if n else ""


# ---------- 페이지 만들기 ----------
def build():
    videos = read_const(ROOT / "videos.js", "VIDEOS", [])
    try:
        videos = videos + json.loads((ROOT / "archive.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    V = {vid_of(v.get("url")): v for v in videos if vid_of(v.get("url"))}
    briefs = read_const(ROOT / "briefs.js", "BRIEFS", [])
    weekly = read_const(ROOT / "briefs.js", "WEEKLY", [])
    digests = read_const(ROOT / "stocks.js", "STOCKSUM", {})
    notes = read_const(ROOT / "notes.js", "NOTES", {})
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        man = {}
    for k in ("brief", "week", "stock"):
        man.setdefault(k, {})
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    changed = 0

    # 종목 페이지 주소 (브리핑에서 링크할 때 쓴다)
    stock_slug = {norm(d.get("name")): slug(d.get("name")) for d in digests.values()}
    for s, m in man["stock"].items():
        stock_slug.setdefault(norm(m.get("name")), s)

    def stock_a(name):
        s = stock_slug.get(norm(name))
        return f'<a href="{href("stock/" + quote(s) + "/")}">{e(name)}</a>' if s else e(name)

    # 일간 브리핑
    all_dates = sorted(set(man["brief"]) | {b["date"] for b in briefs})
    for b in briefs:
        d = b["date"]
        i = all_dates.index(d)
        prev_d = all_dates[i - 1] if i > 0 else None
        next_d = all_dates[i + 1] if i + 1 < len(all_dates) else None
        title = f"{sdate(d)} 시장 브리핑: {b.get('headline', '')}"
        desc = desc_of(*(b.get("keypoints") or []))
        th = "".join(f'<div class="item"><b>{e(t["title"])}</b>{e(t["summary"])}{src_line(t.get("refs"), V)}</div>' for t in b.get("themes") or [])
        ag = "".join(f'<div class="item">{e(a["point"])}{src_line(a.get("refs"), V)}</div>' for a in b.get("agreements") or [])
        dg = "".join(f'<div class="item"><b>{e(x["topic"])}</b>' + "".join(
            f'<div>{e(w["view"])} <span class="src">— {vlink(V[w["ref"]]) if w.get("ref") in V else e(w.get("channel"))}</span></div>' for w in x.get("views") or []) + "</div>"
            for x in b.get("disagreements") or [])
        sk = "".join(f'<div class="item"><b>{stock_a(s["name"])} <span class="meta">{s.get("count", "")}편에서 언급</span></b>' + "".join(
            f'<div>{e(m["view"])} <span class="src">— {vlink(V[m["ref"]]) if m.get("ref") in V else e(m.get("channel"))}</span></div>' for m in (s.get("mentions") or [])[:4]) + "</div>"
            for s in b.get("stocks") or [])
        vids = [V[i] for i in b.get("sources") or [] if i in V]
        prev_a = f'<a href="{href("brief/" + prev_d + "/")}">← {e(sdate(prev_d))} 브리핑</a>' if prev_d else "<span></span>"
        next_a = f'<a href="{href("brief/" + next_d + "/")}">{e(sdate(next_d))} 브리핑 →</a>' if next_d else "<span></span>"
        wk = (datetime.date.fromisoformat(d) - datetime.timedelta(days=datetime.date.fromisoformat(d).weekday())).isoformat()
        body = (f'<article class="card"><div class="eyebrow">{e(kdate(d))} 시장 브리핑</div><h1>{e(b.get("headline"))}</h1>'
                f'<div class="meta">경제 유튜브 영상 {b.get("count", len(vids))}편을 종합했다</div>'
                f'<ul class="kp">{"".join(f"<li>{e(k)}</li>" for k in b.get("keypoints") or [])}</ul>{note_box(notes, d)}</article>'
                + (f'<section class="card"><h2>핵심 주제</h2>{th}</section>' if th else "")
                + (f'<section class="card"><h2>공통으로 말한 것</h2>{ag}</section>' if ag else "")
                + (f'<section class="card"><h2>엇갈린 의견</h2>{dg}</section>' if dg else "")
                + (f'<section class="card"><h2>여러 영상에서 언급된 종목</h2>{sk}</section>' if sk else "")
                + (f'<section class="card"><h2>이날 요약한 영상</h2><div class="vids">{"".join(vcard(v) for v in vids)}</div></section>' if vids else "")
                + f'<div class="pn">{prev_a}'
                + (f'<a href="{href("week/" + wk + "/")}">이 주의 주간 브리핑</a>' if wk in man["week"] or any(x["week"] == wk for x in weekly) else "")
                + f'{next_a}</div>')
        c = write(f"brief/{d}", page(f"brief/{d}/", title, desc, body, date=d))
        changed += c
        man["brief"][d] = {"headline": b.get("headline"), "count": b.get("count"),
                           "lastmod": today if c or d not in man["brief"] else man["brief"][d].get("lastmod", today)}

    # 주간 브리핑
    for w in weekly:
        ws = w["week"]
        title = f"{sdate(ws)}~{sdate(w.get('end'))} 주간 시장 브리핑: {w.get('headline', '')}"
        desc = desc_of(*(w.get("keypoints") or []))
        fl = "".join(f'<div class="item"><b>{e(kdate(f["date"]))}</b>{e(f["point"])} '
                     + (f'<a href="{href("brief/" + f["date"] + "/")}">브리핑 보기</a>' if f["date"] in man["brief"] else "") + "</div>"
                     for f in w.get("flow") or [])
        rc = "".join(f'<div class="item"><b>{e(r["title"])}</b>{e(r["summary"])}<div class="src">{len(r.get("dates", []))}일 등장: '
                     + " · ".join(f'<a href="{href("brief/" + x + "/")}">{e(sdate(x))}</a>' if x in man["brief"] else e(sdate(x)) for x in r.get("dates") or []) + "</div></div>"
                     for r in w.get("recurring") or [])
        sw = "".join(f'<div class="item"><b>{stock_a(s["name"])} <span class="meta">{s.get("videos")}편 · {len(s.get("days") or [])}일</span></b>{e(s["note"])}</div>'
                     for s in w.get("stocks") or [])
        body = (f'<article class="card"><div class="eyebrow">{e(kdate(ws))} ~ {e(kdate(w.get("end")))} 주간 브리핑</div><h1>{e(w.get("headline"))}</h1>'
                f'<div class="meta">이번 주 경제 유튜브 영상 {w.get("videos", "")}편을 종합했다</div>'
                f'<ul class="kp">{"".join(f"<li>{e(k)}</li>" for k in w.get("keypoints") or [])}</ul>{note_box(notes, "week:" + ws)}</article>'
                + (f'<section class="card"><h2>하루하루의 흐름</h2>{fl}</section>' if fl else "")
                + (f'<section class="card"><h2>이번 주 반복된 주제</h2>{rc}</section>' if rc else "")
                + (f'<section class="card"><h2>이번 주 많이 언급된 종목</h2>{sw}</section>' if sw else ""))
        c = write(f"week/{ws}", page(f"week/{ws}/", title, desc, body, date=w.get("gen_date") or ws))
        changed += c
        man["week"][ws] = {"headline": w.get("headline"), "end": w.get("end"), "videos": w.get("videos"),
                           "lastmod": today if c or ws not in man["week"] else man["week"][ws].get("lastmod", today)}

    # 종목 페이지
    mentions = {}
    for v in V.values():
        for row in v.get("stocks") or []:
            if len(row) >= 3:
                mentions.setdefault(norm(row[1]), []).append((v, row))
    brief_days = {}
    for b in briefs:
        for s in b.get("stocks") or []:
            brief_days.setdefault(norm(s["name"]), set()).add(b["date"])
    for k, d in digests.items():
        name, s = d.get("name"), slug(d.get("name"))
        ms = sorted(mentions.get(norm(name), []), key=lambda x: x[0].get("date", ""), reverse=True)
        title = f"{name}: 경제 유튜브 채널들의 시각 종합"
        desc = desc_of(d.get("summary"), *(d.get("points") or []))
        rows = "".join(f'<div class="item"><span class="meta">{e(sdate(v.get("date")))}</span> {e(row[2])} '
                       f'<span class="src">— {vlink(v, row[0] if len(row) > 0 else None, v.get("channel") + (" ▶" + row[0] if row[0] else ""))}</span></div>'
                       for v, row in ms[:40])
        bd = sorted(brief_days.get(norm(name), set()), reverse=True)
        body = (f'<article class="card"><div class="eyebrow">종목 종합</div><h1>{e(name)} <span class="tone t{e(d.get("tone"))}">{e(d.get("tone"))}</span></h1>'
                f'<div class="meta">경제 유튜브 영상 {d.get("count")}편 기준 · {e(sdate(d.get("updated")))} 정리</div>'
                f'<p><b>{e(d.get("summary"))}</b></p><ul class="kp">{"".join(f"<li>{e(p)}</li>" for p in d.get("points") or [])}</ul></article>'
                + (f'<section class="card"><h2>채널별 언급</h2>{rows}</section>' if rows else "")
                + (f'<section class="card"><h2>이 종목이 나온 브리핑</h2><div class="chips">'
                   + "".join(f'<a href="{href("brief/" + x + "/")}">{e(sdate(x))}</a>' for x in bd if x in man["brief"]) + "</div></section>" if bd else ""))
        c = write(f"stock/{s}", page(f"stock/{quote(s)}/", title, desc, body, date=d.get("updated")))
        changed += c
        man["stock"][s] = {"name": name, "tone": d.get("tone"), "count": d.get("count"),
                           "lastmod": today if c or s not in man["stock"] else man["stock"][s].get("lastmod", today)}

    # 모아보기 페이지
    bl = "".join(f'<a href="{href("brief/" + d + "/")}"><b>{e(m.get("headline"))}</b><small>{e(kdate(d))} · 영상 {e(m.get("count"))}편</small></a>'
                 for d, m in sorted(man["brief"].items(), reverse=True))
    changed += write("brief", page("brief/", "일간 시장 브리핑 모아보기", "경제 유튜브 채널들의 영상을 하루 단위로 종합한 시장 브리핑 목록이다.",
                                   f'<section class="card"><h1>일간 시장 브리핑</h1><div class="list">{bl or "아직 없다."}</div></section>', kind="list", jsonld=False))
    wl = "".join(f'<a href="{href("week/" + w + "/")}"><b>{e(m.get("headline"))}</b><small>{e(sdate(w))} ~ {e(sdate(m.get("end")))} · 영상 {e(m.get("videos"))}편</small></a>'
                 for w, m in sorted(man["week"].items(), reverse=True))
    changed += write("week", page("week/", "주간 시장 브리핑 모아보기", "경제 유튜브 채널들의 한 주 흐름을 종합한 주간 브리핑 목록이다.",
                                  f'<section class="card"><h1>주간 시장 브리핑</h1><div class="list">{wl or "아직 없다."}</div></section>', kind="list", jsonld=False))
    sl = "".join(f'<a href="{href("stock/" + quote(s) + "/")}"><b>{e(m.get("name"))} <span class="tone t{e(m.get("tone"))}">{e(m.get("tone"))}</span></b><small>영상 {e(m.get("count"))}편 기준</small></a>'
                 for s, m in sorted(man["stock"].items(), key=lambda x: -(x[1].get("count") or 0)))
    changed += write("stock", page("stock/", "종목별 유튜브 시각 종합", "여러 경제 유튜브 채널에서 언급된 종목을 종목별로 종합한 목록이다.",
                                   f'<section class="card"><h1>종목별 종합</h1><div class="list">{sl or "아직 없다."}</div></section>', kind="list", jsonld=False))

    # 사이트맵
    urls = [(url(""), today), (url("brief/"), today), (url("week/"), today), (url("stock/"), today)]
    urls += [(url(f"brief/{d}/"), m.get("lastmod", today)) for d, m in man["brief"].items()]
    urls += [(url(f"week/{w}/"), m.get("lastmod", today)) for w, m in man["week"].items()]
    urls += [(url(f"stock/{quote(s)}/"), m.get("lastmod", today)) for s, m in man["stock"].items()]
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + "".join(
        f"<url><loc>{html.escape(u)}</loc><lastmod>{lm}</lastmod></url>\n" for u, lm in urls) + "</urlset>\n"
    (ROOT / "sitemap.xml").write_text(sm, encoding="utf-8")
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"개별 페이지: 일간 {len(man['brief'])}개, 주간 {len(man['week'])}개, 종목 {len(man['stock'])}개 (이번에 바뀐 페이지 {changed}개)")
    return changed


if __name__ == "__main__":
    build()
