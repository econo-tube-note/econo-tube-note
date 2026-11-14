#!/usr/bin/env python3
"""유튜브 영상을 제미나이로 요약해서 videos.js에 추가한다.

사용법
  python scripts/summarize.py <영상주소> [<영상주소> ...]   (주소를 직접 준다)
  python scripts/summarize.py                                (주소 없이 실행하면 channels.json의 채널에서 새 영상을 찾아 요약한다)
필요한 것: 환경변수 GEMINI_API_KEY (GitHub 비밀 저장 공간에서 넣어 준다)
"""
import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# 모델 이름은 여기(또는 워크플로 파일의 GEMINI_MODEL)에서 바꾼다.
try:
    sys.stdout.reconfigure(line_buffering=True)  # 로그가 바로바로 보이게 한다
except Exception:
    pass

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
CALL_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "300"))  # 제미나이 응답을 기다리는 최대 시간(초)
DATA = Path(__file__).resolve().parent.parent / "videos.js"
HEADER = "/* 영상 목록. 자동화(scripts/summarize.py)가 갱신하는 파일이다. 직접 고칠 때는 JSON 형식을 지킨다. */\n"
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})")

PROMPT = """너는 한국 경제·투자 유튜브 영상을 요약하는 편집자다. 영상을 보고 아래 규칙대로 JSON으로만 답해라.

규칙
- 문체는 모두 '~다'로 통일한다.
- people: 출연자 이름을 쉼표로 적는다. 모르면 빈 문자열.
- conclusion: 영상의 한 줄 결론 (한 문장).
- tags: 키워드 3개. '하락장', '외국인수급', '반도체', '금리', '환율'처럼 짧고 흔한 말을 우선 쓴다.
- parts: 영상 내용을 주제별로 2~4개 파트로 나눈다. 파트 제목(title)은 네가 정한다. 각 파트에 핵심 항목을 3~4개 넣는다. 항목 text는 '소제목: 설명' 형식으로 쓴다. 출연자의 전망이나 의견은 '~라고 본다', '~라고 주장한다'처럼 출연자의 말이라는 것이 드러나게 쓴다.
- stocks: 중요하게 다룬 종목 최대 7개. name에는 종목명만 쓰고 괄호로 다른 이름을 덧붙이지 않는다. note에는 출연자가 그 종목에 대해 어떤 평가를 했는지(긍정, 부정, 이유)를 한 줄로 쓴다. '언급됐다'만 쓰지 않는다.
- numbers: 가장 중요한 숫자 4~5개만. value는 영상에서 말한 단위와 기준 그대로 적고, 단위나 기준이 분명하지 않으면 '(단위 불명확)'을 붙인다. note에는 숫자의 의미를 한 줄로 쓴다.
- time: 해당 내용이 영상에서 나오는 시간. 링크나 주소 없이 '분:초' 글자만 적는다. 예: 06:34 (1시간이 넘으면 1:05:30). 확실하지 않으면 빈 문자열로 둔다.
- 영상에 없는 내용은 쓰지 않는다. 네가 아는 정보로 영상 내용의 사실 여부를 판단하거나 정정하지 않는다. 추측하지 않는다.
"""


# ---------- 제한 시간 ----------
def run_with_timeout(fn, seconds):
    """fn을 실행하되 seconds초 안에 안 끝나면 TimeoutError를 낸다."""
    box = {}

    def target():
        try:
            box["v"] = fn()
        except BaseException as e:
            box["e"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise TimeoutError(f"{seconds}초 안에 응답이 없다")
    if "e" in box:
        raise box["e"]
    return box["v"]


# ---------- 제미나이 호출 (이 함수만 외부 라이브러리를 쓴다) ----------
def call_gemini(video_url):
    from google import genai
    from google.genai import types
    from pydantic import BaseModel

    class Item(BaseModel):
        time: str
        text: str

    class SPart(BaseModel):
        title: str
        items: list[Item]

    class Stock(BaseModel):
        time: str
        name: str
        note: str

    class Num(BaseModel):
        time: str
        value: str
        note: str

    class Summary(BaseModel):
        people: str
        conclusion: str
        tags: list[str]
        parts: list[SPart]
        stocks: list[Stock]
        numbers: list[Num]

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    # 첫 번째 모델이 바쁘거나(503) 없으면(404) 다음 모델로 넘어간다
    fallbacks = os.environ.get("GEMINI_FALLBACKS", "gemini-3.7-flash,gemini-3.5-flash-lite")
    models = [MODEL] + [m.strip() for m in fallbacks.split(",") if m.strip() and m.strip() != MODEL]
    permanent = ("NOT_FOUND", "PERMISSION_DENIED", "INVALID_ARGUMENT", "UNAUTHENTICATED")
    last = None
    for model in models:
        for attempt in range(3):
            try:
                def ask(model=model):
                    return client.models.generate_content(
                        model=model,
                        contents=types.Content(
                            parts=[
                                types.Part(file_data=types.FileData(file_uri=video_url)),
                                types.Part(text=PROMPT),
                            ]
                        ),
                        config=types.GenerateContentConfig(
                            response_mime_type="application/json",
                            response_schema=Summary,
                            temperature=0.2,
                        ),
                    )

                print(f"  [{model}] 요청 보냄 (최대 {CALL_TIMEOUT}초 기다림)")
                resp = run_with_timeout(ask, CALL_TIMEOUT)
                print(f"  사용한 모델: {model}")
                return json.loads(resp.text)
            except TimeoutError as e:
                last = e
                print(f"  [{model}] {e} -> 다음 모델로 넘어간다")
                break
            except Exception as e:
                last = e
                print(f"  [{model}] 호출 실패({attempt + 1}/3): {str(e)[:200]}")
                if any(c in str(e) for c in permanent):
                    break  # 이 모델은 다시 해도 소용없으니 다음 모델로
                time.sleep(20 * (attempt + 1))  # 바쁠 때는 조금씩 더 쉬고 다시 시도
    raise RuntimeError(f"제미나이 호출 실패: {last}")


# ---------- 영상 정보(제목, 채널, 날짜) ----------
def http_get(url, timeout=20):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko,en;q=0.8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:200].replace("\n", " ")
        raise RuntimeError(f"HTTP {e.code} {e.reason}: {body}") from None


def get_meta(vid):
    url = f"https://www.youtube.com/watch?v={vid}"
    o = json.loads(
        http_get("https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe=""))
    )
    title = (o.get("title") or "").strip()
    channel = (o.get("author_name") or "").strip()
    date = ""
    try:
        html = http_get(url)
        for pat in (
            r'itemprop="uploadDate"\s+content="(\d{4}-\d{2}-\d{2})',
            r'"uploadDate":"(\d{4}-\d{2}-\d{2})',
            r'"publishDate":"(\d{4}-\d{2}-\d{2})',
        ):
            m = re.search(pat, html)
            if m:
                date = m.group(1)
                break
    except Exception:
        pass
    if not date:  # 날짜를 못 읽으면 오늘(한국 시간) 날짜를 쓴다
        kst = datetime.timezone(datetime.timedelta(hours=9))
        date = datetime.datetime.now(kst).strftime("%Y-%m-%d")
    return title, channel, date


# ---------- 점검과 정리 ----------
def clean(s, vid_url, title, channel, date):
    def tm(t):
        t = (t or "").strip()
        return t if TIME_RE.match(t) else ""  # 형식이 틀리면 시간을 비운다

    parts = []
    for p in s.get("parts") or []:
        items = [[tm(i.get("time")), (i.get("text") or "").strip()]
                 for i in p.get("items") or [] if (i.get("text") or "").strip()]
        if items:
            parts.append({"t": (p.get("title") or "").strip(), "items": items})
    conclusion = (s.get("conclusion") or "").strip()
    if not conclusion or not parts:
        raise ValueError("요약에 결론이나 주제별 내용이 비어 있다")

    stocks = [[tm(x.get("time")), (x.get("name") or "").strip(), (x.get("note") or "").strip()]
              for x in (s.get("stocks") or [])[:7] if (x.get("name") or "").strip()]
    numbers = [[tm(x.get("time")), (x.get("value") or "").strip(), (x.get("note") or "").strip()]
               for x in (s.get("numbers") or [])[:6] if (x.get("value") or "").strip()]
    tags = [t.strip() for t in (s.get("tags") or []) if t.strip()][:3]

    entry = {"url": vid_url, "channel": channel, "date": date, "title": title}
    if (s.get("people") or "").strip():
        entry["people"] = s["people"].strip()
    entry.update({"conclusion": conclusion, "tags": tags, "parts": parts,
                  "stocks": stocks, "numbers": numbers})
    return entry


# ---------- videos.js 읽기/쓰기 ----------
def load():
    if not DATA.exists():
        return []
    s = DATA.read_text(encoding="utf-8")
    s = s[s.index("const VIDEOS=") + len("const VIDEOS="):]
    return json.loads(s[s.index("["): s.rindex("]") + 1])


def save(videos):
    keep = int(os.environ.get("MAX_KEEP", "240"))  # 사이트에는 최신 영상만 남기고 나머지는 archive.json으로 옮긴다
    if len(videos) > keep:
        old, videos = videos[keep:], videos[:keep]
        write_json(ARCHIVE, read_json(ARCHIVE, []) + old)
    DATA.write_text(
        HEADER + "const VIDEOS=" + json.dumps(videos, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8",
    )


def video_id(url):
    m = ID_RE.search(url or "")
    return m.group(1) if m else None


# ---------- 자동 모드: 채널의 새 영상을 찾아서 요약 ----------
ROOT = DATA.parent
CHANNELS = ROOT / "channels.json"
STATE = ROOT / "state.json"
ARCHIVE = ROOT / "archive.json"
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
KST = datetime.timezone(datetime.timedelta(hours=9))


def cfg(name, default):
    return int(os.environ.get(name, default))


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def resolve_channel_id(handle):
    html = http_get("https://www.youtube.com/" + handle.lstrip("/"))
    for pat in (
        r'"externalId":"(UC[\w-]{22})"',
        r'rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
        r'"channelId":"(UC[\w-]{22})"',
    ):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return ""


def parse_feed(xml):
    root = ET.fromstring(xml.encode("utf-8"))
    author = (root.findtext("a:author/a:name", default="", namespaces=NS) or "").strip()
    out = []
    for e in root.findall("a:entry", NS):
        link = e.find("a:link", NS)
        href = link.get("href", "") if link is not None else ""
        try:
            ts = datetime.datetime.fromisoformat((e.findtext("a:published", default="", namespaces=NS) or "").replace("Z", "+00:00"))
        except Exception:
            continue
        out.append({
            "id": e.findtext("yt:videoId", default="", namespaces=NS),
            "title": (e.findtext("a:title", default="", namespaces=NS) or "").strip(),
            "published": ts,
            "short": "/shorts/" in href,
        })
    return author, out  # 피드는 최신순


def parse_iso_duration(v):
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", v or "")
    if not m:
        return 0
    d, h, mi, sec = [int(x or 0) for x in m.groups()]
    return d * 86400 + h * 3600 + mi * 60 + sec


def fetch_via_api(cid, key):
    """유튜브 공식 API(YouTube Data API)로 최근 영상을 가져온다. 길이와 생방송 여부도 같이 온다."""
    base = "https://www.googleapis.com/youtube/v3/"
    pl = json.loads(http_get(f"{base}playlistItems?part=contentDetails&maxResults=15&playlistId=UU{cid[2:]}&key={key}"))
    ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
    if not ids:
        return "", []
    vd = json.loads(http_get(f"{base}videos?part=contentDetails,snippet&id={','.join(ids)}&key={key}"))
    meta = {v["id"]: v for v in vd.get("items", [])}
    author, out = "", []
    for vid in ids:  # 재생목록은 최신순
        v = meta.get(vid)
        if not v:
            continue
        sn = v["snippet"]
        author = author or sn.get("channelTitle", "")
        live = sn.get("liveBroadcastContent", "none")
        out.append({
            "id": vid,
            "title": sn.get("title", "").strip(),
            "published": datetime.datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")),
            "short": False,
            "length": parse_iso_duration(v["contentDetails"].get("duration", "")),
            "live": live == "live",
            "upcoming": live == "upcoming",
        })
    return author, out


def fetch_entries(cid):
    """채널의 최근 영상 목록. 공식 API 키가 있으면 먼저 쓰고, 안 되면 RSS 주소를 여러 방법으로 시도한다."""
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if key:
        try:
            return fetch_via_api(cid, key)
        except Exception as e:
            print(f"  공식 API 실패: {str(e)[:200]}")
    plan = [
        (f"channel_id={cid}", 3),         # 일반 채널 피드
        (f"playlist_id=UULF{cid[2:]}", 2),  # 쇼츠·생방송을 뺀 업로드 목록
        (f"playlist_id=UU{cid[2:]}", 1),    # 전체 업로드 목록
    ]
    last = None
    for query, tries in plan:
        for i in range(tries):
            try:
                return parse_feed(http_get("https://www.youtube.com/feeds/videos.xml?" + query))
            except Exception as e:
                last = e
                print(f"  피드 실패 ({query.split('=')[0]}, {i + 1}/{tries}): {str(e)[:120]}")
                if i < tries - 1:
                    time.sleep(15)
    raise RuntimeError(f"목록을 가져오지 못했다: {str(last)[:120]}")


def get_info(vid):
    try:
        html = http_get(f"https://www.youtube.com/watch?v={vid}")
    except Exception:
        return {}
    m = re.search(r'"lengthSeconds":"(\d+)"', html)
    return {"length": int(m.group(1)) if m else 0,
            "live": '"isLive":true' in html, "upcoming": '"isUpcoming":true' in html}


def interleave(lists):
    """채널마다 최신 영상부터 한 편씩 번갈아 꺼낸다. (한 채널이 예산을 다 쓰지 않게)"""
    out = []
    for i in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if i < len(l):
                out.append(l[i])
    return out


def auto():
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY가 없다. GitHub 비밀 저장 공간에 키를 넣었는지 확인해라.")
        return 1
    max_age, max_len = cfg("MAX_AGE_DAYS", 2), cfg("MAX_VIDEO_MIN", 90) * 60
    min_len, budget = cfg("MIN_VIDEO_SEC", 180), cfg("DAILY_BUDGET_MIN", 450) * 60
    per_run = cfg("MAX_PER_RUN", 6)
    deadline = time.time() + cfg("RUN_DEADLINE_MIN", 60) * 60

    channels = read_json(CHANNELS, [])
    if not channels:
        print("channels.json이 없거나 비어 있다.")
        return 1
    state = read_json(STATE, {})
    for k in ("skipped", "failed", "spent"):
        state.setdefault(k, {})
    now = datetime.datetime.now(datetime.timezone.utc)
    today = now.astimezone(KST).strftime("%Y-%m-%d")
    week_ago = (now.astimezone(KST) - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    state["spent"] = {d: v for d, v in state["spent"].items() if d >= week_ago}
    spent = state["spent"].get(today, 0)

    videos = load()
    have = {video_id(v.get("url")) for v in videos + read_json(ARCHIVE, [])}

    lists, ids_changed = [], False
    for ch in channels:
        if not ch.get("id"):
            try:
                ch["id"] = resolve_channel_id(ch["handle"])
            except Exception as e:
                print(f"채널 ID 찾기 실패: {ch['name']} ({ch['handle']}): {str(e)[:150]}")
                continue
            if not ch["id"]:
                print(f"채널 ID를 못 찾았다: {ch['name']} ({ch['handle']}). channels.json의 id에 직접 넣어야 한다.")
                continue
            ids_changed = True
        try:
            author, entries = fetch_entries(ch["id"])
        except Exception as e:
            print(f"채널 영상 목록 실패: {ch['name']}: {e}")
            continue
        print(f"채널 확인: {ch['name']} -> {author} ({ch['id']}), 최근 영상 {len(entries)}편")
        fresh = []
        for e in entries:
            if e["id"] in have or e["id"] in state["skipped"]:
                continue
            if (now - e["published"]).total_seconds() > max_age * 86400:
                continue
            e["channel"] = author or ch["name"]
            fresh.append(e)
        lists.append(fresh)
    if ids_changed:
        write_json(CHANNELS, channels)
    if not lists:
        print("어느 채널의 영상 목록도 가져오지 못했다. (유튜브 쪽 일시 오류일 수 있다. 다음 실행 때 다시 시도한다.)")

    done, bad_streak = 0, 0
    for e in interleave(lists):
        if done >= per_run or time.time() > deadline:
            print("이번 실행에서 처리할 수 있는 한도에 도달했다.")
            break
        vid = e["id"]
        if e["short"]:
            state["skipped"][vid] = "쇼츠"
            continue
        info = {"length": e["length"], "live": e["live"], "upcoming": e["upcoming"]} if "length" in e else get_info(vid)
        if info.get("live") or info.get("upcoming"):
            print(f"생방송 중이거나 예정된 영상이라 다음에 처리한다: {e['title']}")
            continue
        length = info.get("length") or 0
        if 0 < length < min_len:
            state["skipped"][vid] = "너무 짧음"
            continue
        if length > max_len:
            state["skipped"][vid] = f"너무 긴 영상({length // 60}분)"
            print(f"너무 길어서 건너뜀({length // 60}분): {e['title']}")
            continue
        est = length or 1800  # 길이를 모르면 30분으로 계산한다
        if spent + est > budget:
            print(f"오늘 처리 시간 예산을 넘어서 다음으로 미룬다: {e['title']}")
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        print(f"요약 시작: {e['channel']} | {e['title']} ({est // 60}분)")
        try:
            entry = clean(call_gemini(url), url, e["title"], e["channel"],
                          e["published"].astimezone(KST).strftime("%Y-%m-%d"))
            videos.insert(0, entry)
            have.add(vid)
            state["failed"].pop(vid, None)
            spent += est
            state["spent"][today] = spent
            done, bad_streak = done + 1, 0
            save(videos)
            print(f"  완료: {e['title']}")
        except Exception as ex:
            n = state["failed"].get(vid, 0) + 1
            state["failed"][vid] = n
            bad_streak += 1
            print(f"  실패({n}번째): {str(ex)[:200]}")
            if n >= 5:
                state["skipped"][vid] = "요약 5번 실패"
                state["failed"].pop(vid, None)
        write_json(STATE, state)
        if bad_streak >= 2:
            print("연속으로 실패해서 이번 실행은 여기서 멈춘다. (구글이 혼잡할 수 있다. 다음 실행 때 다시 시도한다.)")
            break
        time.sleep(5)

    write_json(STATE, state)
    print(f"\n이번 실행: 성공 {done}편 | 오늘 사용한 영상 시간 {spent // 60}분 / 예산 {budget // 60}분")
    return 0


# ---------- 실행 ----------
def main(argv):
    urls = [u for u in re.split(r"[\s,]+", " ".join(argv)) if u]
    if not urls:
        return auto()
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY가 없다. GitHub 비밀 저장 공간에 키를 넣었는지 확인해라.")
        return 1

    videos = load()
    have = {video_id(v.get("url")) for v in videos + read_json(ARCHIVE, [])}
    ok, failed = [], []
    for u in urls:
        vid = video_id(u)
        if not vid:
            failed.append((u, "영상 ID를 찾을 수 없는 주소"))
            continue
        if vid in have:
            print(f"이미 있는 영상이라 건너뜀: {vid}")
            continue
        print(f"요약 시작: {vid}")
        try:
            title, channel, date = get_meta(vid)
            summary = call_gemini(f"https://www.youtube.com/watch?v={vid}")
            entry = clean(summary, f"https://www.youtube.com/watch?v={vid}", title, channel, date)
            videos.insert(0, entry)
            have.add(vid)
            ok.append(vid)
            save(videos)  # 한 편 끝날 때마다 저장
            print(f"  완료: {title}")
        except Exception as e:
            failed.append((u, str(e)))
            print(f"  실패: {e}")
        time.sleep(5)

    print(f"\n성공 {len(ok)}편, 실패 {len(failed)}편")
    for u, why in failed:
        print(f"  - {u}: {why}")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
