from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import os

# .env 로드 (파일과 같은 폴더)
load_dotenv(dotenv_path=Path(__file__).with_name(".env"), override=True)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PROMPT = """Write exactly two lines:
LINE 1: Hello from GPT-5
LINE 2: Current date (no code block)."""

buffer = []

with client.responses.stream(
    model="gpt-5",
    input=[
        {"role": "system", "content": "Return plain text only. No explanations."},
        {"role": "user", "content": PROMPT}
    ],
    max_output_tokens=500,
    reasoning={"effort": "medium"},
) as stream:
    for event in stream:
        # 최종 텍스트만 모음
        if event.type == "response.output_text.delta":
            buffer.append(event.delta)
        elif event.type == "response.error":
            raise RuntimeError(event.error)

    final = stream.get_final_response()

text = "".join(buffer).strip()
print("TEXT:\n", text)
print("\n--- RAW (for debug) ---\n", final)
