#!/usr/bin/env python3
"""검색에 잡히는 개별 페이지를 만든다.

videos.js, briefs.js, stocks.js, notes.js 를 읽어서
  brief/<날짜>/index.html       일간 브리핑
  week/<월요일날짜>/index.html   주간 브리핑
  stock/<종목>/index.html       종목 종합
  brief/, week/, stock/          모아보기
  sitemap.xml
를 만든다. 디자인은 index.html 의 스타일을 그대로 가져다 써서 메인 화면과 똑같이 보인다.
제미나이를 쓰지 않아서 한도나 비용이 들지 않는다. 한 번 만든 페이지는 지우지 않는다.
사용법: python scripts/pages.py
"""
import datetime
import html
import json
import os
import re
from pathlib import Path
import sys
from urllib.parse import quote

try:  # 종목 별칭(하이닉스 -> SK하이닉스)은 summarize.py에 있는 표를 같이 쓴다
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from summarize import canon_stock
except Exception:
    def canon_stock(n):
        return (n or "").strip()

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
    return re.sub(r"[\s·・\-_.()（）]", "", canon_stock(n)).upper()


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


e = lambda s: html.escape(str(s if s is not None else ""), quote=True)


def kdate(d):
    try:
        x = datetime.date.fromisoformat(d)
        return f"{x.year}.{x.month:02d}.{x.day:02d} ({WD[x.weekday()]})"
    except Exception:
        return d or ""


def sdate(d):
    return (d or "")[5:].replace("-", ".")


def url(path):
    return SITE + "/" + path.lstrip("/")


def href(path):
    return BASE + path.lstrip("/")


def desc_of(*parts, n=150):
    t = re.sub(r"\s+", " ", " ".join(x for x in parts if x)).strip()
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


# ---------- 디자인: 메인 화면(index.html)의 스타일을 그대로 쓴다 ----------
def main_css():
    try:
        t = (ROOT / "index.html").read_text(encoding="utf-8")
        return re.search(r"<style>(.*?)</style>", t, re.S).group(1)
    except Exception:
        return ""


EXTRA_CSS = """
.logo{display:block;font-size:2rem;font-weight:800;letter-spacing:-.03em;margin:0 0 16px;color:var(--ink);text-decoration:none}
.nav a{border:0;background:none;padding:10px 16px;font-weight:700;color:var(--sub);text-decoration:none;border-bottom:3px solid transparent;margin-bottom:-1px;flex:none}
.nav{display:flex;gap:4px}
.nav a.on{color:var(--ink);border-bottom-color:var(--accent)}
.foot a{color:var(--accent);text-decoration:none;font-weight:600}
.brief h1{font-size:1.5rem;line-height:1.4;font-weight:800;letter-spacing:-.02em;margin:14px 0 10px}
.bdates a,.bhead .link{border:1px solid var(--line);background:none;color:var(--sub);border-radius:99px;padding:3px 11px;font-size:.8rem;text-decoration:none}
.bdates a:hover{color:var(--accent);border-color:var(--accent)}
a.vc{color:inherit;text-decoration:none}
.vgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(380px,100%),1fr));gap:10px}
.chips a{display:inline-block;background:var(--chip);border-radius:99px;padding:3px 12px;margin:0 6px 6px 0;font-size:.88rem;text-decoration:none;color:var(--ink)}
.plist .tone{margin-left:6px;vertical-align:2px}
.srow .tm{text-decoration:none}
@media(max-width:600px){.logo{font-size:1.55rem}.nav a{padding:10px 12px}.brief h1{font-size:1.22rem}}
"""

POP_JS = """<script>
(()=>{const pop=document.createElement("div");pop.className="pop";pop.hidden=true;document.body.appendChild(pop);let cur=null;
function show(el,html,wide){pop.innerHTML=html;pop.hidden=false;pop.scrollTop=0;const r=el.getBoundingClientRect(),w=Math.min(wide?560:420,innerWidth-24);
pop.style.width=w+"px";pop.style.left=(scrollX+Math.min(Math.max(12,r.left),innerWidth-w-12))+"px";const h=pop.offsetHeight||0;let top=r.bottom+8;
if(h&&top+h>innerHeight&&r.top-8-h>12)top=r.top-8-h;pop.style.top=(scrollY+top)+"px";cur=el}
function hide(){pop.hidden=true;cur=null}
document.addEventListener("click",e=>{const t=e.target;const p=t.closest&&t.closest(".rel,.hv");
 if(p){const tp=document.getElementById(p.dataset.t);if(!tp)return;if(cur===p&&!pop.hidden)hide();else show(p,tp.innerHTML,p.classList.contains("rel"));return}
 const x=t.closest&&t.closest("[data-exp]");if(x){x.classList.toggle("open");return}
 if(!(t.closest&&t.closest(".pop")))hide()});
addEventListener("resize",hide)})();
</script>"""


def page(path, title, desc, body, kind="article", date=None, nav_on="home"):
    canon = url(path)
    ld = ""
    if kind == "article":
        data = {"@context": "https://schema.org", "@type": "Article", "headline": title[:110], "description": desc,
                "url": canon, "inLanguage": "ko", "publisher": {"@type": "Organization", "name": SITE_NAME}}
        if date:
            data["datePublished"] = date
        ld = '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    tabs = [("home", "홈", ""), ("videos", "영상 요약", "#videos"), ("stocks", "종목", "stock/"),
            ("numbers", "숫자·지표", "#numbers"), ("community", "커뮤니티", "#community")]
    nav = "".join(f'<a href="{BASE}{h}" class="{"on" if k == nav_on else ""}">{t}</a>' for k, t, h in tabs)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} | {e(SITE_NAME)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canon)}">
<meta property="og:type" content="{'article' if kind == 'article' else 'website'}"><meta property="og:site_name" content="{e(SITE_NAME)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(canon)}">
<style>{main_css()}{EXTRA_CSS}</style>{ld}</head>
<body><div class="wrap">
<a class="logo" href="{BASE}">{e(SITE_NAME)}</a>
<nav class="nav">{nav}</nav>
{body}
<nav class="foot" style="margin-top:34px;display:flex;flex-wrap:wrap;gap:6px 16px;font-size:.9rem"><a href="{href('brief/')}">일간 브리핑 모아보기</a><a href="{href('week/')}">주간 브리핑 모아보기</a><a href="{href('stock/')}">종목 모아보기</a></nav>
<p class="note">AI가 경제 유튜브 영상과 그 요약을 종합한 내용이라 오류가 있을 수 있다. 투자 권유가 아니며, 정확한 내용은 원본 영상에서 확인해야 한다. 영상과 썸네일의 저작권은 각 채널에 있다.</p>
</div>{POP_JS}</body></html>
"""


def write(path, text):
    p = ROOT / path if path.endswith(".xml") else ROOT / path.strip("/") / "index.html"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and p.read_text(encoding="utf-8") == text:
        return False
    p.write_text(text, encoding="utf-8")
    return True


# ---------- 조각 (메인 화면과 같은 모양) ----------
class Frag:
    def __init__(self, V):
        self.V, self.tpl, self.n = V, {}, 0

    def vcard(self, v):
        vid = vid_of(v.get("url"))
        return (f'<a class="vc" href="{BASE}#v/{e(vid)}"><div class="vl"><div class="vth"><img src="https://img.youtube.com/vi/{e(vid)}/hqdefault.jpg" alt="" loading="lazy"></div>'
                f'<b>{e(v.get("channel"))}</b><small>{e((v.get("date") or "").replace("-", "."))}</small></div>'
                f'<div class="vr"><div class="vt">{e(v.get("title"))}</div><p>{e(v.get("conclusion"))}</p></div></a>')

    def rel(self, ids):
        vs = [self.V[i] for i in dict.fromkeys(ids or []) if i in self.V]
        if not vs:
            return ""
        self.n += 1
        key = f"r{self.n}"
        self.tpl[key] = "".join(self.vcard(v) for v in vs[:6])
        return f'<button class="rel" data-t="{key}">관련 영상 {len(vs)}</button>'

    def hv(self, ref, label=None):
        v = self.V.get(ref)
        if not v:
            return f'<span class="hv">{e(label)}</span>' if label else ""
        key = "v" + ref
        self.tpl[key] = self.vcard(v)
        return f'<button class="hv" data-t="{key}">{e(label or v.get("channel"))}</button>'

    def templates(self):
        return "".join(f'<template id="{k}">{h}</template>' for k, h in self.tpl.items())


def sect(title, n, body, c):
    return f'<div class="bsec"><h3 class="bt {c}">{title}<span class="cn">{n}</span></h3>{body}</div>' if body else ""


def note_box(notes, key):
    n = (notes or {}).get(key)
    return f'<p class="enote"><b>편집자 한마디</b>{e(n)}</p>' if n else ""


def kp_list(items):
    return f'<ul class="kp">{"".join(f"<li>{e(k)}</li>" for k in items or [])}</ul>' if items else ""


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

    stock_slug = {norm(d.get("name")): slug(canon_stock(d.get("name"))) for d in digests.values()}
    for s_, m in man["stock"].items():
        if canon_stock(m.get("name")) == m.get("name"):
            stock_slug.setdefault(norm(m.get("name")), s_)

    def stock_name(name):
        s_ = stock_slug.get(norm(name))
        return f'<a href="{href("stock/" + quote(s_) + "/")}" style="color:inherit">{e(name)}</a>' if s_ else e(name)

    def mark(kind, key, c, extra):
        old = man[kind].get(key)
        man[kind][key] = dict(extra, lastmod=today if c or not old else old.get("lastmod", today))

    # 일간 브리핑
    all_dates = sorted(set(man["brief"]) | {b["date"] for b in briefs})
    week_keys = set(man["week"]) | {w["week"] for w in weekly}
    for b in briefs:
        d, F = b["date"], Frag(V)
        i = all_dates.index(d)
        near = all_dates[max(0, i - 3): i + 4]
        dates = "".join(f'<a href="{href("brief/" + x + "/")}" class="{"on" if x == d else ""}" style="{"background:var(--accent);border-color:var(--accent);color:#fff" if x == d else ""}">{e(sdate(x))}</a>' for x in near)
        wk = (datetime.date.fromisoformat(d) - datetime.timedelta(days=datetime.date.fromisoformat(d).weekday())).isoformat()
        th = "".join(f'<div class="tcard"><b>{e(t["title"])}</b><p data-exp title="눌러서 펼치기">{e(t["summary"])}</p>{F.rel(t.get("refs"))}</div>' for t in b.get("themes") or [])
        ag = "".join(f'<div class="mrow"><span>{e(a["point"])}</span>{F.rel(a.get("refs"))}</div>' for a in b.get("agreements") or [])
        dg = "".join(f'<div class="dblock"><div class="dtopic">{e(x["topic"])}</div><div class="dviews">'
                     + "".join(f'<div class="dv"><span>{e(w["view"])}</span>{F.hv(w.get("ref"), w.get("channel"))}</div>' for w in x.get("views") or [])
                     + "</div></div>" for x in b.get("disagreements") or [])
        sk = "".join(f'<div class="sk"><div class="skh"><b>{stock_name(s["name"])}</b><small>{s.get("count", "")}편에서 언급</small></div>'
                     + "".join(f'<div class="mrow"><span>{e(m["view"])}</span>{F.hv(m.get("ref"), m.get("channel"))}</div>' for m in (s.get("mentions") or [])[:4])
                     + "</div>" for s in b.get("stocks") or [])
        vids = [V[x] for x in b.get("sources") or [] if x in V]
        body = (f'<div class="brief"><div class="bhead"><b>시장 브리핑</b><span>{e(kdate(d))} · 영상 {b.get("count", len(vids))}편 종합</span>'
                + (f'<a class="link" href="{href("week/" + wk + "/")}">주간 브리핑 →</a>' if wk in week_keys else "")
                + f'<span class="bdates">{dates}</span></div>'
                f'<h1>{e(b.get("headline"))}</h1>{kp_list(b.get("keypoints"))}{note_box(notes, d)}'
                + sect("핵심 주제", len(b.get("themes") or []), th and f'<div class="tgrid">{th}</div>', "c1")
                + sect("공통으로 말한 것", len(b.get("agreements") or []), ag, "c2")
                + sect("엇갈린 의견", len(b.get("disagreements") or []), dg, "c3")
                + sect("여러 영상에서 언급된 종목", len(b.get("stocks") or []), sk and f'<div class="skg">{sk}</div>', "c4")
                + sect("이날 요약한 영상", len(vids), vids and '<div class="vgrid">' + "".join(F.vcard(v) for v in vids) + "</div>", "")
                + '<p class="bnote">AI가 이날의 영상 요약들을 종합한 내용이며 투자 권유가 아니다. \'관련 영상\'이나 채널 이름을 누르면 근거가 된 영상을 볼 수 있다.</p></div>'
                + F.templates())
        c = write(f"brief/{d}", page(f"brief/{d}/", f"{sdate(d)} 시장 브리핑: {b.get('headline', '')}", desc_of(*(b.get("keypoints") or [])), body, date=d))
        changed += c
        mark("brief", d, c, {"headline": b.get("headline"), "count": b.get("count")})

    # 주간 브리핑
    for w in weekly:
        ws = w["week"]
        fl = "".join(f'<dt>{e(sdate(f["date"]))}({WD[datetime.date.fromisoformat(f["date"]).weekday()]})</dt><dd>{e(f["point"])}'
                     + (f' <a class="link" href="{href("brief/" + f["date"] + "/")}">브리핑 →</a>' if f["date"] in man["brief"] else "") + "</dd>"
                     for f in w.get("flow") or [])
        rc = "".join(f'<div class="tcard"><b>{e(r["title"])}</b><p data-exp title="눌러서 펼치기">{e(r["summary"])}</p><small>{len(r.get("dates") or [])}일 등장 · '
                     + ", ".join(f'<a href="{href("brief/" + x + "/")}">{e(sdate(x))}</a>' if x in man["brief"] else e(sdate(x)) for x in r.get("dates") or [])
                     + "</small></div>" for r in w.get("recurring") or [])
        sw = "".join(f'<div class="sk"><div class="skh"><b>{stock_name(s["name"])}</b><small>{s.get("videos")}편 · {len(s.get("days") or [])}일</small></div><p>{e(s["note"])}</p></div>'
                     for s in w.get("stocks") or [])
        body = (f'<div class="brief"><div class="bhead"><b>주간 브리핑</b><span>{e(kdate(ws))} ~ {e(kdate(w.get("end")))} · 영상 {w.get("videos", "")}편 종합</span></div>'
                f'<h1>{e(w.get("headline"))}</h1>{kp_list(w.get("keypoints"))}{note_box(notes, "week:" + ws)}'
                + sect("하루하루의 흐름", len(w.get("flow") or []), fl and f'<dl class="tl">{fl}</dl>', "c1")
                + sect("이번 주 반복된 주제", len(w.get("recurring") or []), rc and f'<div class="tgrid">{rc}</div>', "c2")
                + sect("이번 주 많이 언급된 종목", len(w.get("stocks") or []), sw and f'<div class="skg">{sw}</div>', "c4")
                + '<p class="bnote">AI가 이번 주의 일간 브리핑들을 종합한 내용이며 투자 권유가 아니다.</p></div>')
        c = write(f"week/{ws}", page(f"week/{ws}/", f"{sdate(ws)}~{sdate(w.get('end'))} 주간 시장 브리핑: {w.get('headline', '')}",
                                     desc_of(*(w.get("keypoints") or [])), body, date=w.get("gen_date") or ws))
        changed += c
        mark("week", ws, c, {"headline": w.get("headline"), "end": w.get("end"), "videos": w.get("videos")})

    # 종목 페이지: 2편 이상에서 언급된 모든 종목 (종합 정리가 있으면 맨 위에 보여 준다)
    table = {}
    for v in V.values():
        for row in v.get("stocks") or []:
            if len(row) >= 3 and norm(row[1]):
                t = table.setdefault(norm(row[1]), {"names": {}, "items": []})
                t["names"][row[1]] = t["names"].get(row[1], 0) + 1
                t["items"].append((v, row))
    dig_by = {}
    for d in digests.values():  # 같은 종목의 종합이 여러 개면(예전 별칭 이름으로 만든 것) 최신 것을 쓴다
        k = norm(d.get("name"))
        if k not in dig_by or (d.get("updated") or "", d.get("count") or 0) > (dig_by[k].get("updated") or "", dig_by[k].get("count") or 0):
            dig_by[k] = d
    brief_days = {}
    for b in briefs:
        for s in b.get("stocks") or []:
            brief_days.setdefault(norm(s["name"]), set()).add(b["date"])

    def tm(v, t):
        vid = vid_of(v.get("url"))
        return f'<a class="tm" href="https://www.youtube.com/watch?v={e(vid)}&t={secs(t)}s" target="_blank" rel="noopener">▶ {e(t)}</a>' if t and vid else ""

    for k, t in table.items():
        vids_ = {vid_of(v.get("url")) for v, _ in t["items"]}
        if len(vids_) < 2 and k not in dig_by:
            continue  # 한 편에서만 나온 종목은 내용이 얇아서 페이지를 만들지 않는다
        d = dig_by.get(k)
        name = canon_stock(d.get("name") if d else max(t["names"], key=t["names"].get))
        s_, F = slug(name), Frag(V)
        ms = sorted(t["items"], key=lambda x: x[0].get("date", ""), reverse=True)
        chans = {v.get("channel") for v, _ in ms}
        last = ms[0][0].get("date", "") if ms else ""
        rows = "".join(f'<p class="srow"><small>{e(sdate(v.get("date")))}</small><span>{e(row[2])}</span><span class="rt">{F.hv(vid_of(v.get("url")))}{tm(v, row[0])}</span></p>'
                       for v, row in ms[:40])
        bd = [x for x in sorted(brief_days.get(k, set()), reverse=True) if x in man["brief"]]
        tone = d.get("tone") if d else None
        dig = (f'<div class="digest"><div class="dh"><b>종합</b><span>영상 {d.get("count")}편 기준 · {e(sdate(d.get("updated")))} 정리</span></div><p>{e(d.get("summary"))}</p>'
               + ("<ul>" + "".join(f"<li>{e(p)}</li>" for p in d.get("points") or []) + "</ul>" if d.get("points") else "") + "</div>") if d else ""
        body = (f'<div class="brief"><div class="bhead"><b>종목</b><span>영상 {len(vids_)}편 · {len(chans)}채널 · 마지막 언급 {e(sdate(last))}</span>'
                f'<a class="link" href="{href("stock/")}">전체 종목 →</a></div>'
                f'<h1>{e(name)}{f" <span class=\"tone t{e(tone)}\" style=\"font-size:.8rem;vertical-align:5px\">{e(tone)}</span>" if tone else ""}</h1>{dig}'
                + sect("채널별 언급", len(ms[:40]), rows and f'<div class="skrb" style="padding:0">{rows}</div>', "c4")
                + sect("이 종목이 나온 브리핑", len(bd), bd and '<div class="chips">' + "".join(f'<a href="{href("brief/" + x + "/")}">{e(sdate(x))}</a>' for x in bd) + "</div>", "c1")
                + "</div>" + F.templates())
        desc = desc_of(d.get("summary"), *(d.get("points") or [])) if d else desc_of(f"{name}에 대해 경제 유튜브 채널 {len(chans)}곳이 한 말을 모았다.", *[r[2] for _, r in ms[:3]])
        c = write(f"stock/{s_}", page(f"stock/{quote(s_)}/", f"{name}: 경제 유튜브 채널들의 시각", desc, body, date=(d or {}).get("updated") or last, nav_on="stocks"))
        changed += c
        mark("stock", s_, c, {"name": name, "tone": tone, "count": len(vids_), "channels": len(chans), "last": last})

    # 예전에 별칭 이름(예: 하이닉스)으로 만든 종목 페이지는 정식 이름 페이지로 넘기고 목록에서 뺀다
    for s_, m in list(man["stock"].items()):
        c_ = canon_stock(m.get("name"))
        if c_ != m.get("name") and slug(c_) != s_:
            to = href("stock/" + quote(slug(c_)) + "/")
            changed += write(f"stock/{s_}", f'<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8"><title>{e(c_)}</title>'
                             f'<link rel="canonical" href="{SITE}/stock/{quote(slug(c_))}/"><meta name="robots" content="noindex">'
                             f'<meta http-equiv="refresh" content="0; url={to}"></head><body><a href="{to}">{e(c_)} 페이지로 이동</a></body></html>')
            del man["stock"][s_]

    # 모아보기
    def listing(path, title, desc, items, nav_on="home", extra="", script=""):
        body = f'<div class="brief"><h1 style="margin-top:0">{title}</h1>{extra}' + (f'<ul class="plist" id="plist">{items}</ul>' if items else '<div class="empty">아직 없다.</div>') + "</div>" + script
        return write(path, page(path + "/", title, desc, body, kind="list", nav_on=nav_on))

    changed += listing("brief", "일간 시장 브리핑", "경제 유튜브 채널들의 영상을 하루 단위로 종합한 시장 브리핑 목록이다.",
                       "".join(f'<li><a href="{href("brief/" + d + "/")}"><b>{e(m.get("headline"))}</b><small>{e(kdate(d))} · 영상 {e(m.get("count"))}편</small></a></li>'
                               for d, m in sorted(man["brief"].items(), reverse=True)))
    changed += listing("week", "주간 시장 브리핑", "경제 유튜브 채널들의 한 주 흐름을 종합한 주간 브리핑 목록이다.",
                       "".join(f'<li><a href="{href("week/" + w + "/")}"><b>{e(m.get("headline"))}</b><small>{e(sdate(w))} ~ {e(sdate(m.get("end")))} · 영상 {e(m.get("videos"))}편</small></a></li>'
                               for w, m in sorted(man["week"].items(), reverse=True)))
    stock_bar = ('<div class="vbar"><input id="sq" type="search" placeholder="종목 이름 검색" aria-label="종목 검색">'
                 '<div class="chips" id="sr"><button class="chip" data-r="7">7일</button><button class="chip" data-r="30" aria-pressed="true">30일</button><button class="chip" data-r="all">전체</button></div></div>')
    stock_js = """<script>
(()=>{const q=document.getElementById("sq"),rows=[...document.querySelectorAll("#plist li")];let r="30";
const p=new URLSearchParams(location.search).get("q");if(p)q.value=p;
const nk=s=>s.replace(/[\\s·・\\-_.()（）]/g,"").toUpperCase();
function f(){const cut=r==="all"?"":new Date(Date.now()+9*36e5-(+r-1)*864e5).toISOString().slice(0,10),k=nk(q.value);let n=0;
rows.forEach(li=>{const ok=(!cut||li.dataset.last>=cut)&&(!k||nk(li.dataset.name).includes(k));li.hidden=!ok;if(ok)n++});
document.querySelectorAll("#sr .chip").forEach(b=>b.setAttribute("aria-pressed",b.dataset.r===r));
let em=document.getElementById("sempty");if(!em){em=document.createElement("div");em.id="sempty";em.className="empty";em.textContent="조건에 맞는 종목이 없다.";document.getElementById("plist").after(em)}em.hidden=n>0}
q.addEventListener("input",f);document.getElementById("sr").addEventListener("click",e=>{const b=e.target.closest(".chip");if(b){r=b.dataset.r;f()}});f()})();
</script>"""
    changed += listing("stock", "종목", "여러 경제 유튜브 채널에서 언급된 종목을 종목별로 모아 채널들의 시각을 정리했다.",
                       "".join(f'<li data-name="{e(m.get("name"))}" data-last="{e(m.get("last") or "")}"><a href="{href("stock/" + quote(s_) + "/")}"><b>{e(m.get("name"))}'
                               + (f'<span class="tone t{e(m.get("tone"))}">{e(m.get("tone"))}</span>' if m.get("tone") else "")
                               + f'</b><small>영상 {e(m.get("count"))}편{" · " + str(m.get("channels")) + "채널" if m.get("channels") else ""}{" · 마지막 언급 " + sdate(m.get("last")) if m.get("last") else ""}</small></a></li>'
                               for s_, m in sorted(man["stock"].items(), key=lambda x: (-(x[1].get("count") or 0), x[1].get("name") or ""))),
                       nav_on="stocks", extra=stock_bar, script=stock_js)

    # 사이트맵
    urls = [(url(""), today), (url("brief/"), today), (url("week/"), today), (url("stock/"), today)]
    urls += [(url(f"brief/{d}/"), m.get("lastmod", today)) for d, m in man["brief"].items()]
    urls += [(url(f"week/{w}/"), m.get("lastmod", today)) for w, m in man["week"].items()]
    urls += [(url(f"stock/{quote(s_)}/"), m.get("lastmod", today)) for s_, m in man["stock"].items()]
    (ROOT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      + "".join(f"<url><loc>{html.escape(u)}</loc><lastmod>{lm}</lastmod></url>\n" for u, lm in urls) + "</urlset>\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"개별 페이지: 일간 {len(man['brief'])}개, 주간 {len(man['week'])}개, 종목 {len(man['stock'])}개 (이번에 바뀐 페이지 {changed}개)")
    return changed


if __name__ == "__main__":
    build()
