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
SITE = os.environ.get("SITE_URL", "https://marketraven.kr").rstrip("/")
BASE = "/" + SITE.split("://", 1)[1].split("/", 1)[1].strip("/") + "/" if SITE.count("/") > 2 else "/"
SITE_NAME = os.environ.get("SITE_NAME", "Market Raven")
GA_ID = os.environ.get("GA_ID", "G-RNKNJWH6EC")  # 방문 통계 (Google 애널리틱스 측정 ID, 공개해도 되는 값)
TAGLINE = "경제 유튜브, 대신 보고 핵심만 전한다"
CONTACT = os.environ.get("CONTACT_EMAIL", "gomajjy0@gmail.com")
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


def video_ld(v, vid):
    """검색엔진용 영상 정보(VideoObject): 원본 유튜브 영상을 가리킨다"""
    d = v.get("date") or ""
    data = {"@context": "https://schema.org", "@type": "VideoObject", "name": (v.get("title") or "")[:200],
            "description": v.get("conclusion") or v.get("title") or "",
            "thumbnailUrl": [f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"],
            "embedUrl": f"https://www.youtube.com/embed/{vid}", "url": f"https://www.youtube.com/watch?v={vid}",
            "inLanguage": "ko", "author": {"@type": "Organization", "name": v.get("channel") or ""}}
    if re.match(r"\d{4}-\d{2}-\d{2}$", d):
        data["uploadDate"] = d + "T00:00:00+09:00"
    return data


def short_title(t):
    """탭·검색 결과용 짧은 제목: 앞뒤의 [말머리]·#번호와 | 뒤 출연자 표기를 뺀다"""
    s = (t or "").strip()
    s = re.sub(r"^(\s*[\[【][^\]】]{0,20}[\]】]\s*)+", "", s)
    s = re.split(r"[|ㅣ｜]", s)[0]
    s = re.sub(r"(\s*([\[【][^\]】]{0,20}[\]】]|#\d+))+\s*$", "", s).strip(" -·")
    if len(s) < 6:
        s = (t or "").strip()
    return re.sub(r"\s+", " ", s)


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
.logo{font-size:2rem;font-weight:800;letter-spacing:-.03em;margin:0 0 16px;color:var(--ink)}
@media(max-width:640px){.logo{font-size:1.55rem}}
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
.bli{display:flex!important;gap:18px;align-items:center}
.bld{flex:none;width:76px;display:flex;flex-direction:column}
.bld b{font-size:1.45rem!important;font-weight:800!important;letter-spacing:-.03em;line-height:1.1;color:var(--ink)}
.bld.wk b{font-size:1.15rem!important}
.bld small{margin-top:2px!important}
.vpage .bhead>b{font-size:1.15rem}
.vtop{display:grid;grid-template-columns:300px minmax(0,1fr);grid-template-rows:auto auto 1fr;grid-template-areas:"hero meta" "hero title" "hero btn";gap:6px 20px;align-items:start;margin:14px 0 18px}
.vhero{grid-area:hero;display:block;position:relative;border-radius:12px;overflow:hidden;aspect-ratio:16/9;background:linear-gradient(135deg,#dbe3f4,#b9c6e6)}
.vhero img{width:100%;height:100%;object-fit:cover;display:block}
.vhero iframe{width:100%;height:100%;border:0;display:block}
.vhero i{position:absolute;inset:0;margin:auto;width:44px;height:31px;border-radius:9px;background:rgba(0,0,0,.7);color:#fff;font-style:normal;display:flex;align-items:center;justify-content:center;font-size:.85rem}
.vmeta{grid-area:meta;display:flex;flex-wrap:wrap;align-items:center;gap:2px 8px;font-size:.85rem;color:var(--sub)}
.vmeta b{color:var(--accent)}
.vshr{all:unset;cursor:pointer;color:var(--sub);font-size:.8rem;border:1px solid var(--line);border-radius:99px;padding:1px 10px}.vshr:hover{color:var(--accent);border-color:var(--accent)}
.vshr{margin-left:auto}.vmeta a+.vshr{margin-left:6px}
#shtoast{position:fixed;left:50%;bottom:24px;transform:translate(-50%,20px);background:#14181f;color:#fff;font-size:.88rem;padding:10px 16px;border-radius:10px;opacity:0;pointer-events:none;transition:.2s;max-width:90vw;word-break:break-all;z-index:99}
#shtoast.on{opacity:1;transform:translate(-50%,0);pointer-events:auto}
button.link.shr{font:inherit;cursor:pointer}
.vmeta a{margin-left:auto;color:var(--sub);text-decoration:none;font-size:.8rem}
.vmeta a:hover{color:var(--accent)}
.brief .vh1{grid-area:title;font-size:1.1rem;line-height:1.5;margin:0;font-weight:800;letter-spacing:-.01em}
.vyt{grid-area:btn;align-self:end;justify-self:start;border:1px solid var(--line);color:var(--sub);font-weight:600;font-size:.76rem;padding:3px 10px;border-radius:99px;text-decoration:none;white-space:nowrap}
.vyt:hover{border-color:var(--accent);color:var(--accent)}
.vpage .digest p{font-size:1.08rem;line-height:1.65}
.vpage{padding-top:20px}
@media(max-width:640px){.vpage{padding-top:16px}
 .vtop{grid-template-columns:62% minmax(0,1fr);grid-template-rows:auto auto auto;grid-template-areas:"meta meta" "title title" "hero btn";gap:6px 10px;margin-top:0}
 .vhero{margin-top:6px}.brief .vh1{font-size:1.02rem}.vpage .digest p{font-size:1.02rem}
 .vyt{font-size:.7rem;padding:2px 8px}.vyl{display:none}}
.vpage .digest .md{color:#fff;font-size:.72rem;font-weight:700;padding:0 8px;border-radius:99px;line-height:1.7}
.vpage .bsec h3.bt{margin:22px 0 6px}
.vrow{display:flex;gap:12px;align-items:baseline;margin:0;padding:9px 0;border-top:1px solid var(--line);line-height:1.65}
.vrow>span:not(.rt){flex:1;min-width:0}
.vrow .rt{flex:none}
.vrow .tm{text-decoration:none}
/* 모바일: 시간 버튼이 칸을 차지하지 않고 글 끝에 붙는다(자리가 없으면 다음 줄로) */
@media(max-width:600px){.vrow{display:block}.vrow .vsn{display:block;min-width:0;margin-bottom:1px}
 .vrow .rt{display:inline-flex;float:none;margin:0 0 0 6px;vertical-align:1px}}
.vsn{flex:none;min-width:88px}.vsn a{color:inherit}
.vlab{color:var(--sub);font-size:.78rem}
.vnote{color:var(--sub);font-size:.8rem;margin:6px 0 0}
.vtags{display:flex;flex-wrap:wrap;gap:6px;margin:20px 0 4px}
.vkw{background:var(--chip);color:var(--sub);border-radius:99px;padding:3px 11px;font-size:.84rem;text-decoration:none}
.vkw:hover{color:var(--accent)}
.strend{display:flex;align-items:flex-end;gap:4px;height:64px;padding:4px 0}
.strend span{flex:1;background:var(--accent);border-radius:4px 4px 0 0;opacity:.85}
.strend span.z{background:var(--line);opacity:1}
.strl{display:flex;justify-content:space-between;color:var(--sub);font-size:.74rem}
.sgd{margin:14px 0 2px;font-size:.8rem;font-weight:700;color:var(--sub)}
.slist .more{display:none}.slist.open .more{display:block}
.smore{margin:12px 0 0;border:1px solid var(--line);background:var(--card);color:var(--sub);border-radius:99px;padding:6px 14px;font:inherit;font-size:.84rem;cursor:pointer}
.smore:hover{color:var(--accent)}
.infodoc h2.bt{margin:26px 0 8px}.infodoc p,.infodoc li{line-height:1.75}
#themes,#agree,#disagree{scroll-margin-top:12px}
.dis .dv .hv{align-self:flex-end}
.tcard.flash{outline:2px solid var(--accent);outline-offset:2px;transition:outline-color .4s}
.blt{min-width:0}
.bli:hover .bld b{color:var(--accent)}
@media(max-width:600px){.bli{gap:12px}.bld{width:62px}.bld b{font-size:1.2rem!important}.bld.wk b{font-size:1rem!important}}
.srow .tm{text-decoration:none}
/* 브리핑 머리: 흰 박스 밖에 페이지 제목처럼 */
.bpre{margin:4px 0 14px}
.bpt{display:flex;flex-wrap:wrap;align-items:baseline;gap:2px 10px}
.bpt b{color:var(--accent);font-weight:800;font-size:1.15rem}
.bpt span{color:var(--sub);font-size:.88rem}
.bpl{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin-top:10px}
.bpl .bdates{margin-left:0;display:flex;gap:6px;flex-wrap:wrap}
.bpl .bdates a.on{background:var(--accent);border-color:var(--accent);color:#fff}
.bpl .bdates a.oth{border-style:dashed}
.bpl .bact{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
.bpl .link{border:1px solid var(--line);background:var(--card);color:var(--sub);border-radius:99px;padding:3px 11px;font-size:.8rem;text-decoration:none;cursor:pointer}
.bpl .link:hover{color:var(--accent);border-color:var(--accent)}
.brief h1.bh1{margin-top:0}
/* 종합한 영상: 홈의 영상 카드와 같은 모양 */
a.card{color:inherit;text-decoration:none}
.brief .bvgrid .card h2{margin:0;font-size:.85rem;line-height:1.45;letter-spacing:0;-webkit-line-clamp:2}
.bvgrid{grid-template-columns:repeat(auto-fill,minmax(min(210px,100%),1fr))}
@media(min-width:601px){.bvgrid .card p{font-size:.95rem;-webkit-line-clamp:3}.brief .bvgrid .card h2{font-size:.85rem}.bvgrid .card .body{gap:6px}}
@media(min-width:601px){.bvgrid .card{border:0;border-radius:0;background:none}.bvgrid .card .thumb{border-radius:10px}.bvgrid .card .body{padding:10px 2px 0}.bvgrid .card:hover p{color:var(--accent)}}
.bpl .bact .link{font:inherit;font-size:.8rem;line-height:1.5}
.bpl .bact .bsh,.bpl .bact .btg{display:inline-flex;align-items:center;gap:5px;font-weight:700;color:#fff;padding:5px 13px}
.bpl .bact .bsh{background:var(--accent);border-color:var(--accent)}
.bpl .bact .btg{background:#229ed9;border-color:#229ed9}
.bpl .bact .bsh:hover,.bpl .bact .btg:hover{color:#fff;filter:brightness(1.08)}
@media(max-width:600px){.bpl .bact{margin-left:0}.bpt b{font-size:1.05rem}
 .tcard{display:block}.tcard>p{margin-bottom:6px}.tcard>.rel{display:block;margin:0 0 0 auto}}
/* 종목 탭: 숫자·지표 탭과 같은 모양 */
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.sother a{padding:12px 16px}
@media(max-width:600px){.logo{font-size:1.55rem}.nav a{padding:10px 12px}.brief h1{font-size:1.22rem}}
"""

SHARE_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 12v7a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-7"/><path d="M12 3v12"/><path d="M7 8l5-5 5 5"/></svg>'
TG_ICON = '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M21.5 3.6 2.9 10.8c-1.3.5-1.3 1.2-.2 1.5l4.8 1.5 1.8 5.6c.2.6.4.8.9.8.4 0 .6-.2.9-.5l2.3-2.2 4.7 3.5c.9.5 1.5.2 1.7-.8l3.1-14.7c.3-1.3-.5-1.9-1.4-1.5ZM9.6 14l8.7-5.5c.4-.3.8-.1.5.2l-7.4 6.7-.3 3.1L9.6 14Z"/></svg>'

POP_JS = """<script>
// 공유하기: 폰에서는 카톡·스레드 등으로 보내는 창, 안 되면 링크 복사
document.addEventListener("click",async ev=>{const b=ev.target.closest&&ev.target.closest("[data-share]");if(!b)return;
const u=location.href.split("#")[0],d={title:document.title,url:u};
try{if(navigator.share){await navigator.share(d);return}}catch(x){if(x&&x.name==="AbortError")return}
let ok=false;try{await navigator.clipboard.writeText(u);ok=true}catch(x){}
let t=document.getElementById("shtoast");if(!t){t=document.createElement("div");t.id="shtoast";document.body.appendChild(t)}
t.textContent=ok?"링크를 복사했다. 붙여넣어 공유하면 된다.":u;t.className="on";clearTimeout(t._h);t._h=setTimeout(()=>t.className="",ok?2200:6000)});
(()=>{const m=/^#theme-([0-9]+)$/.exec(location.hash);if(!m)return;const go=()=>{const s=document.getElementById("themes"),c=document.getElementById("theme-"+m[1]);
if(s)s.scrollIntoView({block:"start"});if(c){c.classList.add("flash");setTimeout(()=>c.classList.remove("flash"),2600)}};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",()=>setTimeout(go,0));else setTimeout(go,0)})();
</script><script>
(()=>{const pop=document.createElement("div");pop.className="pop";pop.hidden=true;document.body.appendChild(pop);let cur=null;
function show(el,html,wide){pop.innerHTML=html;pop.hidden=false;pop.scrollTop=0;const r=el.getBoundingClientRect(),w=Math.min(wide?600:480,innerWidth-24);
pop.style.width=w+"px";pop.style.left=(scrollX+Math.min(Math.max(12,r.left),innerWidth-w-12))+"px";const h=pop.offsetHeight||0;let top=r.bottom+8;
if(h&&top+h>innerHeight&&r.top-8-h>12)top=r.top-8-h;pop.style.top=(scrollY+top)+"px";cur=el}
function hide(){pop.hidden=true;cur=null}
document.addEventListener("click",e=>{const t=e.target;const p=t.closest&&t.closest(".rel,.hv");
 if(p){const tp=document.getElementById(p.dataset.t);if(!tp)return;if(cur===p&&!pop.hidden)hide();else show(p,tp.innerHTML,p.classList.contains("rel"));return}
 const x=t.closest&&t.closest("[data-exp]");if(x){x.classList.toggle("open");return}
 if(!(t.closest&&t.closest(".pop")))hide()});
addEventListener("resize",hide)})();
</script>"""


def page(path, title, desc, body, kind="article", date=None, nav_on="home", tab_title=None, image=None, extra_ld=None):
    canon = url(path)
    ld = ""
    if kind == "article":
        data = {"@context": "https://schema.org", "@type": "Article", "headline": title[:110], "description": desc,
                "url": canon, "inLanguage": "ko", "publisher": {"@type": "Organization", "name": SITE_NAME}}
        if date:
            data["datePublished"] = date
        if image:
            data["image"] = image
        ld = '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    if extra_ld:
        ld += '<script type="application/ld+json">' + json.dumps(extra_ld, ensure_ascii=False).replace("</", "<\\/") + "</script>"
    tabs = [("home", "홈", ""), ("brief", "브리핑", "brief/"), ("videos", "영상 요약", "#videos"), ("stocks", "종목", "stock/"),
            ("numbers", "숫자·지표", "#numbers"), ("community", "커뮤니티", "#community")]
    nav = "".join(f'<a href="{BASE}{h}" class="{"on" if k == nav_on else ""}">{t}</a>' for k, t, h in tabs)
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
{(f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA_ID}"></script><script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments)}}gtag("js",new Date());gtag("config","{GA_ID}");</script>' if GA_ID else "")}
<title>{e(tab_title or (title + " | " + SITE_NAME))}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canon)}">
<meta property="og:type" content="{'article' if kind == 'article' else 'website'}"><meta property="og:site_name" content="{e(SITE_NAME)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(canon)}">
<meta property="og:image" content="{e(image or url("og.png"))}"><link rel="alternate" type="application/rss+xml" title="{e(SITE_NAME)}" href="{e(url("rss.xml"))}"><meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png"><link rel="apple-touch-icon" href="/apple-touch-icon.png">
<style>{main_css()}{EXTRA_CSS}</style>{ld}</head>
<body><div class="wrap">
<div class="logo brand"><a href="{BASE}"><img src="{BASE}logo.svg" alt="" width="54" height="43">{e(SITE_NAME)}</a><small>{e(TAGLINE)}</small></div>
<nav class="nav">{nav}</nav>
{body}

<p class="note">AI가 경제 유튜브 영상과 그 요약을 종합한 내용이라 오류가 있을 수 있다. 투자 권유가 아니며, 정확한 내용은 원본 영상에서 확인해야 한다. 영상과 썸네일의 저작권은 각 채널에 있다.</p>
<footer class="sitefoot"><a href="https://t.me/marketraven" target="_blank" rel="noopener">텔레그램으로 브리핑 받기</a><a href="{BASE}about/">사이트 소개</a><a href="{BASE}privacy/">개인정보처리방침</a><a href="mailto:{e(CONTACT)}">문의 {e(CONTACT)}</a></footer>
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
VBYID = {}  # 영상 ID -> 영상 (build에서 채운다)


def who(ref, channel):
    """엇갈린 시각에 붙는 이름: 채널 · 출연자 (같은 채널 다른 출연자를 구분하려고)"""
    v = VBYID.get(ref or "") or {}
    ch = channel or v.get("channel") or ""
    ppl = [x.strip() for x in str(v.get("people") or "").replace("·", ",").split(",") if x.strip()]
    same = not channel or not v.get("channel") or channel.split()[0] == str(v.get("channel")).split()[0]  # 연결된 영상의 채널이 다르면 출연자를 붙이지 않는다
    return ch + (" · " + ", ".join(ppl[:2]) if ppl and same else "")


class Frag:
    def __init__(self, V):
        self.V, self.tpl, self.n = V, {}, 0

    def vcard(self, v):
        vid = vid_of(v.get("url"))
        return (f'<a class="vc" href="{href("v/" + vid + "/")}"><div class="vl"><div class="vth"><img src="https://img.youtube.com/vi/{e(vid)}/hqdefault.jpg" alt="" loading="lazy"></div>'
                f'<b>{e(v.get("channel"))}</b><small>{e((v.get("date") or "").replace("-", "."))}</small></div>'
                f'<div class="vr"><div class="vt">{e(v.get("title"))}</div><p>{e(v.get("conclusion"))}</p></div></a>')

    def card(self, v):
        """홈·영상 요약 탭과 같은 영상 카드 (키워드와 '상세 요약'은 뺀 작은 판)."""
        vid = vid_of(v.get("url"))
        md = MOOD_LABEL.get(v.get("mood"))
        return (f'<a class="card" href="{href("v/" + vid + "/")}"><div class="thumb"><img src="https://img.youtube.com/vi/{e(vid)}/hqdefault.jpg" alt="" loading="lazy"></div>'
                f'<div class="body"><div class="meta"><b>{e(v.get("channel"))}</b><span>{e((v.get("date") or "").replace("-", "."))}</span>'
                + (f'<span class="md m{e(v.get("mood"))}">{md}</span>' if md else "")
                + f'</div><h2>{e(v.get("title"))}</h2><p>{e(v.get("conclusion"))}</p></div></a>')

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


def sect(title, n, body, c, sid=""):
    return (f'<div class="bsec"{f" id={chr(34)}{sid}{chr(34)}" if sid else ""}><h3 class="bt {c}">{title}{f'<span class="cn">{n}</span>' if n != "" else ""}</h3>{body}</div>') if body else ""


def note_box(notes, key):
    n = (notes or {}).get(key)
    return f'<p class="enote"><b>편집자 한마디</b>{e(n)}</p>' if n else ""


def kp_list(items):
    return f'<ul class="kp">{"".join(f"<li>{e(k)}</li>" for k in items or [])}</ul>' if items else ""


# ---------- 홈 대시보드 ----------
CLEAR_NUM = ("지수", "금리", "환율", "국채", "유가", "WTI", "브렌트", "금 가격", "금값", "은 가격", "구리", "달러", "엔화", "위안",
             "CPI", "PCE", "PPI", "물가", "실업", "고용", "GDP", "성장률", "신용잔고", "예탁금", "지급준비금", "비트코인", "VIX",
             "수출", "PMI", "M2", "외국인 순매도", "외국인 순매수", "순매수", "순매도", "시가총액")


def num_key(v):
    t = re.sub(r"[\s,]", "", v or "")
    return re.sub(r"(\d)\.0(?=\D|$)", r"\1", t)


# ---------- 브리핑 공유 이미지 (카톡·검색 미리보기용, 1200x630) ----------
def og_image(name, kicker, headline, foot):
    """og/<name>.png 를 만들고 사이트 주소를 돌려준다. 글꼴이나 Pillow가 없으면 None (공통 이미지를 쓴다)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    font, logo = ROOT / "scripts" / "og-font.otf", ROOT / "scripts" / "og-logo.png"
    if not font.exists():
        return None
    out = ROOT / "og" / f"{name}.png"
    out.parent.mkdir(exist_ok=True)
    F = lambda s: ImageFont.truetype(str(font), s)
    im = Image.new("RGB", (1200, 630), "white")
    dr = ImageDraw.Draw(im)
    x0 = 64
    if logo.exists():
        lg = Image.open(logo).convert("RGBA")
        lg = lg.resize((int(lg.width * 70 / lg.height), 70))
        im.paste(lg, (x0, 46), lg)
        dr.text((x0 + lg.width + 16, 56), "Market Raven", font=F(40), fill="#14181f")
    dr.text((x0, 176), kicker, font=F(40), fill="#e5383b")

    def wrap(text, f, width):
        lines, cur = [], ""
        for w in (text or "").split(" "):
            t_ = (cur + " " + w).strip()
            if dr.textlength(t_, font=f) <= width:
                cur = t_
                continue
            if cur:
                lines.append(cur)
            cur = ""
            for ch in w:  # 한 단어가 너무 길면 글자 단위로 자른다
                if dr.textlength(cur + ch, font=f) > width:
                    lines.append(cur)
                    cur = ""
                cur += ch
        if cur:
            lines.append(cur)
        return lines
    for size in (68, 60, 52):
        f = F(size)
        lines = wrap(headline, f, 1200 - x0 * 2)
        if len(lines) <= 3:
            break
    lines = lines[:3]
    y = 250
    for ln in lines:
        dr.text((x0, y), ln, font=f, fill="#14181f")
        y += int(size * 1.32)
    dr.text((x0, 532), foot, font=F(30), fill="#5d6573")
    site = SITE.split("//")[-1]
    dr.text((1200 - x0 - dr.textlength(site, font=F(30)), 532), site, font=F(30), fill="#5d6573")
    dr.rectangle([0, 612, 1200, 630], fill="#e5383b")
    im.save(out, optimize=True)
    return url(f"og/{name}.png")


# ---------- RSS (네이버 서치어드바이저 등록용) ----------
def write_rss(man):
    from email.utils import format_datetime

    def when(s):
        try:
            return format_datetime(datetime.datetime.fromisoformat(s[:16] if "T" in s else s + "T09:00").replace(tzinfo=KST))
        except Exception:
            return ""
    items = []
    for d, m in man["brief"].items():
        items.append((d + "T23:00", f"{sdate(d)} 시장 브리핑: {m.get('headline') or ''}", url(f"brief/{d}/"), m.get("desc") or ""))
    for w, m in man["week"].items():
        items.append(((m.get("end") or w) + "T23:30", f"{sdate(w)}~{sdate(m.get('end'))} 주간 시장 브리핑: {m.get('headline') or ''}", url(f"week/{w}/"), m.get("desc") or ""))
    for k, m in man["video"].items():
        items.append((m.get("ts") or (m.get("date") or "") + "T12:00", f"{short_title(m.get('title'))} 요약" + (f" | {m.get('ch')}" if m.get("ch") else ""), url(f"v/{k}/"), m.get("desc") or ""))
    items.sort(key=lambda x: x[0], reverse=True)
    body = "".join(f"<item><title>{e(tt)}</title><link>{e(ln)}</link><guid isPermaLink=\"true\">{e(ln)}</guid><description>{e(ds)}</description><pubDate>{when(ts)}</pubDate></item>\n"
                   for ts, tt, ln, ds in items[:60])
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>\n'
           f"<title>{e(SITE_NAME)}</title><link>{e(url(''))}</link><description>{e(TAGLINE)}. 경제 유튜브 영상 요약과 매일 시장 브리핑.</description><language>ko</language>"
           f'<atom:link href="{e(url("rss.xml"))}" rel="self" type="application/rss+xml"/>\n' + body + "</channel></rss>\n")
    (ROOT / "rss.xml").write_text(xml, encoding="utf-8")


def build_dash(recent, briefs, weekly, digests, man):
    now = datetime.datetime.now(KST)
    since = (now - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M")
    yday = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    # 최근 24시간 영상 (올라온 시각이 없는 예전 데이터는 날짜로 대신 판단)
    day = [v for v in recent if (v.get("ts") or "") >= since or (not v.get("ts") and (v.get("date") or "") >= yday)]
    if len(day) < 3:  # 너무 적으면 최근 영상 10편으로 채운다
        day = recent[:10]
    b = max(briefs, key=lambda x: x["date"]) if briefs else None
    blocks = []

    def hd(title, color, meta="", more=""):
        return (f'<div class="dhd"><h2 class="bt {color}">{title}</h2>' + (f'<span class="dmeta">{meta}</span>' if meta else "")
                + (f'<a class="dmore" href="{more[0]}">{more[1]} →</a>' if more else "") + "</div>")

    # 1) 지금 시장은
    if b:
        bl = href("brief/" + b["date"] + "/")
        themes = "".join(f'<a class="dth" href="{bl}#theme-{n + 1}">{e(t["title"])}</a>' for n, t in enumerate((b.get("themes") or [])[:3]))
        wk_line = ""
        if weekly:
            w = max(weekly, key=lambda x: x["week"])
            this_mon = (now.date() - datetime.timedelta(days=now.weekday())).isoformat()
            lab = "이번 주 흐름" if w["week"] == this_mon else "지난주 흐름"
            wk_line = (f'<div class="dfoot"><div class="dwk"><b>{lab}</b><span>{e(w.get("headline"))}</span></div>'
                       f'<a class="dmore" href="{href("week/" + w["week"] + "/")}">주간 브리핑 보기 →</a></div>')
        blocks.append(
            f'<section class="dblk dmkt">' + hd("지금 시장은", "c1", f'{e(kdate(b["date"]))} 기준 · 영상 {e(b.get("count"))}편 종합 · {now:%H:%M} 갱신', (bl, "브리핑 전문 보기"))
            + f'<p class="dhl">{e(b.get("headline"))}</p>{kp_list(b.get("keypoints"))}'
            + (f'<div class="dths"><small>핵심 주제</small>{themes}</div>' if themes else "")
            + wk_line + "</section>")

    # 2) 채널들의 시장 판단: 영상 단위 분위기(어제와 비교) + 주요 쟁점 1개
    parts = []
    prev_since = (now - datetime.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M")
    yday2 = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    prev = [v for v in recent if v not in day and ((v.get("ts") or "") >= prev_since or (not v.get("ts") and yday2 <= (v.get("date") or "") < yday))]

    def moods(vs):
        c = {"낙관": 0, "중립": 0, "비관": 0}
        for v in vs:
            if v.get("mood") in c:
                c[v["mood"]] += 1
        return c

    ML = {"낙관": "긍정", "중립": "중립·관망", "비관": "부정"}  # 데이터 이름 -> 화면에 보이는 이름
    mc, pc = moods(day), moods(prev)
    tot, ptot = sum(mc.values()), sum(pc.values())
    if tot >= 5:
        segs = "".join(f'<a class="mseg m{k}" style="flex:{n}" href="{BASE}#videos/mood/{quote(k)}" title="{ML[k]} {n}편"><b>{ML[k]}</b><span>{n}</span></a>'
                       for k, n in mc.items() if n)
        trend = ""
        if ptot >= 5:
            score = (mc["낙관"] - mc["비관"]) / tot
            pscore = (pc["낙관"] - pc["비관"]) / ptot
            d = score - pscore
            trend = ("어제보다 긍정 쪽으로 기울었다" if d >= 0.15 else "어제보다 부정 쪽으로 기울었다" if d <= -0.15 else "어제와 비슷한 분위기다")
            arrow = "▲" if d >= 0.15 else "▼" if d <= -0.15 else "―"
            trend = f'<p class="mtrend"><span class="ma">{arrow}</span>{trend} <small>어제 긍정 {pc["낙관"]} · 중립 {pc["중립"]} · 부정 {pc["비관"]}</small></p>'
        parts.append(f'<div class="dj"><h3>최근 24시간 영상 {tot}편의 분위기 <small>막대를 누르면 해당 영상만 본다</small></h3><div class="mbar">{segs}</div>{trend}</div>')
    if b and b.get("disagreements"):
        d = b["disagreements"][0]
        boxes = '<span class="vs">vs</span>'.join(
            f'<div class="dv"><span>{e(w.get("view"))}</span><a class="dvc" href="{BASE}#v/{e(w.get("ref"))}">{e(who(w.get("ref"), w.get("channel")))}</a></div>'
            for w in (d.get("views") or [])[:2])
        parts.append(f'<div class="dj"><h3>주요 쟁점</h3><div class="dis"><b class="dq">{e(d["topic"])}</b><div class="dvs">{boxes}</div></div></div>')
    if parts:
        more = (href("brief/" + b["date"] + "/") + ("#agree" if b.get("agreements") else "#disagree"), "채널 의견 전체 보기") if b else ""
        blocks.append('<section class="dblk">' + hd("채널들의 시장 판단", "c3", "유튜브는 지금 시장을 이렇게 본다", more) + "".join(parts) + "</section>")

    # 3) 많이 언급된 종목 TOP6
    tb = {}
    for v in day:
        seen = set()
        for row in v.get("stocks") or []:
            if len(row) < 2 or not norm(row[1]) or norm(row[1]) in seen:
                continue
            seen.add(norm(row[1]))
            t = tb.setdefault(norm(row[1]), {"name": canon_stock(row[1]), "n": 0, "ch": set(), "notes": []})
            t["n"] += 1
            t["ch"].add(v.get("channel"))
            if len(row) > 2 and row[2]:
                t["notes"].append(row[2])
    dig = {}
    for d in digests.values():
        k = norm(d.get("name"))
        if k not in dig or (d.get("updated") or "") > (dig[k].get("updated") or ""):
            dig[k] = d
    tone_of = {k: d.get("tone") for k, d in dig.items()}
    for bb in sorted(briefs, key=lambda x: x["date"]):  # 최근 브리핑의 그날 평가가 있으면 그걸 쓴다
        for x in bb.get("stocks") or []:
            if x.get("tone"):
                tone_of[norm(x["name"])] = x["tone"]

    def first_sentence(t):
        t = (t or "").strip()
        m = re.match(r"(.+?[다요]\.)(\s|$)", t)
        return m.group(1) if m else t

    top = sorted(tb.items(), key=lambda kv: (-kv[1]["n"], -len(kv[1]["ch"]), kv[1]["name"]))[:6]
    if top:
        cells = ""
        for k, t in top:
            tone = tone_of.get(k)
            s_ = slug(t["name"])
            link = href("stock/" + quote(s_) + "/") if s_ in man["stock"] else href("stock/?q=" + quote(t["name"]))
            line = first_sentence(dig[k].get("summary")) if k in dig else (t["notes"][0] if t["notes"] else "")
            cells += (f'<a class="dstk" href="{link}"><span class="dsn"><b>{e(t["name"])}</b>'
                      + (f'<span class="tone t{e(tone)}">{e(tone)}</span>' if tone else "")
                      + f'</span><small>영상 {t["n"]}편 · {len(t["ch"])}채널</small>'
                      + (f'<p>{e(line)}</p>' if line else "") + "</a>")
        blocks.append('<section class="dblk">' + hd("많이 언급된 종목", "c4", f"최근 24시간 · 영상 {len(day)}편 기준", (href("stock/"), "종목 페이지로"))
                      + f'<div class="dgrid">{cells}</div></section>')

    # 4) 숫자로 본 시장: 지표 이름이 분명한 것만
    nb = {}
    for v in day:
        for n in v.get("numbers") or []:
            if len(n) < 4:
                continue
            label = (n[3] or "").strip()
            if not label or label == "기타" or not any(c in label for c in CLEAR_NUM) or "불명확" in n[1]:
                continue
            g = nb.setdefault(label, {"vals": {}, "n": 0})
            g["n"] += 1
            g["vals"].setdefault(num_key(n[1]), []).append((n, v))
    groups = sorted(nb.items(), key=lambda kv: -kv[1]["n"])
    keep = 6 if len(groups) >= 6 else (3 if len(groups) >= 3 else 0)
    if keep:
        cards = ""
        for label, g in groups[:keep]:
            vk, lst = max(g["vals"].items(), key=lambda kv: len(kv[1]))
            n, v = lst[0]
            vid = vid_of(v.get("url"))
            cards += (f'<a class="dnum" href="{BASE}#numbers/{quote(label)}"><small class="dnl"><span>{e(label)}</span>'
                      + (f'<span class="cnt">{g["n"]}번 언급</span>' if g["n"] > 1 else "") + f'</small><b>{e(n[1])}</b><p>{e(n[2])}</p></a>')
        blocks.append('<section class="dblk">' + hd("숫자로 본 시장", "c2", "최근 24시간 · 영상에서 언급된 수치 · 실시간 시세 아님", (BASE + "#numbers", "숫자·지표로"))
                      + f'<div class="dgrid">{cards}</div></section>')

    # 5) 최신 영상: 카드 모양은 영상 요약 탭과 같다 (화면에서 채운다)
    # 화면에서 다시 그리지만, 자바스크립트를 못 읽는 검색엔진도 영상 페이지 링크를 따라가게 미리 채워 둔다
    def hcard(i, v):
        vid = vid_of(v.get("url"))
        md = MOOD_LABEL.get(v.get("mood"))
        tit = f'<a class="clink" href="{href("v/" + vid + "/")}">{e(v.get("title"))}</a>' if vid else e(v.get("title"))
        return (f'<article class="card" data-i="{i}"><div class="thumb">' + (f'<img src="https://img.youtube.com/vi/{e(vid)}/hqdefault.jpg" alt="" loading="lazy">' if vid else "")
                + f'</div><div class="body"><div class="meta"><b>{e(v.get("channel"))}</b><span>{e((v.get("date") or "").replace("-", "."))}</span>'
                + (f'<span class="md m{e(v.get("mood"))}">{md}</span>' if md else "")
                + f'</div><h2>{tit}</h2><p>{e(v.get("conclusion"))}</p></div></article>')
    blocks.append('<section class="dblk dlatest">' + hd("최근 영상", "", "", (BASE + "#videos", "영상 요약 전체 보기"))
                  + '<div class="grid" id="hgrid">' + "".join(hcard(i, v) for i, v in enumerate(recent[:6])) + '</div></section>')

    blocks.append('<p class="bnote">AI가 경제 유튜브 영상들을 요약·종합한 내용이며 투자 권유가 아니다.</p>')
    html_ = "<!--DASH:START-->\n" + "\n".join(blocks) + "\n<!--DASH:END-->"
    p = ROOT / "index.html"
    try:
        t = p.read_text(encoding="utf-8")
    except Exception:
        return 0
    if "<!--DASH:START-->" not in t:
        print("index.html에 대시보드 자리(<!--DASH:START-->)가 없어서 홈을 만들지 않았다.")
        return 0
    t2 = re.sub(r"<!--DASH:START-->.*?<!--DASH:END-->", lambda m: html_, t, flags=re.S)
    if t2 == t:
        return 0
    p.write_text(t2, encoding="utf-8")
    return 1


# ---------- 사이트 소개, 개인정보처리방침 ----------
INFO_DATE = "2026-11-20"


def build_info_pages():
    try:
        chans = [c.get("name") for c in json.loads((ROOT / "channels.json").read_text(encoding="utf-8")) if c.get("name")]
    except Exception:
        chans = []
    ch_list = "".join(f"<li>{e(c)}</li>" for c in chans) or "<li>채널 목록을 불러오지 못했다.</li>"
    mail = f'<a href="mailto:{e(CONTACT)}">{e(CONTACT)}</a>'

    def doc(title, sections):
        return ('<div class="brief infodoc"><h1 style="margin-top:0">' + e(title) + "</h1>"
                + "".join(f'<h2 class="bt c1">{h}</h2>{b}' for h, b in sections) + "</div>")

    about = doc("사이트 소개", [
        ("어떤 곳인가", f"<p>{e(SITE_NAME)}은 인기 경제 유튜브 채널의 영상을 AI가 요약하고, 여러 채널의 이야기를 하루와 한 주 단위로 종합해 보여 주는 곳이다. "
                    "영상을 다 볼 시간이 없을 때, 오늘 경제 유튜브에서 무슨 이야기가 오갔는지 몇 분 안에 파악할 수 있게 만드는 게 목표다.</p>"),
        ("다루는 채널", f"<ul class=\"kp\">{ch_list}</ul><p>채널은 앞으로 늘어날 수 있다.</p>"),
        ("볼 수 있는 것", "<ul class=\"kp\"><li><b>홈</b>: 지금 시장 요약, 채널들의 분위기와 쟁점, 많이 언급된 종목과 숫자를 한눈에 본다.</li>"
                     "<li><b>브리핑</b>: 하루와 한 주의 영상을 종합한 시장 브리핑이다.</li>"
                     "<li><b>영상 요약</b>: 영상마다 한 줄 결론, 장면별 핵심 내용, 언급된 종목과 숫자를 정리하고, 해당 장면으로 바로 가는 시간 링크를 단다.</li>"
                     "<li><b>종목</b>: 여러 영상에서 언급된 종목을 모아 채널들의 시각을 비교한다.</li>"
                     "<li><b>숫자·지표</b>: 영상에서 언급된 지표와 수치를 모아 본다.</li></ul>"),
        ("어떻게 만드나", "<p>2시간마다 자동으로 새 영상을 찾아 Google의 AI(Gemini)로 요약한다. 경제·투자와 관련 없는 영상은 제외한다. "
                     "브리핑과 종목 정리도 같은 방식으로 자동으로 만들고, 필요할 때 운영자가 한마디를 덧붙인다.</p>"),
        ("꼭 알아 둘 점", "<ul class=\"kp\"><li>AI가 만든 요약이라 내용이 틀리거나 빠질 수 있다. 중요한 내용은 원본 영상에서 확인해야 한다.</li>"
                      "<li>이 사이트의 내용은 투자 권유가 아니다. 숫자는 영상 속 출연자가 말한 것이며 실시간 시세가 아니다.</li>"
                      "<li>영상과 썸네일의 저작권은 각 채널에 있다. 모든 요약에는 원본 영상 링크를 단다.</li></ul>"),
        ("문의", f"<p>잘못된 요약, 삭제 요청, 제안은 {mail}로 보내 주면 확인한다.</p>"),
    ])
    privacy = doc("개인정보처리방침", [
        ("1. 수집하는 개인정보", "<p>이 사이트는 회원가입이나 로그인 기능이 없고, 방문자의 이름·연락처 같은 개인정보를 직접 수집하지 않는다.</p>"),
        ("2. 자동으로 기록될 수 있는 정보", "<p>사이트는 GitHub Pages에서 운영된다. GitHub는 보안과 서비스 운영을 위해 방문자의 IP 주소 등 접속 기록을 남길 수 있으며, "
                                   "이는 GitHub의 개인정보 정책을 따른다. 운영자는 이 기록을 따로 받거나 보관하지 않는다.</p>"),
        ("3. 외부에서 불러오는 콘텐츠", "<p>영상 썸네일은 YouTube(Google) 서버에서, 글꼴은 jsDelivr에서 불러온다. 영상 요약 페이지에는 YouTube 플레이어가 들어 있어, 페이지를 열거나 영상을 재생하면 YouTube가 쿠키를 쓰고 접속 정보를 받을 수 있다. "
                                 "이 부분에는 YouTube(Google)의 개인정보 정책이 적용된다.</p>"),
        ("4. 쿠키와 브라우저 저장 공간", "<p>방문 통계를 위해 Google 애널리틱스 쿠키를 쓴다(5번 참고). 그 밖에 화면 설정 같은 편의 기능을 위해 브라우저 저장 공간을 쓸 수 있으나, 그 내용은 방문자의 브라우저에만 남고 운영자에게 전송되지 않는다. 쿠키는 브라우저 설정에서 거부하거나 지울 수 있다.</p>"),
        ("5. 방문 통계와 광고", "<p>이 사이트는 방문자 수와 많이 본 페이지를 파악하기 위해 Google 애널리틱스를 쓴다. Google 애널리틱스는 쿠키로 방문한 페이지, 머문 시간, 대략적인 지역, 기기와 브라우저 종류 같은 정보를 모으며, "
                             "운영자는 개인을 알아볼 수 없는 통계 형태로만 본다. 수집된 정보는 Google의 정책에 따라 처리된다. 수집을 원하지 않으면 "
                             '<a href="https://tools.google.com/dlpage/gaoptout" target="_blank" rel="noopener">Google 애널리틱스 차단 브라우저 부가기능</a>을 쓰거나 쿠키를 거부하면 된다.</p>'
                             "<p>앞으로 Google 애드센스(광고)를 도입할 수 있다. 도입하면 Google을 비롯한 제3자 공급업체가 쿠키를 사용해 방문자의 이 사이트 및 다른 사이트 방문 기록을 바탕으로 광고를 게재할 수 있다. 맞춤 광고는 "
                             '<a href="https://adssettings.google.com" target="_blank" rel="noopener">Google 광고 설정</a>에서 끌 수 있다. 도입할 때 이 문서를 고친다.</p>'),
        ("6. 문의", f"<p>개인정보와 관련한 문의는 {mail}로 보내 주면 된다.</p>"),
        ("7. 시행일", f"<p>이 방침은 {e(kdate(INFO_DATE))}부터 적용한다. 내용이 바뀌면 이 페이지에 알린다.</p>"),
    ])
    n = write("about", page("about/", "사이트 소개", f"{SITE_NAME}은 인기 경제 유튜브 채널의 영상을 AI가 요약하고 하루와 한 주 단위로 종합해 보여 주는 곳이다.", about, kind="list", nav_on=""))
    n += write("privacy", page("privacy/", "개인정보처리방침", f"{SITE_NAME}의 개인정보처리방침이다.", privacy, kind="list", nav_on=""))
    return n


# ---------- 영상별 개별 페이지 ----------
MOOD_LABEL = {"낙관": "긍정", "중립": "중립", "비관": "부정"}


def related_videos(v, pool, n=4):
    """같은 종목(가장 중요), 같은 키워드, 같은 날 다른 채널을 기준으로 이어서 볼 영상을 고른다."""
    me = vid_of(v.get("url"))
    stocks = {norm(r[1]) for r in v.get("stocks") or [] if len(r) > 1 and norm(r[1])}
    tags = set(v.get("tags") or [])
    d0 = v.get("date") or ""
    try:
        day0 = datetime.date.fromisoformat(d0)
    except Exception:
        day0 = None
    scored = []
    for k, w in pool.items():
        if k == me:
            continue
        sc = 3 * len(stocks & {norm(r[1]) for r in w.get("stocks") or [] if len(r) > 1}) + len(tags & set(w.get("tags") or []))
        if w.get("date") == d0 and w.get("channel") != v.get("channel"):
            sc += 1
        if sc <= 0:
            continue
        try:
            gap = abs((datetime.date.fromisoformat(w.get("date")) - day0).days) if day0 else 30
        except Exception:
            gap = 30
        if gap > 14:
            continue
        scored.append((sc - gap * 0.15, w.get("date") or "", w))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [w for _, _, w in scored[:n]]


def build_video_pages(V, man, briefs, stock_slug, mark):
    brief_dates = {b["date"] for b in briefs} | set(man["brief"])
    changed = 0
    for vid, v in V.items():
        F = Frag(V)
        yt = f"https://www.youtube.com/watch?v={vid}"

        def tlink(t):
            return f'<a class="tm" href="{yt}&t={secs(t)}s" data-s="{secs(t)}" target="_blank" rel="noopener">▶ {e(t)}</a>' if t else ""

        mood = MOOD_LABEL.get(v.get("mood"))
        parts = "".join(
            f'<h3 class="bt c1">{e(p_.get("t"))}</h3>'
            + "".join(f'<p class="vrow"><span>{e(x)}</span><span class="rt">{tlink(t)}</span></p>' for t, x in p_.get("items") or [])
            for p_ in v.get("parts") or [])
        stocks = "".join(
            f'<p class="vrow"><b class="vsn">'
            + (f'<a href="{href("stock/" + quote(stock_slug[norm(r[1])]) + "/")}">{e(r[1])}</a>' if norm(r[1]) in stock_slug else e(r[1]))
            + f'</b><span>{e(r[2] if len(r) > 2 else "")}</span><span class="rt">{tlink(r[0])}</span></p>'
            for r in v.get("stocks") or [] if len(r) > 1)
        nums = "".join(
            f'<p class="vrow"><b class="vsn">{e(r[1])}</b><span>{e(r[2])}' + (f' <small class="vlab">{e(r[3])}</small>' if len(r) > 3 and r[3] != "기타" else "")
            + f'</span><span class="rt">{tlink(r[0])}</span></p>'
            for r in v.get("numbers") or [] if len(r) > 2)
        tags = "".join(f'<a class="vkw" href="{BASE}#videos/kw/{quote(t)}">#{e(t)}</a>' for t in v.get("tags") or [])
        rel = related_videos(v, V)
        d = v.get("date") or ""
        # 시간 버튼을 누르면 새 창 대신 위쪽 플레이어가 그 시간부터 재생한다 (Ctrl·⌘ 클릭은 새 창)
        seek_js = ('<script>document.addEventListener("click",function(e){var a=e.target.closest&&e.target.closest(".vpage a.tm[data-s]");'
                   'if(!a||e.ctrlKey||e.metaKey||e.shiftKey||e.button)return;var f=document.querySelector(".vhero iframe");if(!f)return;e.preventDefault();'
                   f'f.src="https://www.youtube.com/embed/{vid}?start="+a.dataset.s+"&autoplay=1&rel=0";'
                   'var top=document.querySelector(".vtop");if(top)top.scrollIntoView({behavior:"smooth",block:"start"});});</script>')
        body = (f'<div class="brief vpage">'
                + f'<div class="vtop"><div class="vmeta"><b>{e(v.get("channel"))}</b><span>{e(kdate(d))}</span>'
                + (f'<a href="{href("brief/" + d + "/")}">이날 시장 브리핑 →</a>' if d in brief_dates else "") + '<button class="vshr" data-share type="button">공유</button>' + f'</div><h1 class="vh1">{e(v.get("title"))}</h1>'
                + f'<div class="vhero"><iframe src="https://www.youtube.com/embed/{e(vid)}?rel=0" title="{e(v.get("title"))}" loading="lazy" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe></div>'
                + f'<a class="vyt" href="{yt}" target="_blank" rel="noopener">▶ 유튜브<span class="vyl">에서 원본</span> 보기</a></div>'
                + f'<div class="digest"><div class="dh"><b>한 줄 결론</b>' + (f'<span class="md m{e(v.get("mood"))}">{e(mood)}</span>' if mood else "")
                + (f'<span>출연 {e(v.get("people"))}</span>' if v.get("people") else "") + f'</div><p>{e(v.get("conclusion"))}</p></div>'
                + (f'<div class="bsec">{parts}</div>' if parts else "")
                + sect("언급된 종목", len(v.get("stocks") or []), stocks and f'<div>{stocks}</div>', "c4")
                + sect("언급된 숫자", len(v.get("numbers") or []), nums and f'<div>{nums}</div><p class="vnote">영상 속 출연자가 말한 수치이며 실시간 시세가 아니다.</p>', "c2")
                + (f'<div class="vtags">{tags}</div>' if tags else "")
                + sect("이어서 볼 영상", len(rel), rel and '<div class="vgrid">' + "".join(F.vcard(w) for w in rel) + "</div>", "")
                + "</div>" + F.templates() + seek_js)
        items = [x for p_ in v.get("parts") or [] for _, x in p_.get("items") or []]
        desc = desc_of(v.get("conclusion"), *items[:3])
        title = f'{v.get("title")} 요약 | {v.get("channel")}'
        c = write(f"v/{vid}", page(f"v/{vid}/", title, desc, body, date=d, nav_on="videos", tab_title=short_title(v.get("title")) + " 요약", image=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", extra_ld=video_ld(v, vid)))
        changed += c
        mark("video", vid, c, {"title": (v.get("title") or "")[:80], "date": d, "ts": v.get("ts") or "", "ch": v.get("channel") or "", "desc": desc})
    return changed


# ---------- 페이지 만들기 ----------
def build():
    videos = read_const(ROOT / "videos.js", "VIDEOS", [])
    try:
        videos = videos + json.loads((ROOT / "archive.json").read_text(encoding="utf-8"))
    except Exception:
        pass
    V = {vid_of(v.get("url")): v for v in videos if vid_of(v.get("url"))}
    VBYID.update(V)
    briefs = read_const(ROOT / "briefs.js", "BRIEFS", [])
    weekly = read_const(ROOT / "briefs.js", "WEEKLY", [])
    digests = read_const(ROOT / "stocks.js", "STOCKSUM", {})
    notes = read_const(ROOT / "notes.js", "NOTES", {})
    try:
        man = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        man = {}
    for k in ("brief", "week", "stock", "video"):
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
        # 날짜 칩은 3개: 최신 날이면 앞의 두 날 + 이날, 아니면 전날 + 이날 + 다음 날. 나머지는 '다른 날'(브리핑 모아보기)
        near = all_dates[max(0, i - 2): i + 1] if i == len(all_dates) - 1 else all_dates[max(0, i - 1): i + 2]
        dates = ("".join(f'<a href="{href("brief/" + x + "/")}" class="{"on" if x == d else ""}">{e(sdate(x))}</a>' for x in near)
                 + f'<a class="oth" href="{href("brief/")}">다른 날 ›</a>')
        wk = (datetime.date.fromisoformat(d) - datetime.timedelta(days=datetime.date.fromisoformat(d).weekday())).isoformat()
        wk = wk if wk in week_keys else max((x for x in week_keys if x < wk), default="")  # 이 주 주간 브리핑이 아직 없으면 가장 최근 주간 브리핑
        th = "".join(f'<div class="tcard" id="theme-{n + 1}"><b>{e(t["title"])}</b><p data-exp title="눌러서 펼치기">{e(t["summary"])}</p>{F.rel(t.get("refs"))}</div>' for n, t in enumerate(b.get("themes") or []))
        ag = "".join(f'<div class="mrow"><span>{e(a["point"])}</span>{F.rel(a.get("refs"))}</div>' for a in b.get("agreements") or [])
        dg = "".join(f'<div class="dis"><b class="dq">{e(x["topic"])}</b><div class="dvs">'  # 홈과 같은 모양: 테두리 상자 vs 테두리 상자
                     + '<span class="vs">vs</span>'.join(f'<div class="dv"><span>{e(w["view"])}</span>{F.hv(w.get("ref"), who(w.get("ref"), w.get("channel")))}</div>' for w in x.get("views") or [])
                     + "</div></div>" for x in b.get("disagreements") or [])
        sk = "".join(f'<div class="sk"><div class="skh"><b>{stock_name(s["name"])}</b><small>{s.get("count", "")}편에서 언급</small></div>'
                     + "".join(f'<div class="mrow"><span>{e(m["view"])}</span>{F.hv(m.get("ref"), m.get("channel"))}</div>' for m in (s.get("mentions") or [])[:4])
                     + "</div>" for s in b.get("stocks") or [])
        vids = [V[x] for x in b.get("sources") or [] if x in V]
        body = (f'<div class="bpre"><div class="bpt"><b>시장 브리핑</b><span>{e(kdate(d))} · 영상 {b.get("count", len(vids))}편 종합</span></div>'
                f'<div class="bpl"><span class="bdates">{dates}</span><span class="bact">'
                + (f'<a class="link" href="{href("week/" + wk + "/")}">주간 브리핑 →</a>' if wk else "")
                + f'<button class="link shr bsh" data-share type="button">{SHARE_ICON}공유하기</button>'
                + f'<a class="link btg" href="https://t.me/marketraven" target="_blank" rel="noopener">{TG_ICON}텔레그램으로 받기</a></span></div></div>'
                f'<div class="brief"><h1 class="bh1">{e(b.get("headline"))}</h1>{kp_list(b.get("keypoints"))}{note_box(notes, d)}'
                + sect("핵심 주제", len(b.get("themes") or []), th and f'<div class="tgrid">{th}</div>', "c1", "themes")
                + sect("공통된 시각", len(b.get("agreements") or []), ag, "c2", "agree")
                + sect("엇갈린 시각", len(b.get("disagreements") or []), dg, "c3", "disagree")
                + sect("많이 언급된 종목", len(b.get("stocks") or []), sk and f'<div class="skg">{sk}</div>', "c4")
                + sect("종합한 영상", len(vids), vids and '<div class="grid bvgrid">' + "".join(F.card(v) for v in vids) + "</div>", "")
                + '<p class="bnote">AI가 이날의 영상 요약들을 종합한 내용이며 투자 권유가 아니다. \'관련 영상\'이나 채널 이름을 누르면 근거가 된 영상을 볼 수 있다.</p></div>'
                + F.templates())
        dd_ = datetime.date.fromisoformat(d)
        ogi = og_image(f"brief-{d}", f"{dd_.month}.{dd_.day:02d} ({WD[dd_.weekday()]}) 시장 브리핑", b.get("headline") or "", f"경제 유튜브 영상 {b.get('count') or ''}편 종합")
        bdesc = desc_of(*(b.get("keypoints") or []))
        c = write(f"brief/{d}", page(f"brief/{d}/", f"{sdate(d)} 시장 브리핑: {b.get('headline', '')}", bdesc, body, date=d, nav_on="brief", image=ogi))
        changed += c
        mark("brief", d, c, {"headline": b.get("headline"), "count": b.get("count"), "desc": bdesc})

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
        body = (f'<div class="bpre"><div class="bpt"><b>주간 브리핑</b><span>{e(kdate(ws))} ~ {e(kdate(w.get("end")))} · 영상 {w.get("videos", "")}편 종합</span></div>'
                f'<div class="bpl"><span class="bdates"><a class="oth" href="{href("brief/")}#weekly">다른 주 ›</a></span><span class="bact">'
                f'<button class="link shr bsh" data-share type="button">{SHARE_ICON}공유하기</button>'
                f'<a class="link btg" href="https://t.me/marketraven" target="_blank" rel="noopener">{TG_ICON}텔레그램으로 받기</a></span></div></div>'
                f'<div class="brief"><h1 class="bh1">{e(w.get("headline"))}</h1>{kp_list(w.get("keypoints"))}{note_box(notes, "week:" + ws)}'
                + sect("하루하루의 흐름", len(w.get("flow") or []), fl and f'<dl class="tl">{fl}</dl>', "c1")
                + sect("이번 주 반복된 주제", len(w.get("recurring") or []), rc and f'<div class="tgrid">{rc}</div>', "c2")
                + sect("이번 주 많이 언급된 종목", len(w.get("stocks") or []), sw and f'<div class="skg">{sw}</div>', "c4")
                + '<p class="bnote">AI가 이번 주의 일간 브리핑들을 종합한 내용이며 투자 권유가 아니다.</p></div>')
        a_, z_ = datetime.date.fromisoformat(ws), datetime.date.fromisoformat(w.get("end") or ws)
        ogi = og_image(f"week-{ws}", f"{a_.month}.{a_.day:02d}~{z_.month}.{z_.day:02d} 주간 시장 브리핑", w.get("headline") or "", f"경제 유튜브 영상 {w.get('videos') or ''}편 종합")
        wdesc = desc_of(*(w.get("keypoints") or []))
        c = write(f"week/{ws}", page(f"week/{ws}/", f"{sdate(ws)}~{sdate(w.get('end'))} 주간 시장 브리핑: {w.get('headline', '')}",
                                     wdesc, body, date=w.get("gen_date") or ws, nav_on="brief", image=ogi))
        changed += c
        mark("week", ws, c, {"headline": w.get("headline"), "end": w.get("end"), "videos": w.get("videos"), "desc": wdesc})

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
        # 날짜별로 묶고, 처음 6개만 보이게 (나머지는 '더 보기')
        rows, cur, shown_n = "", None, 0
        for v, row in ms[:40]:
            dd = v.get("date") or ""
            if dd != cur:
                cnt = sum(1 for w, _ in ms[:40] if w.get("date") == dd)
                rows += f'<div class="sgd{" more" if shown_n >= 6 else ""}">{e(kdate(dd))} · {cnt}편</div>'
                cur = dd
            rows += (f'<p class="srow{" more" if shown_n >= 6 else ""}"><span>{e(row[2])}</span><span class="rt">{F.hv(vid_of(v.get("url")))}{tm(v, row[0])}</span></p>')
            shown_n += 1
        if shown_n > 6:
            rows += f'<button class="smore" onclick="this.parentNode.classList.add(\'open\');this.remove()">언급 {shown_n - 6}개 더 보기</button>'
        # 최근 14일 언급 추이 (날짜별 영상 수)
        end_d = datetime.datetime.now(KST).date()
        per = {}
        for v, _ in ms:
            per.setdefault(v.get("date"), set()).add(vid_of(v.get("url")))
        days = [(end_d - datetime.timedelta(days=i)).isoformat() for i in range(13, -1, -1)]
        mx = max([len(per.get(x, ())) for x in days] + [1])
        trend = ('<div class="strend">' + "".join(
            f'<span title="{e(sdate(x))} {len(per.get(x, ()))}편" style="height:{max(4, round(len(per.get(x, ())) / mx * 100))}%" class="{"z" if not per.get(x) else ""}"></span>' for x in days)
            + f'</div><div class="strl"><small>{e(sdate(days[0]))}</small><small>최근 14일 언급 영상 수</small><small>{e(sdate(days[-1]))}</small></div>')
        bd = [x for x in sorted(brief_days.get(k, set()), reverse=True) if x in man["brief"]]
        tone = d.get("tone") if d else None
        dig = (f'<div class="digest"><div class="dh"><b>종합</b><span>영상 {d.get("count")}편 기준 · {e(sdate(d.get("updated")))} 정리</span></div><p>{e(d.get("summary"))}</p>'
               + ("<ul>" + "".join(f"<li>{e(p)}</li>" for p in d.get("points") or []) + "</ul>" if d.get("points") else "") + "</div>") if d else ""
        body = (f'<div class="brief"><div class="bhead"><b>종목</b><span>영상 {len(vids_)}편 · {len(chans)}채널 · 마지막 언급 {e(sdate(last))}</span>'
                f'<a class="link" href="{href("stock/")}">전체 종목 →</a></div>'
                f'<h1>{e(name)}{f" <span class=\"tone t{e(tone)}\" style=\"font-size:.8rem;vertical-align:5px\">{e(tone)}</span>" if tone else ""}</h1>{dig}'
                + sect("언급 추이", "", trend, "c2")
                + sect("채널별 언급", len(ms[:40]), rows and f'<div class="skrb slist" style="padding:0">{rows}</div>', "c4")
                + sect("이 종목이 나온 브리핑", len(bd), bd and '<div class="chips">' + "".join(f'<a href="{href("brief/" + x + "/")}">{e(sdate(x))}</a>' for x in bd) + "</div>", "c1")
                + "</div>" + F.templates())
        desc = desc_of(d.get("summary"), *(d.get("points") or [])) if d else desc_of(f"{name}에 대해 경제 유튜브 채널 {len(chans)}곳이 한 말을 모았다.", *[r[2] for _, r in ms[:3]])
        c = write(f"stock/{s_}", page(f"stock/{quote(s_)}/", f"{name}: 경제 유튜브 채널들의 시각", desc, body, date=(d or {}).get("updated") or last, nav_on="stocks"))
        changed += c
        # 종목 목록의 순위용: 이번 주·지난주 언급 영상 수, 14일 추이, 한 줄 요약
        # 기간별 순위 데이터: 일간(최근 24시간 vs 그 전 24시간), 주간(7일 vs 7일), 월간(30일 vs 30일). [이번 기간 영상 수, 지난 기간 영상 수, 날짜별 막대]
        now_ = datetime.datetime.now(KST)
        t24, t48 = (now_ - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M"), (now_ - datetime.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M")

        def dset(n):
            return [(end_d - datetime.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]

        def cnt(pred):
            return len({vid_of(v.get("url")) for v, _ in ms if pred(v)})
        tsof = lambda v: v.get("ts") or ((v.get("date") or "") + "T00:00")
        dd7, dd30 = dset(14), dset(60)
        per_ = {"day": [cnt(lambda v: tsof(v) >= t24), cnt(lambda v: t48 <= tsof(v) < t24), [len(per.get(x, ())) for x in dset(7)]],
                "week": [cnt(lambda v: (v.get("date") or "") >= dd7[7]), cnt(lambda v: dd7[0] <= (v.get("date") or "") < dd7[7]), [len(per.get(x, ())) for x in dd7]],
                "month": [cnt(lambda v: (v.get("date") or "") >= dd30[30]), cnt(lambda v: dd30[0] <= (v.get("date") or "") < dd30[30]), [len(per.get(x, ())) for x in dd30[30:]]]}
        wk, pw = per_["week"][0], per_["week"][1]
        one = re.split(r"(?<=다\.)\s", (d.get("summary") or "").strip())[0] if d and d.get("summary") else (ms[0][1][2] if ms and len(ms[0][1]) > 2 else "")
        mark("stock", s_, c, {"name": name, "tone": tone, "count": len(vids_), "channels": len(chans), "last": last,
                              "w": wk, "p": pw, "per": per_, "one": one})

    # 영상별 개별 페이지 (검색에 걸리게)
    changed += build_video_pages(V, man, briefs, stock_slug, mark)

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

    # 브리핑 탭: 일간 브리핑 목록, 그 아래 주간 브리핑 목록
    def day_li(d, m):
        x = datetime.date.fromisoformat(d)
        return (f'<li><a class="bli" href="{href("brief/" + d + "/")}"><span class="bld"><b>{x.month}.{x.day:02d}</b><small>{x.year} · {WD[x.weekday()]}</small></span>'
                f'<span class="blt"><b>{e(m.get("headline"))}</b><small>영상 {e(m.get("count"))}편 종합</small></span></a></li>')

    def week_li(w, m):
        a_, b_ = datetime.date.fromisoformat(w), datetime.date.fromisoformat(m.get("end") or w)
        return (f'<li><a class="bli" href="{href("week/" + w + "/")}"><span class="bld wk"><b>{a_.month}.{a_.day:02d}~</b><small>~{b_.month}.{b_.day:02d}</small></span>'
                f'<span class="blt"><b>{e(m.get("headline"))}</b><small>영상 {e(m.get("videos"))}편 종합</small></span></a></li>')

    dl = "".join(day_li(d, m) for d, m in sorted(man["brief"].items(), reverse=True))
    wl = "".join(week_li(w, m) for w, m in sorted(man["week"].items(), reverse=True))
    body = (f'<div class="brief"><h1 style="margin-top:0">시장 브리핑</h1>'
            f'<h2 class="bt c1">일간 브리핑<span class="cn">{len(man["brief"])}</span></h2>'
            + (f'<ul class="plist blist">{dl}</ul>' if dl else '<div class="empty">아직 없다.</div>')
            + (f'<div class="bsec" id="weekly"><h2 class="bt c2">주간 브리핑<span class="cn">{len(man["week"])}</span></h2><ul class="plist blist">{wl}</ul></div>' if wl else "")
            + "</div>")
    changed += write("brief", page("brief/", "시장 브리핑", "경제 유튜브 채널들의 영상을 하루, 한 주 단위로 종합한 시장 브리핑 목록이다.", body, kind="list", nav_on="brief"))
    changed += listing("week", "주간 시장 브리핑", "경제 유튜브 채널들의 한 주 흐름을 종합한 주간 브리핑 목록이다.",
                       "".join(f'<li><a href="{href("week/" + w + "/")}"><b>{e(m.get("headline"))}</b><small>{e(sdate(w))} ~ {e(sdate(m.get("end")))} · 영상 {e(m.get("videos"))}편</small></a></li>'
                               for w, m in sorted(man["week"].items(), reverse=True)), nav_on="brief")
    # 종목 탭: 이번 주 언급 순위 (지난주 대비 순위 변동, 14일 추이, 한 줄 요약). 최근 2주 언급이 없는 종목은 아래 '그 밖의 종목'
    stock_bar = '<div class="vbar"><input id="sq" type="search" placeholder="종목 이름 검색" aria-label="종목 검색"></div>'
    stock_js = """<script>
(()=>{const q=document.getElementById("sq"),rows=[...document.querySelectorAll("[data-name]")];
const p=new URLSearchParams(location.search).get("q");if(p)q.value=p;
const nk=s=>s.replace(/[\\s·・\\-_.()（）]/g,"").toUpperCase();
function f(){const k=nk(q.value);let n=0;rows.forEach(li=>{const ok=!k||nk(li.dataset.name).includes(k);li.hidden=!ok;if(ok)n++});
let em=document.getElementById("sempty");if(!em){em=document.createElement("div");em.id="sempty";em.className="empty";em.textContent="조건에 맞는 종목이 없다.";q.parentNode.after(em)}em.hidden=n>0}
q.addEventListener("input",f);f()})();
</script>"""
    items_ = list(man["stock"].items())
    PERS = {"day": ("일간", "최근 24시간", "전날 대비", 7), "week": ("주간", "이번 주", "지난주 대비", 14), "month": ("월간", "최근 30일", "지난달 대비", 30)}

    def pv(m, mode):
        x = (m.get("per") or {}).get(mode)
        return x if x else [0, 0, [0] * PERS[mode][3]]

    def ranked_of(mode):
        return sorted([x for x in items_ if pv(x[1], mode)[0] + pv(x[1], mode)[1] > 0],
                      key=lambda x: (-pv(x[1], mode)[0], -pv(x[1], mode)[1], -(x[1].get("count") or 0), x[1].get("name") or ""))

    def rank_html(mode):
        rk_ = ranked_of(mode)
        prev = [s_ for s_, m in sorted([x for x in rk_ if pv(x[1], mode)[1] > 0], key=lambda x: -pv(x[1], mode)[1])]
        mxb = max([max(pv(m, mode)[2] or [0]) for _, m in rk_] + [1])

        def move(s_, j):
            if s_ not in prev:
                return '<span class="nkd new">NEW</span>'
            k = prev.index(s_)
            return f'<span class="nkd up">▲{k - j}</span>' if k > j else f'<span class="nkd dn">▼{j - k}</span>' if k < j else '<span class="nkd">–</span>'

        def bars(b):
            return f'<span class="nkt" title="최근 {len(b)}일 언급">' + "".join(f'<i style="height:{max(14, round(n / mxb * 100)) if n else 6}%"{"" if n else " class=z"}></i>' for n in b) + "</span>"

        return "".join(
            f'<div class="nk" data-name="{e(m.get("name"))}"><a class="nkh nkl" href="{href("stock/" + quote(s_) + "/")}"><span class="nkr">{j + 1}{move(s_, j)}</span>'
            f'<span class="nkm"><b>{e(m.get("name"))}' + (f' <span class="tone t{e(m.get("tone"))}">{e(m.get("tone"))}</span>' if m.get("tone") else "")
            + f'</b><small>{e(m.get("one") or "")}</small></span><span class="nkc"><b>{pv(m, mode)[0]}편</b></span>{bars(pv(m, mode)[2])}</a></div>'
            for j, (s_, m) in enumerate(rk_))

    def head(mode):
        n, cur, prv, nb = PERS[mode]
        chips = "".join(f'<button class="chip" data-per="{k}" aria-pressed="{str(k == mode).lower()}">{v[0]}</button>' for k, v in PERS.items())
        return f'<div class="nkhd"><span>화제 종목</span><small>{cur} 언급 순 · {prv} 순위 · 최근 {nb}일 추이</small><div class="chips nper">{chips}</div></div>'

    # 기간 버튼: 세 기간의 순위를 미리 만들어 두고 버튼으로 바꿔 보여 준다 (검색엔진은 기본인 주간을 읽는다)
    panels = "".join(f'<div class="sper" data-p="{k}"{"" if k == "week" else " hidden"}>{head(k)}' + (f'<div class="nks sks">{rank_html(k)}</div>' if rank_html(k) else f'<div class="empty">{PERS[k][1]} 동안 언급된 종목이 없다.</div>') + "</div>" for k in PERS)
    in_any = {s_ for k in PERS for s_, _ in ranked_of(k)}
    rest = sorted([x for x in items_ if x[0] not in in_any], key=lambda x: (x[1].get("last") or ""), reverse=True)
    rs = "".join(f'<li data-name="{e(m.get("name"))}"><a href="{href("stock/" + quote(s_) + "/")}"><b>{e(m.get("name"))}</b>'
                 f'<small>영상 {e(m.get("count"))}편{" · 마지막 언급 " + sdate(m.get("last")) if m.get("last") else ""}</small></a></li>' for s_, m in rest)
    stock_js = stock_js.replace("q.addEventListener(\"input\",f);f()",
                                "q.addEventListener(\"input\",f);document.addEventListener(\"click\",e=>{const b=e.target.closest&&e.target.closest(\"[data-per]\");if(!b)return;"
                                "document.querySelectorAll(\".sper\").forEach(x=>x.hidden=x.dataset.p!==b.dataset.per);"
                                "document.querySelectorAll(\"[data-per]\").forEach(x=>x.setAttribute(\"aria-pressed\",x.dataset.per===b.dataset.per))});f()")
    # 숫자·지표 탭과 같은 모양: 검색창, 안내 한 줄, 순위 카드 (큰 흰 박스로 감싸지 않는다)
    sbody = ('<h1 class="sr">종목</h1>' + stock_bar
             + '<p class="nhint">경제 유튜브 영상에서 언급된 종목을 모았다. 종목을 누르면 채널별 시각과 종합 정리를 볼 수 있다.</p>' + panels
             + (f'<div class="netc"><div class="nkhd"><span>그 밖의 종목</span><small>최근 2주 동안 언급이 없는 종목 {len(rest)}개</small></div>'
                f'<ul class="plist nks sother">{rs}</ul></div>' if rs else "")
             + stock_js)
    changed += write("stock", page("stock/", "종목", "여러 경제 유튜브 채널에서 언급된 종목을 이번 주 언급 순위로 모으고, 채널들의 시각을 정리했다.", sbody, kind="list", nav_on="stocks"))

    # 홈 대시보드: index.html 의 <!--DASH:START--> ~ <!--DASH:END--> 사이를 미리 만든 화면으로 채운다 (검색에 잡히게)
    changed += build_dash(read_const(ROOT / "videos.js", "VIDEOS", []), briefs, weekly, digests, man)

    # 사이트 소개, 개인정보처리방침
    changed += build_info_pages()

    # 사이트맵
    urls = [(url(""), today), (url("brief/"), today), (url("week/"), today), (url("stock/"), today), (url("about/"), INFO_DATE), (url("privacy/"), INFO_DATE)]
    urls += [(url(f"brief/{d}/"), m.get("lastmod", today)) for d, m in man["brief"].items()]
    urls += [(url(f"week/{w}/"), m.get("lastmod", today)) for w, m in man["week"].items()]
    urls += [(url(f"stock/{quote(s_)}/"), m.get("lastmod", today)) for s_, m in man["stock"].items()]
    urls += [(url(f"v/{k}/"), m.get("lastmod", today)) for k, m in man["video"].items()]
    write_rss(man)
    (ROOT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                                      + "".join(f"<url><loc>{html.escape(u)}</loc><lastmod>{lm}</lastmod></url>\n" for u, lm in urls) + "</urlset>\n", encoding="utf-8")
    MANIFEST.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"개별 페이지: 일간 {len(man['brief'])}개, 주간 {len(man['week'])}개, 종목 {len(man['stock'])}개, 영상 {len(man['video'])}개 (이번에 바뀐 페이지 {changed}개)")
    return changed


if __name__ == "__main__":
    build()
