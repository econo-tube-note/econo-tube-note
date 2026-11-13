#!/usr/bin/env python3
"""유튜브 영상 주소를 받아 제미나이로 요약하고 videos.js에 추가한다.

사용법: python scripts/summarize.py <영상주소> [<영상주소> ...]
필요한 것: 환경변수 GEMINI_API_KEY (GitHub 비밀 저장 공간에서 넣어 준다)
"""
import datetime
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# 모델 이름은 여기(또는 워크플로 파일의 GEMINI_MODEL)에서 바꾼다.
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
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
- stocks: 중요하게 다룬 종목 최대 7개. name에는 종목명만 쓰고 괄호로 다른 이름을 덧붙이지 않는다. note에는 왜 언급됐는지 한 줄로 쓴다.
- numbers: 주요 숫자. value는 영상에서 말한 단위와 기준 그대로 적고, 단위나 기준이 분명하지 않으면 '(단위 불명확)'을 붙인다. note에는 숫자의 의미를 한 줄로 쓴다.
- time: 해당 내용이 영상에서 나오는 시간. 링크나 주소 없이 '분:초' 글자만 적는다. 예: 06:34 (1시간이 넘으면 1:05:30). 확실하지 않으면 빈 문자열로 둔다.
- 영상에 없는 내용은 쓰지 않는다. 네가 아는 정보로 영상 내용의 사실 여부를 판단하거나 정정하지 않는다. 추측하지 않는다.
"""


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
                resp = client.models.generate_content(
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
                print(f"  사용한 모델: {model}")
                return json.loads(resp.text)
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
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


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
    DATA.write_text(
        HEADER + "const VIDEOS=" + json.dumps(videos, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8",
    )


def video_id(url):
    m = ID_RE.search(url or "")
    return m.group(1) if m else None


# ---------- 실행 ----------
def main(argv):
    urls = [u for u in re.split(r"[\s,]+", " ".join(argv)) if u]
    if not urls:
        print("영상 주소가 없다. 할 일 없음.")
        return 0
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY가 없다. GitHub 비밀 저장 공간에 키를 넣었는지 확인해라.")
        return 1

    videos = load()
    have = {video_id(v.get("url")) for v in videos}
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
