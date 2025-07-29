import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
from supabase import create_client, Client
from openai import OpenAI
from notion_client import Client as NotionClient
import re
import smtplib
from email.mime.text import MIMEText
import markdown

# 환경 변수 로드
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai_client = OpenAI(api_key=OPENAI_API_KEY)
notion_client = NotionClient(auth=NOTION_TOKEN)

def get_recent_articles():
    one_week_ago = datetime.now() - timedelta(weeks=1)
    response = supabase.table("articles").select("title, link").gte("created_at", one_week_ago.isoformat() + "Z").execute()
    return response.data if response.data else []

def generate_ai_trend_report_with_gpt(articles):
    article_list_str = "\n".join([f"- [{article['title']}]({article['link']})" for article in articles])
    
    prompt = f"""다음은 지난 한 주간의 AI 관련 뉴스 기사 제목과 링크 목록입니다.
이 기사들을 분석하여 '주간 AI 트렌드 분석 보고서'를 작성해주세요.

보고서 작성 조건:
- 역할: 당신은 AI 트렌드를 전문적으로 분석하고 보고서를 작성하는 전문가입니다.
- 말투: 전문적이고 읽기 쉬운 블로그 스타일.
- 구성:
  1. 서론: 보고서의 목적과 개요를 설명합니다.
  2. 서론과 주요 트렌드 사이에 마크다운 가로줄(---)을 삽입합니다.
  3. 주요 트렌드 (3~5개): 각 트렌드별로 소제목(###)을 붙이고, 해당 트렌드를 설명하는 문단과 함께 관련 기사들을 `[관련기사보기](링크)` 형식으로 자연스럽게 인용하거나 나열해주세요.
  4. 주요 트렌드와 마무리 인사이트 사이에 마크다운 가로줄(---)을 삽입합니다.
  5. 마무리 인사이트: 전체적인 트렌드를 요약하고 미래 전망에 대한 간략한 인사이트를 제공합니다.
- 형식: 마크다운 형식으로 작성하며, 소제목은 `###`을 사용하고, 기사 인용 시에는 반드시 `[관련기사보기](링크)` 형식을 지켜주세요.

기사 목록:
{article_list_str}

주간 AI 트렌드 분석 보고서:
"""
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert AI trend analyst and report writer."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=2000, # Adjust as needed
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"ChatGPT API 호출 오류: {e}")
        return None

def parse_rich_text(text: str):
    # Markdown 링크 형식: [텍스트](https://...)
    link_pattern = r'\[([^\]]+)\]\((https?://[^\)]+)\)'
    segments = []
    last_end = 0

    for match in re.finditer(link_pattern, text):
        start, end = match.span()
        
        # 일반 텍스트 먼저 추가
        if start > last_end:
            segments.append({
                "type": "text",
                "text": {"content": text[last_end:start]},
                "annotations": {"bold": False}
            })

        # 링크 텍스트를 [텍스트] 형태로 표시
        link_content = match.group(1) # Use match.group(1) directly
        link_url = match.group(2)
        segments.append({
            "type": "text",
            "text": {"content": link_content, "link": {"url": link_url}},
            "annotations": {"bold": False}
        })

        last_end = end

    # 남은 일반 텍스트 추가
    if last_end < len(text):
        segments.append({
            "type": "text",
            "text": {"content": text[last_end:]},
            "annotations": {"bold": False}
        })

    return segments

def markdown_to_notion_blocks(md_text: str):
    lines = md_text.splitlines()
    blocks = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line == "---": # Check for horizontal rule
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

def send_email(subject: str, body: str, to_email: str):
    try:
        msg = MIMEText(body, 'html') # Set subtype to 'html'
        msg['Subject'] = subject
        msg['From'] = EMAIL_SENDER
        msg['To'] = to_email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.send_message(msg)
        print(f"이메일이 {to_email} (으)로 성공적으로 발송되었습니다.")
    except Exception as e:
        print(f"이메일 발송 중 오류 발생: {e}")

if __name__ == "__main__":
    print("Supabase에서 기사 제목과 링크를 가져옵니다...")
    articles = get_recent_articles()
    
    if not articles:
        print("새로운 기사가 없습니다.")
    else:
        print(f"{len(articles)}개의 기사를 찾았습니다. ChatGPT로 보고서 생성을 시작합니다...")
        report_content = generate_ai_trend_report_with_gpt(articles)
        
        if report_content:
            print("보고서 생성 완료. Notion 페이지를 생성합니다...")
            page_title = f"주간 AI 트렌드 분석 보고서 ({datetime.now().strftime('%Y-%m-%d')})"
            notion_url = create_notion_page(page_title, report_content)
            
            if notion_url:
                print(f"Notion 페이지 생성 완료: {notion_url}")
                # Convert markdown to HTML for email body
                html_report_content = markdown.markdown(report_content)
                email_body = f"""<html>
<head>
    <style>
        @import url('https://cdn.jsdelivr.net/gh/projectnoonnu/noonfonts_2001@1.1/GmarketSansMedium.woff') format('woff');
        body {{
            font-family: 'GmarketSans', 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif;
        }}
    </style>
</head>
<body>
    <p>안녕하세요,</p>
    <p>주간 AI 트렌드 분석 보고서가 생성되었습니다.</p>
    <p>Notion 링크: <a href=\"{notion_url}\">Notion 링크</a></p>
    <h2>보고서 내용:</h2>
    {html_report_content}
</body>
</html>"""
                send_email(
                    subject=f"[주간 AI 트렌드] {page_title}",
                    body=email_body,
                    to_email=EMAIL_RECIPIENT
                )
            else:
                print("Notion 페이지 생성에 실패했습니다.")
        else:
            print("ChatGPT 보고서 생성에 실패했습니다.")