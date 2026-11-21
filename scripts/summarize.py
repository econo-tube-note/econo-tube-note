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

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")
CALL_TIMEOUT = int(os.environ.get("GEMINI_TIMEOUT", "300"))  # 제미나이 응답을 기다리는 최대 시간(초)
STATS = []   # (모델, 결과) 기록. 결과는 ok / busy / dead
DEAD = set()  # 이번 실행에서 쓸 수 없다고 확인된 모델
MODEL_STATS = {}  # 모델별 누적 기록 (state.json의 models). 잘 되는 모델을 먼저 쓰는 데 쓴다

DATA = Path(__file__).resolve().parent.parent / "videos.js"
HEADER = "/* 영상 목록. 자동화(scripts/summarize.py)가 갱신하는 파일이다. 직접 고칠 때는 JSON 형식을 지킨다. */\n"
TIME_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")
ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/)([A-Za-z0-9_-]{11})")

# 숫자 지표 이름 목록 (프롬프트와 canon_label이 같이 쓴다)
NUM_LABELS = ["코스피 지수", "코스닥 지수", "나스닥 지수", "S&P500 지수", "다우 지수", "닛케이 지수", "필라델피아 반도체 지수",
              "원/달러 환율", "엔/달러 환율", "달러 인덱스", "미국 10년물 국채 금리", "미국 2년물 국채 금리", "미국 국채 금리",
              "한국 국고채 금리", "미국 기준금리", "한국 기준금리", "외국인 순매도", "외국인 순매수", "기관 순매도", "기관 순매수",
              "개인 순매도", "개인 순매수", "신용잔고",
              "반대매매", "고객예탁금", "비트코인 가격", "금 가격", "국제유가", "물가", "고용 지표", "GDP 성장률",
              "PER·PBR", "기업 실적", "목표 주가", "주가 등락률", "시가총액", "수출"]

PROMPT = """너는 한국 경제·투자 유튜브 영상을 요약하는 편집자다. 영상을 보고 아래 규칙대로 JSON으로만 답해라.

규칙
- 문체는 모두 '~다'로 통일한다.
- people: 출연자 이름을 쉼표로 적는다. 모르면 빈 문자열.
- conclusion: 영상의 핵심 결론. 짧게 쓴다. 공백 포함 55자 안팎으로, 최대 두 문장까지 허용한다. 한 문장에 정보를 여러 개 쉼표로 이어 붙이지 말고 핵심 하나만 담는다.
- economic: 이 영상의 중심 내용이 경제·주식·투자·산업·부동산·재테크이면 true, 아니면 false다. 경제 채널 영상이어도 교육, 사회 사건, 건강, 재난, 경제 얘기가 거의 없는 정치·안보 등이 중심이면 false다.
- mood: 이 영상 출연자들이 시장(주식시장 전반)을 보는 분위기를 '낙관', '중립', '비관' 중 하나로 쓴다. 상승·매수 기회를 강조하면 낙관, 하락·위험·매도를 강조하면 비관, 관망을 권하거나 출연자끼리 의견이 갈리거나 시장 전망이 아닌 내용이면 중립이다.
- tags: 키워드 3개. '하락장', '외국인수급', '반도체', '금리', '환율'처럼 짧고 흔한 말을 우선 쓴다.
- parts: 영상 내용을 주제별로 2~4개 파트로 나눈다. 파트 제목(title)은 네가 정한다. 각 파트에 핵심 항목을 3~4개 넣는다. 항목 text는 '소제목: 설명' 형식으로 쓴다. 출연자의 전망이나 의견은 '~라고 본다', '~라고 주장한다'처럼 출연자의 말이라는 것이 드러나게 쓴다.
- 항목 설명은 영상을 안 본 사람이 읽고 '무엇이, 왜, 얼마나'를 알 수 있게 구체적으로 쓴다. 영상에 나온 숫자, 종목·기업·인물 이름, 근거를 넣는다.
  나쁜 예: '시장 악재: AI 투자 확대에 대한 노이즈가 커졌다고 본다.' (무슨 노이즈인지 모른다)
  좋은 예: '시장 악재: 오픈AI의 데이터센터 투자 축소설이 돌면서 AI 투자 사이클이 꺾이는 것 아니냐는 우려가 커졌다고 본다.'
  '중요하다고 본다', '불확실성이 커졌다', '보수적으로 대응해야 한다'처럼 어느 영상에나 쓸 수 있는 말만으로 항목을 채우지 않는다. 그런 결론이면 왜 그렇게 보는지 근거를 함께 쓴다.
- 항목마다 설명 끝맺음을 '~라고 본다'로만 반복하지 말고 '~라고 설명한다', '~라고 지적한다', '~라고 전망한다'처럼 내용에 맞게 쓴다.
- stocks: 중요하게 다룬 종목 최대 7개. name에는 종목명만 쓰고 괄호로 다른 이름을 덧붙이지 않는다. 줄임말이나 영어 대신 한국에서 흔히 쓰는 정식 이름을 쓴다(예: 하이닉스→SK하이닉스, 삼전→삼성전자, NVIDIA→엔비디아, 증권사 앱에 표시되는 종목명 기준). note에는 출연자가 그 종목에 대해 어떤 평가를 했는지(긍정, 부정, 이유)를 한 줄로 쓴다. '언급됐다'만 쓰지 않는다.
- numbers: 가장 중요한 숫자 4~5개만. label은 그 숫자가 가리키는 지표 이름이다. 다음 목록에 맞는 게 있으면 반드시 그 이름을 글자 그대로 쓴다: {NUM_LABELS}. 목록에 없으면 짧은 명사구로 쓰고, 지표라고 하기 어려우면 '기타'로 쓴다. 숫자가 금액이면 그 금액의 주체 기준으로 고른다(예: 외국인이 판 금액은 코스피 지수가 아니라 외국인 순매도, 산 금액은 외국인 순매수). value는 영상에서 말한 단위와 기준 그대로 적고, 단위나 기준이 분명하지 않으면 '(단위 불명확)'을 붙인다. note는 그 숫자가 '무엇의' 숫자인지 주어를 반드시 밝혀서 한 줄로 쓴다. 숫자 카드만 따로 떼어 봐도 이해되게 쓴다.
  나쁜 예: value '2.894조 달러', note '10월 28일 기준 저점을 기록한 후 회복세로 전환되었다고 설명한다.' (무엇이 2.894조 달러인지 없다)
  좋은 예: label '미국 지급준비금', value '2.894조 달러', note '미국 은행들의 지급준비금이 10월 28일 이 수준에서 바닥을 찍고 회복 중이라고 설명한다.'
  label은 가능한 한 구체적인 지표 이름으로 쓰고, 정말 지표로 묶을 수 없을 때만 '기타'로 쓴다.
  kind는 그 숫자의 성격을 '현재', '전망', '과거' 중 하나로 쓴다. 지금 시점의 수치나 최근 실적이면 현재, 앞으로의 예상·목표·목표가면 전망, 지난 기록이나 비교용 과거 수치면 과거다.
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


def model_rate(m):
    c = MODEL_STATS.get(m, {})
    return (c.get("ok", 0) + 1) / (c.get("ok", 0) + c.get("busy", 0) + 2)


# ---------- 제미나이 호출 (이 함수만 외부 라이브러리를 쓴다) ----------
def is_lite(m):
    return "lite" in (m or "")


# ---------- 자막(스크립트) 시험 ----------
def fetch_transcript(vid):
    """유튜브 자막을 가져온다. [(시작초, 글)] 목록. 실패하면 예외를 낸다."""
    from youtube_transcript_api import YouTubeTranscriptApi
    langs = ["ko", "en"]
    try:  # 새 버전
        got = YouTubeTranscriptApi().fetch(vid, languages=langs)
        return [(float(x.start), x.text) for x in got]
    except AttributeError:  # 옛 버전
        got = YouTubeTranscriptApi.get_transcript(vid, languages=langs)
        return [(float(x["start"]), x["text"]) for x in got]


def parse_json3(raw):
    """유튜브 자막(json3 형식)을 [(시작초, 글)]로 바꾼다."""
    data = json.loads(raw)
    out = []
    for ev in data.get("events") or []:
        text = "".join(sg.get("utf8", "") for sg in ev.get("segs") or []).replace("\n", " ").strip()
        if text:
            out.append((ev.get("tStartMs", 0) / 1000, text))
    return out


class _YLog:
    """yt-dlp가 남기는 경고를 모아 둔다 (실패 원인을 로그에 보여 주기 위해)"""
    def __init__(self):
        self.msgs = []

    def debug(self, m):
        pass

    def info(self, m):
        pass

    def warning(self, m):
        self.msgs.append(str(m))

    def error(self, m):
        self.msgs.append(str(m))


def fetch_transcript_ytdlp(vid, cookiefile=""):
    """yt-dlp로 자막을 가져온다. 쿠키 파일이 있으면 로그인한 상태로 요청한다.
    자막 목록이 비어 오면 유튜브에 요청하는 방식(웹, 모바일 웹, TV 등)을 바꿔 가며 다시 시도한다."""
    import yt_dlp
    reasons = []
    for client in [None] + [c.strip() for c in os.environ.get("YTDLP_CLIENTS", "mweb,tv,web_safari,web_embedded").split(",") if c.strip()]:
        log = _YLog()
        opts = {"skip_download": True, "quiet": True, "no_warnings": False, "ignore_no_formats_error": True, "logger": log}
        if cookiefile:
            opts["cookiefile"] = cookiefile
        if client:
            opts["extractor_args"] = {"youtube": {"player_client": [client]}}
        name = client or "기본"
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)
                pools = [("수동 자막", info.get("subtitles") or {}), ("자동 자막", info.get("automatic_captions") or {})]
                for kind, pool in pools:
                    for lang in ("ko", "ko-orig", "ko-KR"):
                        for f in pool.get(lang) or []:
                            if f.get("ext") == "json3" and f.get("url"):
                                try:
                                    raw = ydl.urlopen(f["url"]).read().decode("utf-8")
                                except Exception as e:
                                    reasons.append(f"{name}: 자막 내용 받기 실패({str(e)[:60]})")
                                    continue
                                lines = parse_json3(raw)
                                if lines:
                                    return lines, f"{kind}({lang}, {name})"
                langs = sorted(set(pools[0][1]) | {k for k in pools[1][1] if k.startswith(("ko", "en"))})
                hint = ""
                joined = " ".join(log.msgs)
                if "Sign in" in joined or "not a bot" in joined or "cookies" in joined.lower():
                    hint = " / 로그인 확인 요구(쿠키 문제일 수 있다)"
                reasons.append(f"{name}: 영상 형식 {len(info.get('formats') or [])}개, 자막 {', '.join(langs) or '없음'}{hint}")
        except Exception as e:
            reasons.append(f"{name}: {str(e).splitlines()[0][:80] if str(e) else type(e).__name__}")
    raise RuntimeError("한국어 자막을 못 받았다 → " + " | ".join(reasons)[:400])


def mmss(sec):
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}" if sec >= 3600 else f"{sec // 60:02d}:{sec % 60:02d}"


PROMPT = PROMPT.replace("{NUM_LABELS}", ", ".join(NUM_LABELS))
TRANSCRIPT_PROMPT = PROMPT.replace("영상을 보고 아래 규칙대로", "아래 자막(대본)을 읽고 아래 규칙대로") + """
- 입력은 영상의 자동 자막이다. 각 줄 앞의 [분:초]가 그 말이 나온 시간이다. time에는 이 시간을 쓴다.
- 자동 자막이라 종목명, 숫자, 사람 이름이 소리 나는 대로 잘못 적혀 있을 수 있다. 문맥으로 분명할 때만 바로잡고, 애매하면 그 항목을 쓰지 않는다.

자막:
"""


def transcript_test(target=""):
    """GitHub 서버에서 자막을 가져올 수 있는지, 자막으로 요약하면 품질이 어떤지 시험한다. 사이트에는 아무것도 저장하지 않는다."""
    videos = load()
    if target:
        vids = [video_id(target)] if video_id(target) else []
    else:
        vids = [video_id(v["url"]) for v in videos[:3]]
    print("자막 가져오기 시험 (사이트에는 저장하지 않는다)")
    cookie = os.environ.get("YT_COOKIES_FILE", "")
    if cookie and not (os.path.exists(cookie) and os.path.getsize(cookie) > 50):
        cookie = ""
    methods = [("기본(쿠키 없음)", lambda v: (fetch_transcript(v), "youtube-transcript-api"))]
    methods.append(("yt-dlp + 쿠키" if cookie else "yt-dlp(쿠키 없음)", lambda v: fetch_transcript_ytdlp(v, cookie)))
    print("쿠키: " + ("있음 (GitHub 비밀값 YOUTUBE_COOKIES)" if cookie else "없음"))
    got = None
    for name, fn in methods:
        print(f"\n[방법] {name}")
        for n, vid in enumerate(vids):
            if n:
                time.sleep(5)  # 클라우드 서버에서 연달아 요청하면 유튜브가 막기 쉬워서 간격을 둔다
            try:
                lines, how = fn(vid)
                chars = sum(len(t) for _, t in lines)
                print(f"  성공: {vid} | {how} | 자막 {len(lines)}줄, {chars}자 | 첫 줄: {lines[0][1][:40] if lines else ''}")
                if got is None and lines:
                    got = (vid, lines)
            except Exception as e:
                print(f"  실패: {vid} | {type(e).__name__}: {str(e).splitlines()[0][:200] if str(e) else ''}")
    if not got:
        print("\n결과: 어떤 방법으로도 자막을 못 가져왔다.")
        return 0
    vid, lines = got
    text = "\n".join(f"[{mmss(st)}] {t}" for st, t in lines)
    print(f"\n자막으로 요약해 본다: {vid} (자막 {len(text)}자)")
    t0 = time.time()
    out = call_json(TRANSCRIPT_PROMPT + text, summary_schema, "TRANSCRIPT_MODELS", "gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash-lite", 180)
    print(f"  걸린 시간: {time.time() - t0:.0f}초")
    old = next((v for v in videos if video_id(v["url"]) == vid), None)

    def show(label, conclusion, parts, stocks, numbers):
        print(f"\n===== {label} =====")
        print(f"결론: {conclusion}")
        for p in parts:
            print(f"[{p['t']}]")
            for t, x in p["items"]:
                print(f"  {t:>6} {x}")
        print("종목: " + " / ".join(f"{s[1]}({s[2]})" for s in stocks))
        print("숫자: " + " / ".join(f"{n[1]} - {n[2]}" for n in numbers))

    try:
        new = clean(out, f"https://www.youtube.com/watch?v={vid}", "", "", "")
        show("자막으로 만든 요약", new["conclusion"], new["parts"], new["stocks"], new["numbers"])
    except Exception as e:
        print(f"  자막 요약 정리 실패: {e}")
    if old:
        show(f"지금 사이트의 요약 (영상으로 만든 것, {old.get('model', '모델 기록 없음')})", old.get("conclusion"), old.get("parts") or [], old.get("stocks") or [], old.get("numbers") or [])
    return 0


SLOT_NAMES = ("저녁(17~24시)", "새벽(0~7시)", "오전(7~12시)", "오후(12~17시)")


def budget_window(now):
    """영상 예산의 '하루'와 지금까지 쓸 수 있는 누적 시간(초)을 돌려준다.
    하루는 오후 5시에 시작하고, 시간대별 몫(SLOT_BUDGET_MIN)을 차례로 더한다. 앞 시간대에서 안 쓴 몫은 뒤로 넘어간다."""
    k = now.astimezone(KST) - datetime.timedelta(hours=17)
    day = k.strftime("%Y-%m-%d")
    h = k.hour  # 0~6: 17~24시, 7~13: 0~7시, 14~18: 7~12시, 19~23: 12~17시
    idx = 0 if h < 7 else 1 if h < 14 else 2 if h < 19 else 3
    slots = [int(x) for x in os.environ.get("SLOT_BUDGET_MIN", "170,0,200,100").split(",")][:4]
    slots += [0] * (4 - len(slots))
    return "17시~" + day, sum(slots[:idx + 1]) * 60, SLOT_NAMES[idx]  # 예전(자정 기준) 기록과 이름이 겹치지 않게 앞에 붙인다


def summary_schema():
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
        label: str
        value: str
        note: str
        kind: str

    class Summary(BaseModel):
        people: str
        conclusion: str
        economic: bool
        mood: str
        tags: list[str]
        parts: list[SPart]
        stocks: list[Stock]
        numbers: list[Num]

    return Summary


FPS_OK = [True]  # 영상 프레임 수 줄이기 설정이 받아들여지는지 (거절되면 이번 실행에서는 끈다)


def video_part(types, video_url):
    """영상을 넘길 때 화면을 몇 초에 한 장 볼지 정한다. 소리는 그대로 다 듣는다."""
    fps = float(os.environ.get("VIDEO_FPS", "0.2") or 0)
    if fps and FPS_OK[0]:
        try:
            return types.Part(file_data=types.FileData(file_uri=video_url), video_metadata=types.VideoMetadata(fps=fps))
        except Exception:
            FPS_OK[0] = False
    return types.Part(file_data=types.FileData(file_uri=video_url))


def call_gemini(video_url, allow_lite=True, transcript=None):
    """영상을 요약한다. transcript(자막 글)가 있으면 영상 대신 자막을 읽고 요약한다.
    allow_lite가 False면 품질이 낮은 lite 모델은 쓰지 않는다."""
    from google import genai
    from google.genai import types

    Summary = summary_schema()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    # 모델을 차례로 한 번씩 시도한다. 한 모델이 바쁘면 바로 다음 모델로 넘어가고, 전부 바쁘면 잠깐 쉬었다가 처음부터 다시 돌린다.
    fallbacks = os.environ.get("GEMINI_FALLBACKS", "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash-lite,gemini-3.1-flash-lite")
    models = [MODEL] + [m.strip() for m in fallbacks.split(",") if m.strip() and m.strip() != MODEL]
    # 일반 flash 모델을 먼저(그 안에서는 성공률이 높은 순), lite 모델은 맨 뒤에 둔다. lite는 빠르지만 요약이 얕다.
    models.sort(key=lambda m: (is_lite(m), -model_rate(m)))
    if not allow_lite:
        models = [m for m in models if not is_lite(m)]
    permanent = ("NOT_FOUND", "PERMISSION_DENIED", "INVALID_ARGUMENT", "UNAUTHENTICATED")
    slow = set()  # 이번 영상에서 응답이 멈춘 모델
    last = None
    for rnd in range(3):
        for model in models:
            if model in DEAD or model in slow:
                continue

            def ask(model=model):
                return client.models.generate_content(
                    model=model,
                    contents=(TRANSCRIPT_PROMPT + transcript) if transcript else types.Content(
                        parts=[
                            video_part(types, video_url),
                            types.Part(text=PROMPT),
                        ]
                    ),
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=Summary,
                        temperature=0.2,
                    ),
                )

            wait_s = cfg("TEXT_TIMEOUT_SEC", 120) if transcript else CALL_TIMEOUT  # 자막(글)은 영상보다 훨씬 빨리 끝나야 정상이다
            try:
                print(f"  [{model}] 요청 보냄 (최대 {wait_s}초 기다림)")
                resp = run_with_timeout(ask, wait_s)
                out = json.loads(resp.text)
                STATS.append((model, "ok"))
                print(f"  사용한 모델: {model}")
                return out
            except TimeoutError as e:
                last = e
                slow.add(model)
                STATS.append((model, "busy"))
                print(f"  [{model}] {e} -> 이 영상에서는 다음 모델로 넘어간다")
            except Exception as e:
                last = e
                if FPS_OK[0] and "INVALID_ARGUMENT" in str(e) and os.environ.get("VIDEO_FPS", "0.2") not in ("", "0"):
                    FPS_OK[0] = False  # 프레임 수 설정을 거절했다. 설정 없이 다시 시도한다 (모델을 버리지 않는다)
                    STATS.append((model, "busy"))
                    print(f"  [{model}] 프레임 수 줄이기 설정이 거절돼서 끄고 다시 시도한다: {str(e)[:100]}")
                    continue
                if any(c in str(e) for c in permanent):
                    DEAD.add(model)  # 모델 이름이 없거나 권한이 없다. 이번 실행 동안은 다시 안 쓴다
                    STATS.append((model, "dead"))
                    print(f"  [{model}] 쓸 수 없는 모델: {str(e)[:120]}")
                else:
                    STATS.append((model, "busy"))
                    print(f"  [{model}] 바쁨/오류: {str(e)[:120]}")
                    if "quota" in str(e).lower():
                        slow.add(model)  # 그 모델의 사용 한도를 다 썼다. 이번 영상에서는 다시 묻지 않는다
        if all(m in DEAD or m in slow for m in models):
            break
        if rnd < 2:
            wait = 30 * (rnd + 1)
            print(f"  모든 모델이 바빠서 {wait}초 쉰다 ({rnd + 1}/3)")
            time.sleep(wait)
    raise RuntimeError(f"제미나이 호출 실패(UNAVAILABLE): {last}")


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

    stocks = [[tm(x.get("time")), canon_stock(x.get("name")), (x.get("note") or "").strip()]
              for x in (s.get("stocks") or [])[:7] if (x.get("name") or "").strip()]
    numbers = [[tm(x.get("time")), (x.get("value") or "").strip(), (x.get("note") or "").strip(), canon_label((x.get("label") or "").strip()[:20] or "기타", x.get("value") or "", x.get("note") or "")]
               + ([x["kind"]] if x.get("kind") in ("현재", "전망", "과거") else [])
               for x in (s.get("numbers") or [])[:6] if (x.get("value") or "").strip()]
    tags = [t.strip() for t in (s.get("tags") or []) if t.strip()][:3]

    entry = {"url": vid_url, "channel": channel, "date": date, "title": title}
    if (s.get("people") or "").strip():
        entry["people"] = s["people"].strip()
    entry.update({"conclusion": conclusion, "tags": tags, "parts": parts,
                  "stocks": stocks, "numbers": numbers})
    mood = (s.get("mood") or "").strip()
    if mood in ("낙관", "중립", "비관"):
        entry["mood"] = mood
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
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015", "media": "http://search.yahoo.com/mrss/"}
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
            "desc": " ".join((e.findtext("media:group/media:description", default="", namespaces=NS) or "").split())[:300],
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
            "desc": " ".join((sn.get("description") or "").split())[:300],
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


_WARNED = set()


def warn_once(key, msg):
    if key not in _WARNED:
        _WARNED.add(key)
        print(msg)


def get_info(vid):
    try:
        html = http_get(f"https://www.youtube.com/watch?v={vid}")
    except Exception as e:
        warn_once("http", f"  영상 길이 확인 실패(영상 페이지를 못 읽음): {str(e)[:100]}")
        return {}
    length = 0
    m = re.search(r'"lengthSeconds":\s*"(\d+)"', html)
    if m:
        length = int(m.group(1))
    if not length:
        m = re.search(r'itemprop="duration"\s+content="(PT[^"]+)"', html)
        if m:
            length = parse_iso_duration(m.group(1))
    if not length:
        m = re.search(r'"approxDurationMs":\s*"(\d+)"', html)
        if m:
            length = int(m.group(1)) // 1000
    if not length:
        warn_once("parse", "  영상 길이를 페이지에서 찾지 못했다. (유튜브 화면 구조가 다르거나 접근이 제한됨) 이 경우 영상마다 30분으로 계산한다. 정확하게 하려면 YOUTUBE_API_KEY를 쓰는 편이 좋다.")
    return {"length": length, "live": '"isLive":true' in html, "upcoming": '"isUpcoming":true' in html}


# ---------- 주제 분류: 제목만 보고 경제 관련 영상인지 가려낸다 ----------
TOPIC_PROMPT = """너는 경제·투자 유튜브 채널의 영상을 분류하는 편집자다. 아래 영상들의 제목(과 설명 일부)만 보고, 각 영상이 다음 주제에 해당하는지 판단해라.

해당 주제: 경제(거시경제, 금리, 환율, 물가, 무역), 주식, 투자(코인·채권·펀드 포함), 산업·기업 분석, 부동산, 재테크(저축, 연금, 세금, 대출 등).

참고: 이 채널들은 모두 경제·투자 전문 채널이다. 제목이 "이번엔 진짜 다르다", "지금 당장 확인하세요"처럼 궁금증을 끄는 문구이거나,
사람 이름·인터뷰 형식이라서 경제 단어가 안 보여도 대부분 경제·투자 이야기다. 그런 영상은 해당한다.

규칙
- {rule}
- 정치·외교·안보 이야기라도 제목이나 설명에 환율, 관세, 증시, 산업 영향처럼 경제적 관점이 분명히 드러나면 해당한다.
- 음식, 여행, 건강, 연예, 사회 이슈, 일상, 안보 자체를 다루는 영상은 경제적 관점이 분명하지 않으면 해당하지 않는다.
- reason에는 판단 근거를 한 줄로 쓴다.
- 입력의 id를 그대로 돌려준다. 모든 영상에 대해 답한다.

영상 목록(JSON):
"""


def call_gemini_text(prompt):
    from google import genai
    from google.genai import types
    from pydantic import BaseModel

    class Verdict(BaseModel):
        id: str
        related: bool
        reason: str

    class Verdicts(BaseModel):
        items: list[Verdict]

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    models = [m.strip() for m in os.environ.get("TOPIC_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash").split(",") if m.strip()]
    last = None
    for rnd in range(2):
        for model in models:
            if model in DEAD:
                continue
            try:
                resp = run_with_timeout(
                    lambda m=model: client.models.generate_content(
                        model=m, contents=prompt,
                        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=Verdicts, temperature=0)),
                    90)
                return json.loads(resp.text)
            except Exception as e:
                last = e
                if any(c in str(e) for c in ("NOT_FOUND", "PERMISSION_DENIED", "INVALID_ARGUMENT", "UNAUTHENTICATED")):
                    DEAD.add(model)
        if rnd == 0:
            time.sleep(20)
    raise RuntimeError(f"주제 분류 호출 실패: {str(last)[:150]}")


def classify(items):
    """{영상id: (경제 관련 여부, 이유)}를 돌려준다. 호출이 실패하면 None."""
    strict = cfg("TOPIC_STRICT", 1)
    rule = ("경제·투자 이야기가 중심일 것으로 보이면 related=true로 한다. 제목이 궁금증을 끄는 문구라서 주제를 알 수 없을 때도 true로 한다. 대신 교육·입시, 사회 사건·사고, 건강·의료, 재난, 연예, 일상, 경제 얘기가 없는 정치·안보·역사처럼 경제가 아닌 주제가 제목에 드러나면 경제 채널 영상이어도 false로 한다." if strict
            else "분명히 해당하지 않을 때만 false로 한다. 애매하면 true로 한다.")
    payload = [{"id": e["id"], "channel": e["channel"], "title": e["title"], "description": e.get("desc", "")} for e in items]
    try:
        data = call_gemini_text(TOPIC_PROMPT.replace("{rule}", rule) + json.dumps(payload, ensure_ascii=False))
    except Exception as ex:
        print(f"  {ex}")
        return None
    return {str(i.get("id")): (bool(i.get("related")), str(i.get("reason", ""))[:80]) for i in data.get("items", [])}


# 같은 종목을 다르게 부르는 이름들. 왼쪽이 사이트에 쓸 이름, 오른쪽이 같은 종목으로 볼 다른 이름이다.
# 새로 발견하면 여기에 한 줄 추가하면 된다.
STOCK_ALIAS = {
    "SK하이닉스": ["하이닉스", "SK하닉", "하닉", "SK hynix", "Hynix"],
    "삼성전자": ["삼전", "Samsung Electronics", "삼성전자우"],
    "엔비디아": ["NVIDIA", "엔비디아(NVIDIA)", "NVDA"],
    "테슬라": ["Tesla", "TSLA"],
    "애플": ["Apple", "AAPL"],
    "마이크로소프트": ["Microsoft", "MS", "MSFT"],
    "구글": ["알파벳", "Alphabet", "Google", "GOOGL"],
    "메타": ["Meta", "메타플랫폼스", "페이스북"],
    "아마존": ["Amazon", "AMZN"],
    "TSMC": ["대만반도체", "타이완반도체", "TSMC(대만)"],
    "브로드컴": ["Broadcom", "AVGO"],
    "마이크론": ["Micron", "마이크론테크놀로지"],
    "팔란티어": ["Palantir", "PLTR"],
    "코어위브": ["CoreWeave"],
    "오라클": ["Oracle"],
    "넷플릭스": ["Netflix"],
    "AMD": ["에이엠디"],
    "현대차": ["현대자동차"],
    "기아": ["기아차"],
    "LG에너지솔루션": ["LG엔솔", "엔솔"],
    "삼성바이오로직스": ["삼성바이오", "삼바"],
    "한화에어로스페이스": ["한화에어로"],
    "네이버": ["NAVER"],
    "POSCO홀딩스": ["포스코홀딩스", "포스코"],
}
_ALIAS_KEY = {}


def _key(n):
    return re.sub(r"[\s·・\-_.()（）]", "", n or "").upper()


# ---------- 숫자 지표 이름 통일 ----------
# 같은 지표가 영상마다 다른 이름으로 붙는 걸 막는다. 프롬프트에도 이 목록을 준다.



def canon_label(label, value="", note=""):
    """지표 이름을 NUM_LABELS 기준으로 맞춘다. 맞출 수 없으면 원래 이름을 그대로 둔다."""
    lab = re.sub(r"\s+", " ", (label or "").strip()) or "기타"
    val = value or ""
    t = lab + " " + (note or "")
    money = bool(re.search(r"[조억만천]\s*원|억\s*달러|원$", val))
    if re.fullmatch(r"\s*\d{4}\s*년(도)?\s*", val):
        return "기타"
    if lab in NUM_LABELS:
        base = lab
    else:
        base = None
    # 투자 주체별 매매: 이름에 들어 있거나, 금액 숫자인데 설명이 매도·매수 얘기면
    if re.search(r"코드", lab):
        return "기타"
    def flow(who):
        # 순매도와 순매수는 정반대 얘기라 따로 둔다. 이름 → 값의 부호 → 설명 순으로 판단
        lb = lab.replace("매매", "")
        if re.search(r"매수", lb) and not re.search(r"매도", lb):
            return f"{who} 순매수"
        if re.search(r"매도", lb) and not re.search(r"매수", lb):
            return f"{who} 순매도"
        if re.match(r"\s*-", val):
            return f"{who} 순매도"
        # 설명 문장에서 마지막에 나오는 매도/매수 표현을 본다 (한국어는 주된 동사가 문장 끝에 온다)
        acts = re.findall(r"순매도|매도|팔았|팔고|순매수|매수|사들", note or "")
        if acts:
            return f"{who} 순매도" if acts[-1] in ("순매도", "매도", "팔았", "팔고") else f"{who} 순매수"
        return f"{who} 매매"
    for who in ("외국인", "기관", "개인"):
        if who in lab and re.search(r"매도|매수|매매|순매", lab + (note or "")):
            return flow(who)
    if money and not re.search(r"외국인|기관|개인|신용|예탁|시가총액", lab):
        for who in ("외국인", "기관", "개인"):
            if re.search(who + r"[^.]{0,12}(순매도|순매수|매도한|매수한|매도 금액|매수 금액)", note or ""):
                return flow(who)
    if base == "미국 국채 금리":
        if re.search(r"10\s*년", note or ""):
            return "미국 10년물 국채 금리"
        if re.search(r"2\s*년", note or ""):
            return "미국 2년물 국채 금리"
    if base:
        if base.endswith("가격") and not re.search(r"달러|원|\$|불", val):
            return "기타"
        return base
    rules = [
        (r"신용\s*(잔고|융자)|신용잔고", "신용잔고"), (r"반대매매", "반대매매"), (r"예탁금", "고객예탁금"),
        (r"(한국|국고채).*(금리|국채)|국고채", "한국 국고채 금리"),
        (r"2년(물|만기)?.*(국채|금리|수익률)", "미국 2년물 국채 금리"),
        (r"10년(물|만기)?.*(국채|금리|수익률)|(국채|금리|수익률).*10년", "미국 10년물 국채 금리"),
        (r"^미국 국채 금리$", "미국 국채 금리"),
        (r"국채.*(금리|수익률)|채권\s*금리", "미국 국채 금리"),
        (r"(한국|한은).*기준\s*금리", "한국 기준금리"), (r"기준\s*금리|정책\s*금리|FOMC|연준.*금리", "미국 기준금리"),
        (r"달러\s*인덱스", "달러 인덱스"), (r"엔.*(환율|달러)|달러.*엔", "엔/달러 환율"), (r"환율|원/달러|원·달러|원달러", "원/달러 환율"),
        (r"필라델피아|SOX", "필라델피아 반도체 지수"), (r"코스피", "코스피 지수"), (r"코스닥", "코스닥 지수"),
        (r"나스닥", "나스닥 지수"), (r"S&P|에스앤피", "S&P500 지수"), (r"다우", "다우 지수"), (r"닛케이", "닛케이 지수"),
        (r"비트코인", "비트코인 가격"), (r"금\s*(가격|값|시세)|금값", "금 가격"), (r"유가|WTI|브렌트|원유", "국제유가"),
        (r"CPI|PCE|PPI|소비자\s*물가|생산자\s*물가|물가|인플레", "물가"), (r"고용|비농업|실업", "고용 지표"), (r"GDP|성장률", "GDP 성장률"),
        (r"PER|PBR|밸류에이션", "PER·PBR"), (r"목표\s*(주가|가)", "목표 주가"), (r"시가\s*총액|시총", "시가총액"),
        (r"수출", "수출"),
    ]
    for pat, name in rules:
        if re.search(pat, lab):
            if name == "미국 국채 금리" and re.search(r"10\s*년", note or ""):
                return "미국 10년물 국채 금리"
            if name.endswith("가격") and not re.search(r"달러|원|\$|불", val):
                return "기타"
            if name.endswith("지수") and money:
                break  # 지수 이름이 붙었지만 금액이면 지수 값이 아니다
            return name
    if re.search(r"실적|영업이익|매출|순이익|EPS", lab):
        if re.search(r"%", val) and re.search(r"주가.*(급등|급락|상승|하락|등락)", note or ""):
            return "주가 등락률"
        return "기업 실적"
    if re.search(r"등락률|상승률|하락률|급등|급락", lab):
        return "주가 등락률"
    return lab


def canon_numbers(videos):
    """저장된 영상들의 숫자 지표 이름을 통일한다. 바뀐 개수를 돌려준다."""
    n = 0
    for v in videos:
        for row in v.get("numbers") or []:
            if len(row) >= 4:
                c = canon_label(row[3], row[1], row[2])
                if c != row[3]:
                    row[3], n = c, n + 1
    return n


def canon_stock(n):
    """종목 이름을 사이트에서 쓰는 정식 이름으로 바꾼다."""
    if not _ALIAS_KEY:
        for main_name, others in STOCK_ALIAS.items():
            for o in [main_name] + others:
                _ALIAS_KEY[_key(o)] = main_name
    n = (n or "").strip()
    base = re.sub(r"\s*[(（][^)）]*[)）]\s*", "", n).strip() or n  # 괄호 속 덧붙인 이름은 뗀다
    return _ALIAS_KEY.get(_key(n)) or _ALIAS_KEY.get(_key(base)) or n


def norm_name(n):
    """종목 이름을 비교하기 쉽게 정리한다. (별칭을 정식 이름으로 바꾸고, 공백과 기호를 없애고 대문자로)"""
    return _key(canon_stock(n))


def canon_all(videos):
    """저장된 영상들의 종목 이름을 정식 이름으로 맞춘다. 바뀐 개수를 돌려준다."""
    n = 0
    for v in videos:
        for row in v.get("stocks") or []:
            if len(row) >= 2:
                c = canon_stock(row[1])
                if c != row[1]:
                    row[1], n = c, n + 1
    return n


# ---------- 직접 쓰는 한마디 코멘트 (notes.js) ----------
NOTES = ROOT / "notes.js"


def load_notes():
    try:
        return _read_const(NOTES.read_text(encoding="utf-8"), "NOTES") or {}
    except Exception:
        return {}


def save_notes(n):
    NOTES.write_text("/* 직접 쓰는 한마디 코멘트. 키: 날짜(일간), week:월요일날짜(주간), 영상ID. 자동화로 바꾸거나 직접 고칠 수 있다. */\nconst NOTES=" +
                     json.dumps(n, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")


def week_start(date_str):
    d = datetime.date.fromisoformat(date_str)
    return d - datetime.timedelta(days=d.weekday())  # 그 주의 월요일


def norm_note_key(k):
    k = (k or "").strip()
    today = datetime.datetime.now(KST).date()
    if k in ("오늘", "today"):
        return today.isoformat()
    if k in ("어제", "yesterday"):
        return (today - datetime.timedelta(days=1)).isoformat()
    if k in ("주간", "이번주", "week"):  # 날짜 없이 '주간'만 쓰면 가장 최근 주간 브리핑(없으면 이번 주)에 단다
        weekly = load_weekly()
        return "week:" + (weekly[0]["week"] if weekly else week_start(today.isoformat()).isoformat())
    m = re.fullmatch(r"(?:주간|week)[: ]?(\d{4}-\d{2}-\d{2})", k)
    if m:
        return "week:" + week_start(m.group(1)).isoformat()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", k):
        return k
    return video_id(k) or (k if re.fullmatch(r"[A-Za-z0-9_-]{11}", k) else None)


def set_note(key, text):
    k = norm_note_key(key)
    if not k:
        print(f"코멘트를 달 대상을 알 수 없다: '{key}'. note_key 칸에는 날짜(2026-11-14), 오늘, 주간(가장 최근 주), 주간:날짜, 영상 주소 중 하나를 쓴다.")
        print("(주간 브리핑을 '만들려면' note_key가 아니라 첫 번째 칸(urls)에 주간 이라고 쓴다.)")
        return 1
    notes = load_notes()
    text = (text or "").strip()
    if text:
        notes[k] = text
        print(f"코멘트를 저장했다: {k} -> {text[:60]}")
    elif k in notes:
        del notes[k]
        print(f"코멘트를 지웠다: {k}")
    else:
        print("지울 코멘트가 없다.")
    save_notes(notes)
    return 0


# ---------- 종합 브리핑: 그날의 영상 요약들을 모아 교차 분석 ----------
BRIEFS = ROOT / "briefs.js"
BRIEF_PROMPT = """너는 한국 경제 유튜브 영상들의 요약을 종합하는 편집자다. 아래 영상 요약들을 읽고 하루치 종합 브리핑을 JSON으로 만들어라.

규칙
- 문장은 짧게 쓴다. 한 문장에 정보를 여러 개 이어 붙이지 않는다.
- 아래 영상 요약에 있는 내용만 쓴다. 네가 아는 정보로 사실 여부를 판단하거나 내용을 보태지 않는다.
- 전망이나 의견은 '~라고 본다', '~라고 주장한다'처럼 출연자의 말이라는 것이 드러나게 쓴다. 특정 종목을 사거나 팔라고 권하는 표현은 쓰지 않는다.
- 문체는 모두 '~다'로 통일한다. 숫자는 영상에서 말한 단위와 기준 그대로 쓰고, 단위가 불명확하면 '(단위 불명확)'을 붙인다.
- refs와 ref에는 근거가 된 영상 번호(입력의 n)를 넣는다. 입력에 있는 번호만 쓴다.
- headline: 오늘 영상들을 관통하는 시장 분위기를 공백 포함 45자 안팎의 짧은 한 문장으로 쓴다.
- keypoints: 오늘의 핵심 3~4줄. 각 줄은 공백 포함 40자 안팎의 짧은 문장 하나이고, 정보를 하나씩만 담는다.
- themes: 핵심 주제 2~4개. title은 공백 포함 25자 이내로 짧게, summary는 공백 포함 90자 이내의 한두 문장으로 쓴다.
- agreements: 둘 이상의 영상이 공통으로 말한 것 2~4개. point는 공백 포함 45자 안팎의 한 문장, refs는 2개 이상.
- disagreements: 영상마다 의견이 엇갈린 주제 0~3개. 없으면 빈 목록. 가장 크게 엇갈리고 투자 판단에 중요한 주제를 맨 앞에 둔다. topic은 짧게, views의 각 view는 공백 포함 45자 안팎의 한 문장(각각 view, ref).
- stocks: 둘 이상의 영상에서 언급된 종목 최대 8개. name과 mentions(각각 view: 그 영상에서의 평가나 맥락을 공백 포함 45자 안팎의 한 문장으로, ref). 한 영상에서만 나온 종목은 넣지 않는다. tone에는 이날 영상들의 전반적인 시각을 긍정, 부정, 혼재, 중립 중 하나로 쓴다.

영상 요약(JSON):
"""


def call_json(prompt, make_schema, models_env, default_models, timeout):
    from google import genai
    from google.genai import types

    schema = make_schema()
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    models = [m.strip() for m in os.environ.get(models_env, default_models).split(",") if m.strip()]
    last = None  # 모델은 정해 준 순서대로 쓴다 (글 정리 작업은 lite를 먼저, 브리핑은 좋은 모델을 먼저)
    for rnd in range(2):
        for model in models:
            if model in DEAD:
                continue
            try:
                resp = run_with_timeout(
                    lambda m=model: client.models.generate_content(
                        model=m, contents=prompt,
                        config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.3)),
                    timeout)
                print(f"  사용한 모델: {model}")
                return json.loads(resp.text)
            except Exception as e:
                last = e
                if any(c in str(e) for c in ("NOT_FOUND", "PERMISSION_DENIED", "INVALID_ARGUMENT", "UNAUTHENTICATED")):
                    DEAD.add(model)
        if rnd == 0:
            time.sleep(20)
    raise RuntimeError(f"호출 실패: {str(last)[:150]}")


def brief_schema():
    from pydantic import BaseModel

    class Theme(BaseModel):
        title: str
        summary: str
        refs: list[int]

    class Agree(BaseModel):
        point: str
        refs: list[int]

    class View(BaseModel):
        view: str
        ref: int

    class Disagree(BaseModel):
        topic: str
        views: list[View]

    class StockB(BaseModel):
        name: str
        tone: str
        mentions: list[View]

    class Brief(BaseModel):
        headline: str
        keypoints: list[str]
        themes: list[Theme]
        agreements: list[Agree]
        disagreements: list[Disagree]
        stocks: list[StockB]

    return Brief


def build_brief(date, vids):
    payload = []
    for n, v in enumerate(vids):
        payload.append({
            "n": n, "channel": v["channel"], "title": v["title"], "conclusion": v["conclusion"],
            "points": [x[1] for p in v.get("parts", []) for x in p["items"]],
            "stocks": [[x[1], x[2]] for x in v.get("stocks", [])],
            "numbers": [[x[1], x[2]] for x in v.get("numbers", [])],
        })
    data = call_json(BRIEF_PROMPT + json.dumps(payload, ensure_ascii=False), brief_schema,
                     "BRIEF_MODELS", "gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash-lite", 240)
    ids = [video_id(v["url"]) for v in vids]
    chans = [v["channel"] for v in vids]

    def ok(r):
        return isinstance(r, int) and 0 <= r < len(ids)

    def refs(rs):
        return [ids[r] for r in dict.fromkeys(rs or []) if ok(r)]

    def txt(x):
        return (x or "").strip()

    themes = [{"title": txt(t.get("title")), "summary": txt(t.get("summary")), "refs": refs(t.get("refs"))}
              for t in data.get("themes") or [] if txt(t.get("title")) and txt(t.get("summary"))]
    agreements = [{"point": txt(a.get("point")), "refs": refs(a.get("refs"))}
                  for a in data.get("agreements") or [] if txt(a.get("point")) and len(refs(a.get("refs"))) >= 2]
    disagreements = []
    for d in data.get("disagreements") or []:
        views = [{"channel": chans[v["ref"]], "view": txt(v.get("view")), "ref": ids[v["ref"]]}
                 for v in d.get("views") or [] if ok(v.get("ref")) and txt(v.get("view"))]
        if txt(d.get("topic")) and len({v["ref"] for v in views}) >= 2:
            disagreements.append({"topic": txt(d["topic"]), "views": views})
    stocks = []
    for s_ in data.get("stocks") or []:
        ms = [{"channel": chans[m["ref"]], "view": txt(m.get("view")), "ref": ids[m["ref"]]}
              for m in s_.get("mentions") or [] if ok(m.get("ref")) and txt(m.get("view"))]
        if txt(s_.get("name")) and len({m["ref"] for m in ms}) >= 2:
            tone = s_.get("tone") if s_.get("tone") in ("긍정", "부정", "혼재", "중립") else ""
            stocks.append({"name": canon_stock(txt(s_["name"])), "count": len({m["ref"] for m in ms}), "tone": tone, "mentions": ms})
    stocks.sort(key=lambda x: -x["count"])
    kp = [txt(x) for x in data.get("keypoints") or [] if txt(x)][:4]
    if not txt(data.get("headline")) or not kp or not themes:
        raise ValueError("브리핑에 헤드라인, 핵심 줄, 주제가 비어 있다")
    return {"date": date, "count": len(vids), "sources": ids, "headline": txt(data["headline"]),
            "keypoints": kp, "themes": themes, "agreements": agreements,
            "disagreements": disagreements, "stocks": stocks}


def _read_const(text, name):
    i = text.find(f"const {name}=")
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(text[i + len(f"const {name}="):].lstrip())[0]
    except Exception:
        return None


def _load_briefs_file():
    try:
        t = BRIEFS.read_text(encoding="utf-8")
    except Exception:
        return [], []
    return (_read_const(t, "BRIEFS") or []), (_read_const(t, "WEEKLY") or [])


def _save_briefs_file(briefs, weekly):
    BRIEFS.write_text("/* 종합 브리핑(일간 BRIEFS, 주간 WEEKLY). 자동화(scripts/summarize.py)가 갱신하는 파일이다. */\nconst BRIEFS=" +
                      json.dumps(briefs, ensure_ascii=False, indent=1) + ";\nconst WEEKLY=" +
                      json.dumps(weekly, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")


# ---------- 스레드 글 초안을 텔레그램으로 받기 (운영자 전용) ----------
# 정해진 시간대의 첫 실행에서 한 번만 보낸다. TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID 비밀값이 없으면 아무것도 하지 않는다.
SITE_URL_ = os.environ.get("SITE_URL", "https://marketraven.kr").rstrip("/")

THREADS_PROMPT = """너는 스레드(Threads)에 올릴 짧은 글을 쓰는 개인 투자자다. 아래 자료는 여러 경제 유튜브 영상을 요약·종합한 것이다.
이 자료로 스레드 본문 1개와 첫 댓글 1개를 JSON으로 써라.

목적: {goal}

말투
- 커뮤니티에 혼자 정리해서 올리는 듯한 편한 '~이다', '~했다' 체. 독백 느낌으로, 존댓말과 '~함/~임' 체는 쓰지 않는다.
- '국장', '줍줍', '던지다', '버티다'처럼 투자 커뮤니티에서 흔히 쓰는 말은 자연스럽게 써도 된다. 다만 과하게 쓰지 않는다.
- 광고 문구, 과장, 이모지, 해시태그, 'ㅋㅋ' 금지. AI가 쓴 티가 나는 표현(예: '주목할 만하다', '시사점', '~할 것으로 보인다') 금지.

구성
- 첫 줄: "오늘 경제 유튜브 N개를 다 돌려봤다."처럼 몇 개를 봤는지로 시작한다.
- 이어서 다들 공통으로 꼽은 이유나 시각 1~2개, 숫자 하나(지수, 금액 등).
- 엇갈린 시각이 있으면 "한쪽은 ~하라고 하고, 다른 쪽은 ~라고 한다." 식으로 하나 넣는다. 채널 이름은 쓰지 않는다.
- 끝에서 두 번째 줄은 어느 편도 들지 않는 짧은 개인 소감 한 줄(예: "솔직히 둘 다 맞는 말 같다.").
- 마지막 줄은 다른 사람들 생각이 궁금하다는 한 줄(예: "다들 지금 추매하는 쪽인지, 좀 더 지켜보는 쪽인지 궁금하다.").
- 짧은 줄로 끊고 문단 사이는 빈 줄 하나. 본문은 공백 포함 350자 이내.
- 특정 종목을 사거나 팔라고 권하는 말은 쓰지 않는다. 유튜버들이 이렇게 봤다는 전달자 입장을 지킨다.

예시(말투만 참고하고 내용은 자료대로 쓴다)
오늘 경제 유튜브 16개를 다 돌려봤다.

다들 범인으로 앤트로픽 상장을 꼽았다.
거기로 돈이 확 쏠리면서 기술주랑 국장에서 수급이 빠졌다는 얘기다.

코스피는 외국인이 던지면서 4,800 근처까지 밀렸다.

근데 그래서 지금 뭘 해야 하냐에서는 완전히 갈렸다.

한쪽은 이 정도 빠졌으면 나눠서 줍줍하라고 하고,
다른 쪽은 규제 이슈가 남아서 더 빠질 수 있으니 현금 들고 버티라고 한다.

솔직히 둘 다 맞는 말 같다.
다들 지금 추매하는 쪽인지, 좀 더 지켜보는 쪽인지 궁금하다.

comment(첫 댓글)는 한 줄: 누가 어떤 근거로 그렇게 봤는지 사이트에 정리해 뒀다는 말과 함께 끝에 이 주소를 그대로 붙인다: {link}
image_title은 공유 이미지에 크게 넣을 한 줄 요약이다. 40자 이내, '~했다' 체 한 문장.

자료(JSON):
"""


def threads_schema():
    from pydantic import BaseModel

    class Post(BaseModel):
        post: str
        comment: str
        image_title: str  # 공유 이미지에 크게 들어갈 한 줄 (40자 이내)
    return Post


def tg_ok():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def tg_photo(path, caption="", chat=None, html=False):
    """사진 파일을 텔레그램으로 보낸다 (multipart 업로드). chat을 안 주면 운영자에게 보낸다."""
    import urllib.request
    import uuid
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), chat or os.environ.get("TELEGRAM_CHAT_ID", "")
    bd = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", chat), ("caption", caption[:1024])) + ((("parse_mode", "HTML"),) if html else ()):
        parts.append(f"--{bd}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    parts.append(f"--{bd}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"image.png\"\r\nContent-Type: image/png\r\n\r\n".encode()
                 + Path(path).read_bytes() + f"\r\n--{bd}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{tok}/sendPhoto", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={bd}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode()).get("ok")


def tg_alert(state, key, text):
    """운영 알림. 같은 key는 한 번만 보낸다."""
    if not tg_ok():
        return
    al = state.setdefault("alerts", {})
    if al.get(key):
        return
    try:
        if tg_send("[Market Raven 알림]\n" + text):
            al[key] = True
            for k in sorted(al)[:-60]:
                al.pop(k, None)
    except Exception as e:
        print(f"알림 보내기 실패: {str(e)[:100]}")


def tg_send(text, chat=None, html=False):
    import urllib.request
    import urllib.parse
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN", ""), chat or os.environ.get("TELEGRAM_CHAT_ID", "")
    q = {"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "false"}
    if html:
        q["parse_mode"] = "HTML"
    data = urllib.parse.urlencode(q).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=20) as r:
        return json.loads(r.read().decode()).get("ok")


def threads_draft(state, videos, force=""):
    if not tg_ok():
        return
    now = datetime.datetime.now(KST)
    today, wd, h = now.date().isoformat(), now.weekday(), now.hour
    slot = force or ("am" if wd < 5 and 10 <= h < 14 else "pm" if wd < 5 and 16 <= h < 21 else
                     "sat" if wd == 5 and 18 <= h < 23 else "sun" if wd == 6 and 18 <= h < 23 else "")
    if not slot:
        return
    sent = state.setdefault("threads", {})
    key = f"{today}-{slot}"
    if sent.get(key) and not force:
        return
    vids = lambda days: [v for v in videos if (v.get("date") or "") >= (now.date() - datetime.timedelta(days=days)).isoformat()]
    slim = lambda vs: [{"채널": v.get("channel"), "제목": v.get("title"), "결론": v.get("conclusion"), "분위기": v.get("mood")} for v in vs[:14]]
    briefs = {b["date"]: b for b in load_briefs()}
    if slot == "am":
        src = [v for v in videos if v.get("date") == today]
        if len(src) < 2:
            print("스레드 초안: 오늘 오전 영상이 아직 적어서 이번엔 건너뛴다")
            return
        goal, link, data = (f"오늘 오전까지 올라온 경제 유튜브 {len(src)}편이 오늘 장을 어떻게 봤는지 전한다.", SITE_URL_ + "/", slim(src))
    elif slot == "pm":
        b = briefs.get(today)
        if not b:
            print("스레드 초안: 오늘 브리핑이 아직 없어서 이번엔 건너뛴다")
            return
        goal, link = (f"오늘 장 마감 후, 경제 유튜브 {b.get('count')}편을 종합한 오늘의 시장 브리핑을 전한다.", f"{SITE_URL_}/brief/{today}/")
        data = {k: b.get(k) for k in ("headline", "keypoints", "agreements", "disagreements", "count")}
        data["stocks"] = [{"name": s.get("name"), "count": s.get("count"), "tone": s.get("tone")} for s in (b.get("stocks") or [])[:5]]
    elif slot == "sat":
        ws = week_start(today).isoformat()
        w = next((x for x in load_weekly() if x.get("week") == ws), None)
        if w:
            goal, link = ("이번 주 경제 유튜브들이 반복해서 말한 주제와 많이 언급한 종목을 한 주 결산으로 전한다.", f"{SITE_URL_}/week/{ws}/")
            data = {k: w.get(k) for k in ("headline", "keypoints", "recurring", "stocks", "videos")}
        else:
            days = sorted(d for d in briefs if d >= ws)
            if not days:
                return
            goal, link = ("이번 주 경제 유튜브들이 반복해서 말한 주제를 한 주 결산으로 전한다.", f"{SITE_URL_}/brief/")
            data = [{k: briefs[d].get(k) for k in ("date", "headline", "keypoints")} for d in days]
    else:
        src = vids(1)
        if len(src) < 2:
            return
        goal, link, data = ("주말에 올라온 경제 유튜브들이 꼽은 다음 주 관전 포인트(일정, 변수, 걱정거리)를 전한다.", SITE_URL_ + "/", slim(src))
    try:
        out = call_json(THREADS_PROMPT.replace("{goal}", goal).replace("{link}", link) + json.dumps(data, ensure_ascii=False),
                        threads_schema, "THREADS_MODELS", "gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash-lite", 90)
    except Exception as e:
        print(f"스레드 초안 만들기 실패: {str(e)[:120]}")
        return
    out, _ = fix_names(out)
    label = {"am": "평일 오전", "pm": "평일 저녁", "sat": "토요일", "sun": "일요일"}[slot]
    # 공유 이미지: 사이트 브리핑 이미지와 같은 모양으로 만들어 사진으로 보낸다
    img = None
    try:
        import importlib.util
        sp = importlib.util.spec_from_file_location("pages_for_og", ROOT / "scripts" / "pages.py")
        pg = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(pg)
        d_ = now.date()
        kick = {"am": f"{d_.month}.{d_.day:02d} ({'월화수목금토일'[d_.weekday()]}) 오전 시황", "pm": f"{d_.month}.{d_.day:02d} ({'월화수목금토일'[d_.weekday()]}) 시장 브리핑",
                "sat": "이번 주 시장 결산", "sun": "다음 주 관전 포인트"}[slot]
        head_ = (briefs.get(today) or {}).get("headline") if slot == "pm" else ""
        head_ = fix_names(head_ or out.get("image_title") or "")[0]
        n_ = (briefs.get(today) or {}).get("count") if slot == "pm" else (len(data) if isinstance(data, list) else "")
        if pg.og_image(f"tg-{slot}", kick, head_, f"경제 유튜브 영상 {n_}편 종합" if n_ else "경제 유튜브 종합"):
            img = ROOT / "og" / f"tg-{slot}.png"
    except Exception as e:
        print(f"공유 이미지 만들기 실패(글만 보낸다): {str(e)[:100]}")
    msg = f"[스레드 초안 · {label} · {today}]\n\n{(out.get('post') or '').strip()}\n\n──── 첫 댓글 ────\n{(out.get('comment') or '').strip()}"
    try:
        if img and img.exists():
            tg_photo(img, f"{label} 공유 이미지")
        if tg_send(msg):
            sent[key] = True
            for k in sorted(sent)[:-40]:
                sent.pop(k, None)
            print(f"스레드 초안을 텔레그램으로 보냈다 ({label})")
    except Exception as e:
        print(f"텔레그램 보내기 실패: {str(e)[:120]}")


# ---------- 표기 사전: AI가 자주 틀리게 쓰는 회사·인물 이름을 바로잡는다 ----------
# 영상 제목과 채널 이름은 원본이라 건드리지 않고, 요약·브리핑·종목 종합 글만 고친다. 새로 틀리는 이름이 보이면 여기에 한 줄 추가하면 된다.
NAME_FIX = [("엔트로픽", "앤트로픽"), ("앤비디아", "엔비디아"), ("엔비디어", "엔비디아"), ("팔란티아", "팔란티어"), ("팔란디어", "팔란티어"),
            ("브로드캄", "브로드컴"), ("오픈 AI", "오픈AI"), ("오픈에이아이", "오픈AI"), ("SK 하이닉스", "SK하이닉스"), ("에스케이하이닉스", "SK하이닉스"),
            ("코어 위브", "코어위브"), ("마이크로 소프트", "마이크로소프트"), ("테슬러", "테슬라"), ("슈퍼 마이크로", "슈퍼마이크로")]
_FIX_SKIP = {"title", "channel", "url", "id", "ts", "date", "model", "src", "ref", "refs", "sources", "week", "end", "updated"}


def fix_names(o):
    """o 안의 글을 표기 사전대로 고친다. (고친 결과, 바뀐 곳 수)"""
    if isinstance(o, str):
        s = o
        for a, b in NAME_FIX:
            if a in s:
                s = s.replace(a, b)
        return s, int(s != o)
    if isinstance(o, list):
        n, out = 0, []
        for x in o:
            y, k = fix_names(x)
            out.append(y)
            n += k
        return out, n
    if isinstance(o, dict):
        n, out = 0, {}
        for key, x in o.items():
            if key in _FIX_SKIP:
                out[key] = x
                continue
            out[key], k = fix_names(x)
            n += k
        return out, n
    return o, 0


def fix_all(videos):
    """저장된 요약·브리핑·종목 종합의 이름 표기를 고친다."""
    total = 0
    for i, v in enumerate(videos):
        videos[i], k = fix_names(v)
        total += k
    if total:
        save(videos)
    b, w = _load_briefs_file()
    (b2, w2), k = fix_names([b, w])
    if k:
        _save_briefs_file(b2, w2)
        total += k
    d, k = fix_names(load_stock_digests())
    if k:
        save_stock_digests(d)
        total += k
    if total:
        print(f"이름 표기를 바로잡았다: {total}곳 (예: 엔트로픽 -> 앤트로픽)")
    return total


# ---------- 공개 텔레그램 채널에 브리핑 올리기 (구독자용) ----------
# 평일 오전(11시대): 오전 영상들의 한 줄 결론 모음, 평일 저녁(17시대): 그날 일간 브리핑, 토요일 저녁: 주간 브리핑.
# TELEGRAM_CHANNEL(예: @marketraven)이 없으면 하지 않는다.
def channel_post(state, force="", videos=None):
    ch = os.environ.get("TELEGRAM_CHANNEL", "").strip()
    if not (ch and os.environ.get("TELEGRAM_BOT_TOKEN")):
        return
    import html as H
    now = datetime.datetime.now(KST)
    today, wd, h = now.date().isoformat(), now.weekday(), now.hour
    slot = force or ("am" if wd < 5 and 10 <= h < 14 else "pm" if wd < 5 and 16 <= h < 23 else "sat" if wd == 5 and 18 <= h < 23 else "")
    if not slot:
        return
    done_ = state.setdefault("channel", {})
    key = f"{today}-{slot}"
    if done_.get(key) and not force:
        return
    E = lambda s: H.escape(str(s or ""))
    d_ = now.date()
    if slot == "am":
        vs = [v for v in (videos if videos is not None else load()) if v.get("date") == today and v.get("conclusion")]
        if len(vs) < 3:
            print("채널: 오늘 오전 영상이 아직 적어서 이번엔 올리지 않는다")
            return
        vs, _ = fix_names(vs)
        mood = {"낙관": "긍정", "중립": "중립", "비관": "부정"}
        cnt = {k: sum(1 for v in vs if v.get("mood") == k) for k in mood}
        kick = f"{d_.month}.{d_.day:02d} ({'월화수목금토일'[d_.weekday()]}) 오전 시황"
        head = f"오전 경제 유튜브 {len(vs)}편, 긍정 {cnt['낙관']} · 중립 {cnt['중립']} · 부정 {cnt['비관']}"
        link, n = f"{SITE_URL_}/", len(vs)
        lines = [f"<b>{E(kick)}</b>", f"<b>{E(head)}</b>", ""]
        for v in vs[:6]:
            lines += [f"<b>{E(v.get('channel'))}</b> · {E(mood.get(v.get('mood'), ''))}", f"{E(v.get('conclusion'))}", ""]
        lines = lines[:-1]
    elif slot == "pm":
        b = next((x for x in load_briefs() if x.get("date") == today), None)
        if not b:
            print("채널: 오늘 브리핑이 아직 없어서 이번엔 올리지 않는다")
            return
        b, _ = fix_names(b)
        kick = f"{d_.month}.{d_.day:02d} ({'월화수목금토일'[d_.weekday()]}) 시장 브리핑"
        link, head, n = f"{SITE_URL_}/brief/{today}/", b.get("headline") or "", b.get("count") or ""
        lines = [f"<b>{E(kick)}</b>", f"<b>{E(head)}</b>", ""] + [f"• {E(k)}" for k in (b.get("keypoints") or [])[:4]]
        dis = (b.get("disagreements") or [])[:1]
        if dis and len(dis[0].get("views") or []) >= 2:
            v1, v2 = dis[0]["views"][:2]
            lines += ["", f"<b>엇갈린 시각</b> · {E(dis[0].get('topic'))}", f"- {E(v1.get('view'))}", f"- {E(v2.get('view'))}"]
        st = [s.get("name") for s in (b.get("stocks") or [])[:5] if s.get("name")]
        if st:
            lines += ["", f"<b>많이 언급된 종목</b> {E(', '.join(st))}"]
    else:
        ws = week_start(today).isoformat()
        w = next((x for x in load_weekly() if x.get("week") == ws), None)
        if not w:
            print("채널: 이번 주 주간 브리핑이 아직 없어서 올리지 않는다")
            return
        w, _ = fix_names(w)
        a_, z_ = datetime.date.fromisoformat(ws), datetime.date.fromisoformat(w.get("end") or today)
        kick = f"{a_.month}.{a_.day:02d}~{z_.month}.{z_.day:02d} 주간 시장 브리핑"
        link, head, n = f"{SITE_URL_}/week/{ws}/", w.get("headline") or "", w.get("videos") or ""
        lines = [f"<b>{E(kick)}</b>", f"<b>{E(head)}</b>", ""] + [f"• {E(k)}" for k in (w.get("keypoints") or [])[:5]]
    lines += ["", f"경제 유튜브 영상 {E(n)}편 종합", f'<a href="{E(link)}">{"오늘 영상 요약 전체 보기" if slot == "am" else "전체 브리핑 보기"} →</a>']
    text = "\n".join(lines)
    img = None
    try:
        import importlib.util
        sp = importlib.util.spec_from_file_location("pages_for_og", ROOT / "scripts" / "pages.py")
        pg = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(pg)
        if pg.og_image(f"ch-{slot}", kick, head, f"경제 유튜브 영상 {n}편 종합"):
            img = ROOT / "og" / f"ch-{slot}.png"
    except Exception as e:
        print(f"채널 이미지 만들기 실패(글만 올린다): {str(e)[:100]}")
    try:
        ok = tg_photo(img, text, chat=ch, html=True) if img and img.exists() and len(text) <= 1024 else None
        if not ok:
            if img and img.exists():
                tg_photo(img, "", chat=ch)
            ok = tg_send(text, chat=ch, html=True)
        if ok:
            done_[key] = True
            for k in sorted(done_)[:-40]:
                done_.pop(k, None)
            print(f"텔레그램 채널({ch})에 올렸다: {kick}")
    except Exception as e:
        print(f"채널 올리기 실패: {str(e)[:150]}")


def load_briefs():
    return _load_briefs_file()[0]


def load_weekly():
    return _load_briefs_file()[1]


def save_briefs(briefs):
    w = load_weekly()
    _save_briefs_file(sorted(briefs, key=lambda b: b["date"], reverse=True)[:cfg("BRIEF_KEEP", 60)], w)


def save_weekly(weekly):
    b = load_briefs()
    _save_briefs_file(b, sorted(weekly, key=lambda x: x["week"], reverse=True)[:26])


def put_brief(brief):
    briefs = [b for b in load_briefs() if b["date"] != brief["date"]]
    briefs.append(brief)
    save_briefs(briefs)


def update_briefs(state, videos):
    """영상이 충분히 모인 날의 브리핑을 만들거나 새 영상이 늘면 다시 만든다. 한 번 실행에 한 개만 만든다."""
    if not cfg("BRIEF", 1):
        return
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    state.setdefault("brief_final", {})
    by_date = {b["date"]: b for b in load_briefs()}
    groups = {}
    for v in videos:
        groups.setdefault(v["date"], []).append(v)
    min_videos, min_new = cfg("BRIEF_MIN_VIDEOS", 3), cfg("BRIEF_MIN_NEW", 3)
    for date in sorted(groups, reverse=True)[:3]:
        vids, b = groups[date], by_date.get(date)
        n, prev = len(vids), (b["count"] if b else 0)
        if n < min_videos:
            continue
        final_due = date < today and not state["brief_final"].get(date) and n > prev
        if not (b is None or n - prev >= min_new or final_due):
            continue
        print(f"종합 브리핑 만드는 중: {date} (영상 {n}편)")
        try:
            put_brief(build_brief(date, vids))
        except Exception as e:
            print(f"  브리핑 실패: {str(e)[:200]}")
            continue
        if date < today:
            state["brief_final"][date] = True
        print("  브리핑 완료")
        return


def force_brief(date):
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY가 없다.")
        return 1
    videos = load()
    date = date or max((v["date"] for v in videos), default="")
    vids = [v for v in videos if v["date"] == date]
    if not vids:
        print(f"{date}에 올라온 영상이 없어서 브리핑을 만들 수 없다.")
        return 0
    try:
        put_brief(build_brief(date, vids))
        print(f"브리핑 완료: {date} (영상 {len(vids)}편)")
    except Exception as e:
        print(f"브리핑 실패: {str(e)[:200]}")
    return 0


# ---------- 주간 브리핑: 일간 브리핑들을 모아 한 주의 흐름을 정리 ----------
WEEK_PROMPT = """너는 한 주 동안의 일간 브리핑들을 모아 '주간 브리핑'을 쓰는 편집자다. 아래 JSON에는 하루 단위 브리핑(days)과, 그 주 영상들에서 언급된 종목 표(stocks)가 있다. 규칙대로 JSON으로 답해라.

규칙
- 문장은 짧게 쓴다. 한 문장에 정보를 여러 개 이어 붙이지 않는다. 문체는 '~다'로 통일한다.
- 입력에 있는 내용만 쓴다. 네가 아는 정보로 사실 여부를 판단하거나 내용을 보태지 않는다. 특정 종목을 사거나 팔라고 권하는 표현은 쓰지 않는다.
- headline: 이번 주 흐름을 공백 포함 45자 안팎의 짧은 한 문장으로 쓴다.
- keypoints: 이번 주 핵심 3~4줄. 각 줄은 공백 포함 40자 안팎의 짧은 문장 하나다.
- flow: 날짜별로 하루 한 줄. date는 입력의 날짜 그대로, point는 40자 안팎의 짧은 문장.
- recurring: 이틀 이상에 걸쳐 이어서 나온 주제 2~4개. title은 짧게, summary는 두 문장 이내, dates는 입력의 날짜 2개 이상.
- stocks: 입력 stocks 표에 있는 종목만. name은 표의 이름 그대로, note는 그 주에 이 종목에 대한 언급이 어떻게 이어졌는지 한 문장.

입력(JSON):
"""


def weekly_schema():
    from pydantic import BaseModel

    class Flow(BaseModel):
        date: str
        point: str

    class Rec(BaseModel):
        title: str
        summary: str
        dates: list[str]

    class SNote(BaseModel):
        name: str
        note: str

    class Week(BaseModel):
        headline: str
        keypoints: list[str]
        flow: list[Flow]
        recurring: list[Rec]
        stocks: list[SNote]

    return Week


def build_weekly(ws, days, videos):
    end = (datetime.date.fromisoformat(ws) + datetime.timedelta(days=6)).isoformat()
    in_week = [v for v in videos if ws <= v.get("date", "") <= end]
    table = {}
    for v in in_week:
        vid = video_id(v["url"])
        for row in v.get("stocks") or []:
            k = norm_name(row[1])
            if k:
                t = table.setdefault(k, {"name": row[1], "vids": set(), "days": set()})
                t["vids"].add(vid)
                t["days"].add(v["date"])
    multi = [t for t in table.values() if len(t["vids"]) >= 2]
    ranked = sorted(multi or sorted(table.values(), key=lambda t: -len(t["vids"]))[:3], key=lambda t: -len(t["vids"]))[:8]
    payload = {
        "days": [{"date": b["date"], "headline": b.get("headline", ""), "keypoints": b.get("keypoints") or [b.get("overview", "")],
                  "themes": [{"title": t["title"], "summary": t["summary"]} for t in b.get("themes", [])],
                  "disagreements": [d["topic"] for d in b.get("disagreements", [])]} for b in days],
        "stocks": [{"name": t["name"], "videos": len(t["vids"]), "days": sorted(t["days"])} for t in ranked],
    }
    data = call_json(WEEK_PROMPT + json.dumps(payload, ensure_ascii=False), weekly_schema,
                     "BRIEF_MODELS", "gemini-3.6-flash,gemini-3.7-flash,gemini-3.5-flash-lite", 240)
    dates = [b["date"] for b in days]

    def txt(x):
        return (x or "").strip()

    def nd(x):
        """모델이 날짜를 '11.13', '11월 13일', '2026/11/13'처럼 써도 입력 날짜로 맞춘다."""
        nums = re.findall(r"\d+", str(x or ""))
        for d in dates:
            y, m, dd = d.split("-")
            if nums[-3:] == [y, m, dd] or [n.zfill(2) for n in nums[-2:]] == [m, dd]:
                return d
        return None

    kp = [txt(x) for x in data.get("keypoints") or [] if txt(x)][:4]
    flow = [{"date": nd(f.get("date")), "point": txt(f.get("point"))} for f in data.get("flow") or [] if nd(f.get("date")) and txt(f.get("point"))]
    flow.sort(key=lambda f: f["date"])
    rec = []
    for r in data.get("recurring") or []:
        ds = sorted({nd(d) for d in r.get("dates") or [] if nd(d)})
        if txt(r.get("title")) and txt(r.get("summary")) and len(ds) >= 2:
            rec.append({"title": txt(r["title"]), "summary": txt(r["summary"]), "dates": ds})
    names = {norm_name(t["name"]): t for t in ranked}
    stocks = []
    for x in data.get("stocks") or []:
        t = names.get(norm_name(x.get("name")))
        if t and txt(x.get("note")):
            stocks.append({"name": t["name"], "videos": len(t["vids"]), "days": sorted(t["days"]), "note": txt(x["note"])})
    stocks.sort(key=lambda x: -x["videos"])
    if not txt(data.get("headline")) or not kp or not (flow or rec):
        raise ValueError(f"주간 브리핑 결과가 부족하다 (헤드라인 {'있음' if txt(data.get('headline')) else '없음'}, 핵심 줄 {len(kp)}개, 흐름 {len(flow)}개, 반복 주제 {len(rec)}개)")
    return {"week": ws, "end": end, "days": dates, "sig": [f"{b['date']}:{b['count']}" for b in days],
            "gen_date": datetime.datetime.now(KST).strftime("%Y-%m-%d"), "videos": len(in_week),
            "headline": txt(data["headline"]), "keypoints": kp, "flow": flow, "recurring": rec[:4], "stocks": stocks[:8]}


def update_weekly(videos, force_date=None):
    if not force_date and not cfg("WEEKLY", 1):
        return
    briefs, weekly = load_briefs(), load_weekly()
    groups = {}
    for b in briefs:
        groups.setdefault(week_start(b["date"]).isoformat(), []).append(b)
    today = datetime.datetime.now(KST).strftime("%Y-%m-%d")
    cur_week = week_start(today).isoformat()
    min_days = 1 if force_date else cfg("WEEKLY_MIN_DAYS", 3)
    targets = [week_start(force_date).isoformat()] if force_date else sorted(groups, reverse=True)[:2]
    for ws in targets:
        days = sorted(groups.get(ws, []), key=lambda b: b["date"])
        if len(days) < min_days:
            continue
        sig = [f"{b['date']}:{b['count']}" for b in days]
        cur = next((w for w in weekly if w["week"] == ws), None)
        if not force_date and cur:
            if cur.get("sig") == sig:
                continue
            if ws == cur_week and cur.get("gen_date") == today:
                continue  # 진행 중인 주는 하루에 한 번만 다시 만든다
        print(f"주간 브리핑 만드는 중: {ws} 주 (일간 브리핑 {len(days)}개)")
        try:
            w = build_weekly(ws, days, videos)
        except Exception as e:
            print(f"  주간 브리핑 실패: {str(e)[:200]}")
            continue
        weekly = [x for x in weekly if x["week"] != ws] + [w]
        save_weekly(weekly)
        print("  주간 브리핑 완료")
        return


def force_weekly(date):
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY가 없다.")
        return 1
    briefs = load_briefs()
    date = date or max((b["date"] for b in briefs), default="")
    if not date:
        print("일간 브리핑이 아직 없어서 주간 브리핑을 만들 수 없다. 먼저 '브리핑'을 실행해라.")
        return 0
    update_weekly(load(), force_date=date)
    return 0


# ---------- 종목 종합 (stocks.js): 여러 영상에서 나온 종목 이야기를 한 번에 정리 ----------
STOCKS = ROOT / "stocks.js"
STOCK_PROMPT = """너는 경제 유튜브 영상들에서 한 종목에 대해 나온 말들을 모아 정리하는 편집자다. 아래 JSON은 종목 이름과, 날짜·채널별 언급(mentions)이다. 규칙대로 JSON으로 답해라.

규칙
- 문체는 '~다'로 통일하고 문장은 짧게 쓴다.
- 입력에 있는 내용만 쓴다. 네가 아는 정보로 판단하거나 보태지 않는다. 사거나 팔라고 권하지 않는다.
- tone: 채널들의 전반적인 시각. 긍정, 부정, 혼재, 중립 중 하나.
- summary: 채널들이 이 종목을 어떻게 보는지 종합한 한두 문장 (공백 포함 90자 이내).
- points: 공통으로 나온 이야기나 의견이 갈린 지점 2~3개. 각각 공백 포함 45자 안팎의 한 문장.

입력(JSON):
"""


def load_stock_digests():
    try:
        return _read_const(STOCKS.read_text(encoding="utf-8"), "STOCKSUM") or {}
    except Exception:
        return {}


def save_stock_digests(d):
    STOCKS.write_text("/* 종목별 종합 정리. 자동화(scripts/summarize.py)가 갱신하는 파일이다. */\nconst STOCKSUM="
                      + json.dumps(d, ensure_ascii=False, indent=1) + ";\n", encoding="utf-8")


def stock_schema():
    from pydantic import BaseModel

    class StockDigest(BaseModel):
        tone: str
        summary: str
        points: list[str]
    return StockDigest


def update_stock_digests(videos, force=False):
    """최근 30일 동안 2편 이상에서 언급된 종목을 정리한다. 새 언급이 생긴 종목만 다시 만든다."""
    if not force and not cfg("STOCK_DIGEST", 1):
        return
    days, per_run = cfg("STOCK_DAYS", 30), cfg("STOCK_PER_RUN", 2)
    cut = (datetime.datetime.now(KST) - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    table = {}
    for v in videos:
        if v.get("date", "") < cut:
            continue
        vid = video_id(v.get("url"))
        for row in v.get("stocks") or []:
            k = norm_name(row[1])
            if not k:
                continue
            t = table.setdefault(k, {"names": {}, "items": {}})
            t["names"][row[1]] = t["names"].get(row[1], 0) + 1
            t["items"].setdefault(vid, {"date": v["date"], "channel": v["channel"], "note": row[2]})
    digests = load_stock_digests()
    todo = []
    for k, t in table.items():
        if len(t["items"]) < 2:
            continue
        ids = sorted(t["items"])
        if not force and digests.get(k, {}).get("ids") == ids:
            continue
        todo.append((len(ids), k, t, ids))
    todo.sort(reverse=True)  # 많이 언급된 종목부터
    made = 0
    for _, k, t, ids in todo[:per_run if not force else 30]:
        name = max(t["names"], key=t["names"].get)
        items = sorted(t["items"].values(), key=lambda x: x["date"], reverse=True)[:12]
        print(f"종목 종합 만드는 중: {name} (영상 {len(ids)}편)")
        try:
            out = call_json(STOCK_PROMPT + json.dumps({"name": name, "mentions": items}, ensure_ascii=False),
                            stock_schema, "STOCK_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash", 120)
        except Exception as e:
            print(f"  종목 종합 실패: {str(e)[:120]}")
            break  # 혼잡하면 다음 실행으로 미룬다
        summary = (out.get("summary") or "").strip()
        if not summary:
            continue
        tone = out.get("tone") if out.get("tone") in ("긍정", "부정", "혼재", "중립") else "중립"
        digests[k] = {"name": name, "tone": tone, "summary": summary,
                      "points": [p.strip() for p in out.get("points") or [] if p.strip()][:3],
                      "ids": ids, "count": len(ids), "updated": datetime.datetime.now(KST).strftime("%Y-%m-%d")}
        save_stock_digests(digests)
        made += 1
    if made:
        print(f"종목 종합 {made}개를 새로 만들었다.")


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
    min_len = cfg("MIN_VIDEO_SEC", 180)
    per_run = cfg("MAX_PER_RUN", 6)
    deadline = time.time() + cfg("RUN_DEADLINE_MIN", 60) * 60

    channels = read_json(CHANNELS, [])
    if not channels:
        print("channels.json이 없거나 비어 있다.")
        return 1
    state = read_json(STATE, {})
    for k in ("skipped", "failed", "spent", "models", "topic", "brief_final"):
        state.setdefault(k, {})
    MODEL_STATS.update(state["models"])
    now = datetime.datetime.now(datetime.timezone.utc)
    # 영상 예산의 하루는 오후 5시에 시작한다 (구글 무료 한도가 초기화되는 시각에 맞춘다)
    today, budget, slot_name = budget_window(now)
    week_ago = (now.astimezone(KST) - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    state["spent"] = {d: v for d, v in state["spent"].items() if d.split("~")[-1] >= week_ago and d.startswith("17시~")}
    spent = state["spent"].get(today, 0)
    cookie = os.environ.get("YT_COOKIES_FILE", "")
    if cookie and not (os.path.exists(cookie) and os.path.getsize(cookie) > 50):
        cookie = ""
    print(f"영상 예산: {slot_name} 시간대 | 지금까지 쓸 수 있는 시간 {budget // 60}분 중 {spent // 60}분 사용 | 자막 방식: {'켜짐' if cookie else '꺼짐(쿠키 없음)'}")

    videos = load()
    arch = read_json(ARCHIVE, [])
    have = {video_id(v.get("url")) for v in videos + arch}
    fixed = canon_all(videos)
    fixed_n = canon_numbers(videos)
    if fixed or fixed_n:
        save(videos)
    fixed_a = canon_all(arch)
    fixed_an = canon_numbers(arch)
    if fixed_a or fixed_an:
        write_json(ARCHIVE, arch)
    if fixed_n or fixed_an:
        print(f"숫자 지표 이름을 통일했다: {fixed_n + fixed_an}곳 (예: 외국인 코스피 순매도액 -> 외국인 순매도)")
    if fixed or fixed_a:
        print(f"종목 이름을 정식 이름으로 맞췄다: {fixed + fixed_a}곳 (예: 하이닉스 -> SK하이닉스)")

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
        inc = ch.get("title_include") or []  # channels.json에서 제목에 이 말이 들어간 영상만 모으게 할 수 있다 (예: 특정 코너만)
        if inc:
            nk = lambda t: re.sub(r"\s", "", t or "").lower()
            before = len(entries)
            entries = [e for e in entries if any(nk(w) in nk(e["title"]) for w in inc)]
            print(f"  [{ch['name']}] 제목에 {'/'.join(inc)}가 들어간 영상만 본다: {before}편 중 {len(entries)}편")
        win = int(ch.get("max_age_days") or max_age)  # channels.json에서 채널마다 기간을 따로 정할 수 있다
        fresh, known, old = [], 0, 0
        done_n, why = 0, []
        for e in entries:
            if e["id"] in have:
                known += 1
                done_n += 1
                continue
            if e["id"] in state["skipped"]:
                known += 1
                why.append((str(state["skipped"][e["id"]]), e["title"]))
                continue
            if (now - e["published"]).total_seconds() > win * 86400:
                old += 1
                continue
            e["channel"] = author or ch["name"]
            fresh.append(e)
        newest = max((e["published"] for e in entries), default=None)
        ago = f"{(now - newest).days}일 전" if newest else "알 수 없음"
        groups = {}
        for w, _ in why:
            k = w.split(":")[0].split("(")[0].strip()
            groups[k] = groups.get(k, 0) + 1
        gtxt = f" ({', '.join(f'{k} {n}' for k, n in groups.items())})" if groups else ""
        print(f"  [{ch['name']}] 가장 최근 영상 {ago} | 새 영상 {len(fresh)}편 | 요약함 {done_n}편 | 제외 {len(why)}편{gtxt} | 기간({win}일) 지남 {old}편")
        for w, t in why[:6]:  # 무엇을 왜 뺐는지 제목까지 보여 준다
            print(f"    제외: {w[:40]} | {t[:50]}")
        lists.append(fresh)
    if ids_changed:
        write_json(CHANNELS, channels)
    if not lists:
        print("어느 채널의 영상 목록도 가져오지 못했다. (유튜브 쪽 일시 오류일 수 있다. 다음 실행 때 다시 시도한다.)")

    use_topic = cfg("TOPIC_FILTER", 1)
    if use_topic:
        pending = [e for e in interleave(lists) if not e["short"] and e["id"] not in state["topic"] and e["id"] not in state["skipped"]]
        for i in range(0, len(pending), 30):
            chunk = pending[i:i + 30]
            verdict = classify(chunk)
            if verdict is None:
                print("제목 분류에 실패해서 분류하지 못한 영상은 이번 실행에서 건너뛴다. (다음 실행 때 다시 분류한다)")
                break
            for e in chunk:
                v = verdict.get(e["id"])
                if v is None:
                    continue  # 응답에서 빠진 영상은 다음 실행 때 다시 분류한다
                if v[0]:
                    state["topic"][e["id"]] = True
                else:
                    state["skipped"][e["id"]] = "경제 무관: " + v[1]
                    print(f"경제와 무관해서 제외: [{e['channel']}] {e['title']} ({v[1]})")
        write_json(STATE, state)

    done, bad_streak, flash_down = 0, 0, False
    tr_fail, n_tr, n_vid = 0, 0, 0
    long_sec = cfg("LONG_VIDEO_MIN", 75) * 60
    order = sorted(interleave(lists), key=lambda e: (e.get("length") or 0) > long_sec)  # 긴 영상은 짧은 영상을 다 처리한 뒤에
    for e in order:
        if done >= per_run or time.time() > deadline:
            print("이번 실행에서 처리할 수 있는 한도에 도달했다.")
            break
        vid = e["id"]
        if vid in state["skipped"]:
            continue
        if e["short"]:
            state["skipped"][vid] = "쇼츠"
            continue
        if use_topic and not state["topic"].get(vid):
            continue  # 아직 경제 관련인지 확인되지 않은 영상
        info = {"length": e["length"], "live": e["live"], "upcoming": e["upcoming"]} if "length" in e else get_info(vid)
        if info.get("live") or info.get("upcoming"):
            print(f"생방송 중이거나 예정된 영상이라 다음에 처리한다: {e['title']}")
            continue
        length = info.get("length") or 0
        if 0 < length < min_len:
            state["skipped"][vid] = "너무 짧음"
            continue
        if length > max(max_len, cfg("MAX_TRANSCRIPT_MIN", 180) * 60):
            state["skipped"][vid] = f"너무 긴 영상({length // 60}분)"
            print(f"너무 길어서 건너뜀({length // 60}분): {e['title']}")
            continue
        est = length or 1800  # 길이를 모르면 30분으로 계산한다
        age_h = (now - e["published"]).total_seconds() / 3600
        lite_ok = age_h >= cfg("LITE_AFTER_HOURS", 30)  # 곧 기간이 끝나는 영상만 lite 모델을 허용한다
        if flash_down and not lite_ok:
            continue  # 좋은 모델이 이번 실행에서 모두 막혔다. 급하지 않은 영상은 다음 실행에 좋은 모델로 요약한다
        url = f"https://www.youtube.com/watch?v={vid}"
        # 1) 자막을 먼저 시도한다. 자막으로 요약하면 영상 예산(하루 8시간)을 쓰지 않는다
        text = None
        if cookie and tr_fail < 5:
            try:
                lines, how = fetch_transcript_ytdlp(vid, cookie)
                text = "\n".join(f"[{mmss(st)}] {t}" for st, t in lines)
                tr_fail = 0
            except Exception as ex:
                tr_fail += 1
                print(f"  자막을 못 받았다({tr_fail}번째): {e['title'][:40]} | {str(ex).splitlines()[0][:400] if str(ex) else ''}")
                if tr_fail == 5:
                    print("  자막이 5번 연속 실패했다. 이번 실행은 영상 방식으로만 요약한다. (계속 이러면 쿠키가 만료됐을 수 있다)")
            time.sleep(4)  # 자막 요청 사이에 간격을 둔다 (부계정이 봇으로 찍히지 않게)
        if text is None and length > max_len:  # 자막으로는 긴 영상도 요약하지만, 영상 방식은 너무 긴 영상을 하지 않는다
            print(f"자막이 없고 영상이 길어서({length // 60}분) 영상 방식으로는 하지 않는다: {e['title']}")
            continue
        if text is None and spent + est > budget:
            print(f"영상 예산({slot_name} 시간대)을 넘어서 다음으로 미룬다: {e['title']}")
            continue
        src = "자막" if text else "영상"
        print(f"요약 시작({src}): {e['channel']} | {e['title']} ({est // 60}분)")
        try:
            raw = call_gemini(url, allow_lite=lite_ok, transcript=text)
            if raw.get("economic") is False:
                state["skipped"][vid] = "경제 무관(내용 확인)"
                state["topic"].pop(vid, None)
                print(f"  내용을 보니 경제 영상이 아니라서 제외: {e['title']}")
                continue
            entry = clean(raw, url, e["title"], e["channel"], e["published"].astimezone(KST).strftime("%Y-%m-%d"))
            entry["src"] = src
            entry["model"] = next((m for m, o in reversed(STATS) if o == "ok"), "")  # 어느 모델이 요약했는지 기록
            entry["ts"] = e["published"].astimezone(KST).strftime("%Y-%m-%dT%H:%M")  # 올라온 시각 (홈의 최근 24시간 계산용)
            videos.insert(0, entry)
            have.add(vid)
            state["failed"].pop(vid, None)
            state["topic"].pop(vid, None)
            if src == "영상":
                spent += est
                state["spent"][today] = spent
                n_vid += 1
            else:
                n_tr += 1
            done, bad_streak = done + 1, 0
            save(videos)
            print(f"  완료: {e['title']}")
        except Exception as ex:
            busy = any(c in str(ex) for c in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "응답이 없다"))
            if busy and not lite_ok:
                flash_down = True
                print("  좋은 모델이 모두 바쁘거나 한도에 걸렸다. 급하지 않은 영상은 다음 실행으로 미루고, 기간이 곧 끝나는 영상만 계속 처리한다.")
            else:
                bad_streak += 1
            if busy:
                # 구글이 혼잡해서 생긴 일시적인 실패는 포기 횟수에 세지 않는다. (올라온 지 이틀이 지나면 자연히 대상에서 빠진다)
                print(f"  혼잡으로 실패, 다음 실행 때 다시 시도한다: {str(ex)[:150]}")
            else:
                n = state["failed"].get(vid, 0) + 1
                state["failed"][vid] = n
                print(f"  실패({n}번째): {str(ex)[:200]}")
                if n >= 5:
                    state["skipped"][vid] = "요약 5번 실패"
                    state["failed"].pop(vid, None)
        while STATS:
            m, o = STATS.pop()
            c = state["models"].setdefault(m, {"ok": 0, "busy": 0, "dead": 0})
            c[o] += 1
            if c["ok"] + c["busy"] > 40:  # 오래된 기록의 영향이 줄어들게 절반으로 줄인다
                c["ok"], c["busy"] = c["ok"] // 2, c["busy"] // 2
            MODEL_STATS[m] = c
        write_json(STATE, state)
        if bad_streak >= 2:
            print("연속으로 실패해서 이번 실행은 여기서 멈춘다. (구글이 혼잡할 수 있다. 다음 실행 때 다시 시도한다.)")
            break
        time.sleep(5)

    # 이번 실행에서 여유가 남으면 lite 모델로 만든 얕은 요약을 좋은 모델로 다시 만든다 (최근 2일 영상만)
    # 다시 요약은 영상 예산이 초기화되기 직전(오후 3~5시)에, 새 영상을 다 처리하고 남은 여유로만 한다
    redo_cut = (now.astimezone(KST) - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    redo_time = 15 <= now.astimezone(KST).hour < 17
    for v in [v for v in videos if redo_time and is_lite(v.get("model")) and v.get("date", "") >= redo_cut]:
        if done >= per_run or time.time() > deadline or bad_streak >= 2 or flash_down:
            break
        text = None
        if cookie and tr_fail < 5:
            try:
                lines, _ = fetch_transcript_ytdlp(video_id(v["url"]), cookie)
                text = "\n".join(f"[{mmss(st)}] {t}" for st, t in lines)
            except Exception:
                tr_fail += 1
            time.sleep(4)
        if text is None and spent + 1800 > budget:
            break
        print(f"다시 요약(얕은 요약 보완, {'자막' if text else '영상'}): {v['channel']} | {v['title']}")
        try:
            new = clean(call_gemini(v["url"], allow_lite=False, transcript=text), v["url"], v["title"], v["channel"], v["date"])
            new["src"] = "자막" if text else "영상"
            new["model"] = next((m for m, o in reversed(STATS) if o == "ok"), "")
            for k in ("ts", "mood"):
                if v.get(k) and not new.get(k):
                    new[k] = v[k]
            v.clear()
            v.update(new)
            if not text:
                spent += 1800
                state["spent"][today] = spent
            done += 1
            save(videos)
            print("  완료")
        except Exception as ex:
            bad_streak += 1
            print(f"  실패, 다음에 다시 시도한다: {str(ex)[:150]}")
        time.sleep(5)

    try:
        update_briefs(state, videos)
        update_weekly(videos)
        update_stock_digests(videos)
    except Exception as e:
        print(f"브리핑 단계에서 오류: {str(e)[:150]}")
    try:
        fix_all(videos)
    except Exception as e:
        print(f"이름 표기 정리 중 오류: {str(e)[:120]}")
    # 운영 알림: 오래 요약이 없거나 자막이 계속 실패하면 텔레그램으로 알린다
    now_k = datetime.datetime.now(KST)
    if done:
        state["last_ok"] = now_k.strftime("%Y-%m-%dT%H:%M")
    lo = state.get("last_ok")
    if lo and (now_k.replace(tzinfo=None) - datetime.datetime.fromisoformat(lo)).total_seconds() > 16 * 3600:  # 밤사이 새 영상이 없는 시간을 감안해 16시간
        tg_alert(state, "noop-" + lo, f"마지막으로 요약에 성공한 지 16시간이 넘었다 (마지막 성공 {lo}). Actions 로그를 확인해 봐라.")
    if tr_fail >= 5:
        tg_alert(state, "cookie-" + now_k.date().isoformat(), "자막을 5번 연속 못 받았다. 유튜브 쿠키가 만료됐을 수 있다. 부계정으로 쿠키를 다시 내보내서 YOUTUBE_COOKIES 비밀값을 바꿔라.")
    threads_draft(state, videos)
    channel_post(state, videos=videos)
    write_json(STATE, state)
    for m, c in state["models"].items():
        print(f"모델 누적 기록: {m} -> 성공 {c['ok']}, 바쁨 {c['busy']}, 사용불가 {c['dead']}")
    print(f"\n이번 실행: 성공 {done}편 (자막 {n_tr}편 · 영상 {n_vid}편) | 영상 예산 {spent // 60}분 사용 / 지금까지 쓸 수 있는 시간 {budget // 60}분 ({slot_name}, 오후 5시 초기화)")
    return 0


def remove_videos(targets):
    """사이트에서 영상을 지운다. 대상은 영상 주소(또는 ID), 또는 제목에 들어간 단어다. 지운 영상은 다시 요약하지 않는다."""
    videos = load()
    state = read_json(STATE, {})
    state.setdefault("skipped", {})
    removed = []
    for t in targets:
        vid = video_id(t) or (t if re.fullmatch(r"[A-Za-z0-9_-]{11}", t) else None)
        hits = [v for v in videos if video_id(v.get("url")) == vid] if vid else [v for v in videos if t in v.get("title", "")]
        if len(hits) != 1:
            print(f"삭제하지 않았다: '{t}'에 맞는 영상이 {len(hits)}편이라 하나로 정해지지 않는다.")
            for v in hits[:5]:
                print(f"  - {v.get('title')}")
            continue
        v = hits[0]
        videos.remove(v)
        state["skipped"][video_id(v.get("url"))] = "직접 삭제"
        removed.append(v.get("title"))
    if removed:
        save(videos)
        write_json(STATE, state)
    for r in removed:
        print(f"삭제함: {r}")
    print(f"삭제 {len(removed)}편")
    return 0


# ---------- 기존 영상 정리: 긴 결론을 짧게, 숫자에 지표 이름 붙이기 ----------
def tidy_schemas():
    from pydantic import BaseModel

    class Cn(BaseModel):
        id: str
        conclusion: str

    class Cns(BaseModel):
        items: list[Cn]

    class Lb(BaseModel):
        key: str
        label: str

    class Lbs(BaseModel):
        items: list[Lb]

    return Cns, Lbs


def tidy():
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY가 없다.")
        return 1
    Cns, Lbs = tidy_schemas()
    videos = load()
    max_len = cfg("TIDY_MAX_LEN", 70)
    models = ("TIDY_MODELS", "gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.6-flash")

    # 1) 긴 결론 다시 쓰기
    longs = [v for v in videos if len(v.get("conclusion", "")) > max_len]
    print(f"결론이 {max_len}자보다 긴 영상: {len(longs)}편")
    changed = 0
    for i in range(0, len(longs), 15):
        chunk = longs[i:i + 15]
        payload = [{"id": video_id(v["url"]), "title": v["title"], "conclusion": v["conclusion"]} for v in chunk]
        prompt = ("아래는 영상 제목과 현재의 한 줄 결론이다. 결론을 읽기 쉽게 다시 쓴다.\n"
                  "규칙: 공백 포함 55자 안팎, 최대 두 문장(한 문장이 자연스러우면 한 문장). 쉼표로 정보를 이어 붙이지 않고 핵심 하나만 담는다. "
                  "현재 결론과 제목에 있는 내용만 쓴다. '~다' 문체. id는 그대로 돌려준다.\n입력(JSON):\n" + json.dumps(payload, ensure_ascii=False))
        try:
            data = call_json(prompt, lambda: Cns, *models, 180)
        except Exception as e:
            print(f"  결론 다시 쓰기 실패: {str(e)[:150]}")
            break
        new = {str(x.get("id")): (x.get("conclusion") or "").strip() for x in data.get("items", [])}
        for v in chunk:
            n = new.get(video_id(v["url"]))
            if n and len(n) < len(v["conclusion"]):
                v["conclusion"] = n
                changed += 1
        save(videos)
    print(f"결론을 줄인 영상: {changed}편")

    # 2) 숫자에 지표 이름 붙이기
    todo = []
    for v in videos:
        for j, n in enumerate(v.get("numbers") or []):
            if len(n) < 4 or not n[3]:
                todo.append((v, j))
    print(f"지표 이름이 없는 숫자: {len(todo)}개")
    labeled = 0
    for i in range(0, len(todo), 40):
        chunk = todo[i:i + 40]
        payload = [{"key": f"{video_id(v['url'])}:{j}", "title": v["title"], "value": v["numbers"][j][1], "note": v["numbers"][j][2]} for v, j in chunk]
        prompt = ("아래는 영상에서 나온 숫자와 그 설명이다. 각 숫자가 가리키는 지표 이름(label)을 짧은 명사구로 붙인다.\n"
                  "규칙: 같은 지표는 항상 같은 이름으로 쓴다(예: 코스닥 지수, 코스피 지수, 미국 국채 금리, 원/달러 환율, 신용잔고, 외국인 순매도). "
                  "지표라고 하기 어려우면 '기타'로 쓴다. key는 그대로 돌려준다.\n입력(JSON):\n" + json.dumps(payload, ensure_ascii=False))
        try:
            data = call_json(prompt, lambda: Lbs, *models, 180)
        except Exception as e:
            print(f"  지표 이름 붙이기 실패: {str(e)[:150]}")
            break
        lab = {str(x.get("key")): (x.get("label") or "").strip()[:20] for x in data.get("items", [])}
        for v, j in chunk:
            n = v["numbers"][j]
            l = lab.get(f"{video_id(v['url'])}:{j}") or "기타"
            v["numbers"][j] = (n[:3] + [l]) if len(n) >= 3 else n
            labeled += 1
        save(videos)
    print(f"지표 이름을 붙인 숫자: {labeled}개")
    return 0


def diagnose():
    """채널별로 최근 영상이 왜 수집되었는지/안 되었는지 보여 준다. (제미나이를 부르지 않는다)"""
    channels = read_json(CHANNELS, [])
    state = read_json(STATE, {})
    skipped, failed, topic = state.get("skipped", {}), state.get("failed", {}), state.get("topic", {})
    have = {video_id(v.get("url")) for v in load() + read_json(ARCHIVE, [])}
    now = datetime.datetime.now(datetime.timezone.utc)
    max_age = cfg("MAX_AGE_DAYS", 2)
    for ch in channels:
        print(f"\n== {ch.get('name')} ({ch.get('handle')}) ==")
        cid = ch.get("id")
        try:
            cid = cid or resolve_channel_id(ch["handle"])
            author, entries = fetch_entries(cid)
        except Exception as e:
            print(f"  영상 목록을 가져오지 못했다: {str(e)[:150]}")
            continue
        if not entries:
            print("  피드가 비어 있다.")
            continue
        newest = (now - entries[0]["published"]).total_seconds() / 3600
        print(f"  채널 이름 {author} | 피드 {len(entries)}편 | 가장 최신 영상: {newest:.0f}시간 전 | 최근 {max_age}일 이내: "
              f"{sum(1 for e in entries if (now - e['published']).total_seconds() <= max_age * 86400)}편")
        for e in entries[:8]:
            hrs = (now - e["published"]).total_seconds() / 3600
            age = f"{hrs:.0f}시간 전" if hrs < 48 else f"{hrs / 24:.0f}일 전"
            vid = e["id"]
            if vid in have:
                st = "요약되어 사이트에 있음"
            elif vid in skipped:
                st = "제외됨: " + skipped[vid]
            elif e["short"]:
                st = "쇼츠라서 제외"
            elif hrs > max_age * 24:
                st = f"올라온 지 {max_age}일이 지나 대상 아님"
            elif vid in failed:
                st = f"요약에 {failed[vid]}번 실패, 다시 시도 예정"
            elif topic.get(vid):
                st = "후보 (주제 통과, 처리 순서 대기)"
            else:
                st = "후보 (아직 주제 판단 전이거나 예산 때문에 대기)"
            print(f"  {age:>8} | {st} | {e['title'][:45]}")
    return 0


# ---------- 실행 ----------
def main(argv):
    if os.environ.get("NOTE_KEY"):
        return set_note(os.environ["NOTE_KEY"], os.environ.get("NOTE_TEXT", ""))
    tokens = [u for u in re.split(r"[\s,]+", " ".join(argv)) if u]
    removals = [t.split(":", 1)[1] for t in tokens if t.startswith(("삭제:", "remove:")) and t.split(":", 1)[1]]
    briefing = [t for t in tokens if t.startswith("브리핑")]
    weekly_t = [t for t in tokens if t.startswith("주간")]
    tidy_t = [t for t in tokens if t == "정리"]
    if tokens == ["종목"]:  # 종목 종합을 지금 전부 다시 만든다
        if not os.environ.get("GEMINI_API_KEY"):
            print("GEMINI_API_KEY가 없다.")
            return 1
        update_stock_digests(load(), force=True)
        return 0
    if any(t == "진단" for t in tokens) and len(tokens) == 1:
        return diagnose()
    if tokens and tokens[0].split(":")[0] == "채널":  # 텔레그램 채널에 지금 올려 본다. 예: 채널:am (오전 시황) / 채널:pm (오늘 브리핑) / 채널:sat (이번 주 주간)
        st = read_json(STATE, {})
        channel_post(st, force=tokens[0].split(":", 1)[1] if ":" in tokens[0] else "pm")
        write_json(STATE, st)
        return 0
    if tokens and tokens[0].split(":")[0] == "스레드":  # 스레드 초안을 지금 텔레그램으로 보내 본다. 예: 스레드:pm (am·pm·sat·sun)
        slot = tokens[0].split(":", 1)[1] if ":" in tokens[0] else "pm"
        if not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")):
            print("TELEGRAM_BOT_TOKEN 또는 TELEGRAM_CHAT_ID 비밀값이 없다. GitHub 비밀 저장 공간에 넣었는지 확인해라.")
            return 1
        st = read_json(STATE, {})
        threads_draft(st, load(), force=slot if slot in ("am", "pm", "sat", "sun") else "pm")
        return 0
    if tokens and tokens[0].split(":")[0] == "자막테스트":
        return transcript_test(tokens[0].split(":", 1)[1] if ":" in tokens[0] else "")
    if tokens == ["복구"]:  # '경제 무관'으로 빠졌던 영상을 다시 후보로 돌리고 바로 수집을 돌린다
        state = read_json(STATE, {})
        sk, tp = state.setdefault("skipped", {}), state.setdefault("topic", {})
        back = [k for k, why in sk.items() if str(why).startswith("경제 무관")]
        for k in back:
            sk.pop(k, None)
            tp.pop(k, None)
        write_json(STATE, state)
        print(f"'경제 무관'으로 제외됐던 영상 {len(back)}편을 다시 후보로 돌렸다. (올라온 지 {cfg('MAX_AGE_DAYS', 2)}일 안의 영상만 다시 처리된다)")
        return auto()
    urls = [t for t in tokens if not t.startswith(("삭제:", "remove:", "브리핑", "주간")) and t != "정리"]
    if tidy_t and not urls and not removals:
        return tidy()
    if weekly_t and not urls and not removals:
        return force_weekly(weekly_t[0].split(":", 1)[1] if ":" in weekly_t[0] else "")
    if briefing and not urls and not removals:
        return force_brief(briefing[0].split(":", 1)[1] if ":" in briefing[0] else "")
    if removals:
        code = remove_videos(removals)
        if not urls:
            return code
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
