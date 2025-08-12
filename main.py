import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI
from notion_client import Client as NotionClient
import re
import smtplib
from email.message import EmailMessage
import markdown

# 환경 변수 로드
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")  # 권장: Service Role Key
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# Edge Function(텍스트 응답)과 연동되는 구독/해지 URL
UNSUB_BASE = "https://corocmnneqzimohtrhuf.supabase.co/functions/v1/unsubscribe"
SUB_BASE   = "https://corocmnneqzimohtrhuf.supabase.co/functions/v1/subscribe"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
notion_client = NotionClient(auth=NOTION_TOKEN)

def get_subscribers():
    """구독자 목록(이메일+토큰) 조회"""
    resp = supabase.table("subscribers").select("email, token").eq("subscribed", True).execute()
    return resp.data or []

def get_recent_articles():
    """최근 7일 기사"""
    one_week_ago = datetime.now() - timedelta(days=7)
    response = (
        supabase.table("articles")
        .select("title, link")
        .gte("created_at", one_week_ago.isoformat() + "Z")
        .execute()
    )
    return response.data if response.data else []

def generate_ai_trend_report_with_gpt(articles):
    article_list_str = "\n".join([f"- [{a['title']}]({a['link']})" for a in articles])

    prompt = f"""
당신의 역할:
당신은 인공지능(AI) 산업 전반의 기술, 비즈니스, 정책 흐름을 분석하는 전문 애널리스트입니다.
다음에 제시되는 AI 관련 뉴스 제목과 링크 목록을 기반으로, 지난 한 주간의 주요 AI 트렌드 분석 보고서를 작성해 주세요.
영어기사와 한국어기사를 모두 포함하여, 종합적으로 분석해 주세요.

작성 조건 및 형식:
스타일: 전문가다운 어조이되, 읽기 쉬운 블로그 스타일로 작성하세요.

구조는 아래의 형식을 따라 주세요:
보고서 구조:
# 주간 AI 트렌드 분석 보고서

이번 보고서의 목적과 개요를 간단히 설명해 주세요.

--- (마크다운 가로줄)
## 주요 트렌드
주요 트렌드 분석 (3~5개)
각 트렌드는 ### 소제목으로 작성해 주세요. 번호를 붙여주세요.
각 트렌드 아래에는 불릿을 붙여 3~5개 핵심 포인트를 설명해 주세요.
설명 문장 내의 핵심 키워드를 클릭하면 관련 기사로 연결되도록 해주세요.

--- (마크다운 가로줄)

## 주요 기업 동향
google, Microsoft, OpenAI 등 주요 기업의 최근 동향을 포함해 주세요.
문장에는 불릿을 붙여 작성해 주고, 문장 내의 핵심 키워드를 클릭하면 관련 기사로 연결되도록 해주세요.

--- (마크다운 가로줄)

## 기술 트렌드
새롭게 발표된 기술이나 제품, 모델, 연구 결과 등에 대해 분석해 주세요.
문장에는 불릿을 붙여 작성해 주고, 문장 내의 핵심 키워드를 클릭하면 관련 기사로 연결되도록 해주세요.

--- (마크다운 가로줄)

## 마무리 인사이트
이번 주 AI 업계의 전반적인 흐름을 요약하고,
향후 주목할 기술/산업/정책 이슈에 대해 간단한 전망을 덧붙여 주세요.

**출력 규칙**:
- 최종 보고서 전체 분량은 공백 포함 2000자 이내로 작성.

기사 목록:
{article_list_str}

주간 AI 트렌드 분석 보고서:
"""

    def _extract_text(resp):
        if hasattr(resp, "output_text") and resp.output_text:
            return resp.output_text
        parts = []
        for item in getattr(resp, "output", []) or []:
            if getattr(item, "type", None) in ("message", "text", "output_text"):
                content = getattr(item, "content", None)
                if isinstance(content, list):
                    for c in content:
                        if getattr(c, "type", None) in ("text", "output_text"):
                            parts.append(str(getattr(c, "text", "")))
                elif content:
                    parts.append(str(content))
        return "\n".join(p for p in parts if p).strip()

    try:
        resp = openai_client.responses.create(
            model="gpt-5",
            input=[
                {"role": "system", "content": "You are an expert AI trend analyst and report writer. Reply with Markdown only, no explanations."},
                {"role": "user", "content": prompt},
            ],
            max_output_tokens=10000,
            reasoning={"effort": "medium"},
        )
        text = _extract_text(resp)
        if not text:
            print("DEBUG raw response:", resp)
            return None
        return text
    except Exception as e:
        import traceback
        print("ChatGPT API 호출 오류:", repr(e))
        traceback.print_exc()
        return None

# --- Notion 변환 유틸 (그대로 사용) ---
def parse_rich_text(text: str):
    # Markdown 링크 및 bold 텍스트를 함께 처리
    link_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
    bold_pattern = r'\*\*([^\*]+)\*\*'
    segments = []
    last_end = 0

    # 링크 우선 처리
    for match in re.finditer(link_pattern, text):
        start, end = match.span()

        # 이전 일반 텍스트 (굵게 포함 가능)
        if start > last_end:
            interim_text = text[last_end:start]
            segments.extend(process_text_styles(interim_text))

        # 링크 추가
        link_text = match.group(1)
        link_url = match.group(2)
        segments.append({
            "type": "text",
            "text": {"content": link_text, "link": {"url": link_url}},
            "annotations": {"bold": False}
        })

        last_end = end

    # 남은 텍스트 처리
    if last_end < len(text):
        segments.extend(process_text_styles(text[last_end:]))

    return segments

def process_text_styles(text: str):
    segments = []
    last_end = 0

    # **굵게** 또는 *기울임* 모두 처리
    pattern = r'(\*\*.*?\*\*|\*.*?\*)'
    for match in re.finditer(pattern, text):
        start, end = match.span()
        if start > last_end:
            segments.append({
                "type": "text",
                "text": {"content": text[last_end:start]},
                "annotations": {"bold": False, "italic": False}
            })

        content = match.group(0)
        clean_content = content.strip('*')
        is_bold = content.startswith('**')
        is_italic = not is_bold  # 간단한 처리

        segments.append({
            "type": "text",
            "text": {"content": clean_content},
            "annotations": {"bold": is_bold, "italic": is_italic}
        })

        last_end = end

    if last_end < len(text):
        segments.append({
            "type": "text",
            "text": {"content": text[last_end:]},
            "annotations": {"bold": False, "italic": False}
        })

    return segments

def markdown_to_notion_blocks(md_text: str):
    lines = md_text.splitlines()
    blocks = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line == "---":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
        elif line.startswith("### "):
            blocks.append({"object": "block", "type": "heading_3", "heading_3": {"rich_text": parse_rich_text(line[4:])}})
        elif line.startswith("## "):
            blocks.append({"object": "block", "type": "heading_2", "heading_2": {"rich_text": parse_rich_text(line[3:])}})
        elif line.startswith("# "):
            blocks.append({"object": "block", "type": "heading_1", "heading_1": {"rich_text": parse_rich_text(line[2:])}})
        elif line.startswith("- "):
            blocks.append({"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": parse_rich_text(line[2:])}})
        else:
            blocks.append({"object": "block", "type": "paragraph", "paragraph": {"rich_text": parse_rich_text(line)}})
    return blocks

def create_notion_page(title, content):
    try:
        children = markdown_to_notion_blocks(content)
        response = notion_client.pages.create(
            parent={"database_id": NOTION_DATABASE_ID},
            properties={"제목": {"title": [{"text": {"content": title}}]}},
            children=children
        )
        return response["url"]
    except Exception as e:
        print(f"Notion 페이지 생성 오류: {e}")
        return None

# --- 이메일 발송(구독자별) ---
def build_footer(unsub_url: str, sub_url: str):
    return f"""
<hr>
<p style="font-size:12px;color:#666">
  이 메일은 구독자에게 발송되었습니다.
  <a href="{sub_url}">구독하기</a> · <a href="{unsub_url}">구독취소</a>
</p>"""

def send_one(subject: str, html_body: str, to_email: str, token: str):
    unsub_url = f"{UNSUB_BASE}?token={token}"
    resub_url = f"{SUB_BASE}?token={token}"
    full_html = html_body + build_footer(unsub_url, resub_url)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_SENDER
    msg["To"] = to_email
    msg["List-Unsubscribe"] = f"<{unsub_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    msg.set_content("HTML email")
    msg.add_alternative(full_html, subtype="html")

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
        smtp.send_message(msg)

if __name__ == "__main__":
    print("Supabase에서 최근 7일 기사 제목과 링크를 가져옵니다...")
    articles = get_recent_articles()

    if not articles:
        print("새로운 기사가 없습니다.")
    else:
        print(f"{len(articles)}개의 기사를 찾았습니다. ChatGPT로 보고서 생성을 시작합니다...")
        report_content = generate_ai_trend_report_with_gpt(articles)

        if report_content:
            report_content += (
                "\n\n---\n\n"
                "본 보고서는 국내외 주요 AI 전문 언론사의 최근 1주일 기사 내용을 기반으로 **ChatGPT**가 종합·작성한 자료입니다.\n"
                "*(국내: AI TIMES, Mirakle AI, 로봇신문 / 해외: MIT Technology Review, The Verge, VentureBeat, Techcrunch)*"
            )

            # 주간 제목(오늘 기준 주차 끝일자 표기)
            page_title = f"주간 AI 트렌드 분석 보고서 ({(datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')})"
            print("보고서 생성 완료. Notion 페이지를 생성합니다...")
            notion_url = create_notion_page(page_title, report_content)

            if notion_url:
                print(f"Notion 페이지 생성 완료: {notion_url}")
                html_report_content = markdown.markdown(report_content)
                email_body = f"""<html>
<head>
  <meta charset="utf-8">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap');
    body {{ font-family: 'Inter', sans-serif; }}
  </style>
</head>
<body>
  <p>안녕하세요,</p>
  <p>주간 AI 트렌드 분석 보고서가 생성되었습니다.</p>
  <p><a href="{notion_url}">Notion 링크</a></p>
  {html_report_content}
</body>
</html>"""

                subs = get_subscribers()
                if not subs:
                    print("구독자가 없습니다.")
                else:
                    for s in subs:
                        try:
                            if not s.get("email") or not s.get("token"):
                                print(f"스킵: 잘못된 레코드 {s}")
                                continue
                            send_one(
                                subject=f"[주간 AI 트렌드] {page_title}",
                                html_body=email_body,
                                to_email=s["email"],
                                token=s["token"],
                            )
                        except Exception as e:
                            print(f"발송 실패({s.get('email')}): {e}")
            else:
                print("Notion 페이지 생성에 실패했습니다.")
        else:
            print("ChatGPT 보고서 생성에 실패했습니다.")
