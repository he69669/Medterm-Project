import json
import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# ---------- 0. 準備環境與頁面 ----------
load_dotenv(Path(__file__).resolve().parent / ".env")
st.set_page_config(page_title="期中個人專題", layout="centered")

# ---------- 1. 專題定位與輸出設計 ----------
APP_TITLE = "AI 說走就走：輕旅遊行程快排"
INSTRUCTIONS = """你是一位專業且貼心的旅遊規劃師。
請閱讀使用者輸入的旅遊需求（地點、天數、偏好等），規劃出一個輕鬆的專屬行程。
任務要求：
1. 給這個行程一個吸引人的主題名稱。
2. 用一段話總結這個行程的風格，並給予簡單的注意事項或天氣提醒。
3. 條列出每日的行程大綱（如 Day 1, Day 2）。
4. 針對該行程與地點，條列出建議攜帶的必備物品。
注意：如果使用者輸入的內容完全不是旅遊需求（例如輸入數學題、抱怨文等），請在名稱與總結欄位委婉告知無法規劃，並將「行程大綱」與「必備物品」的陣列回傳空清單（空陣列）。"""

SCHEMA = {
    "type": "object",
    "properties": {
        "trip_title": {
            "type": "string",
            "description": "旅遊主題名稱，若無法規劃請填寫委婉提示"
        },
        "vibe_description": {
            "type": "string",
            "description": "行程風格總結與貼心提醒"
        },
        "daily_itinerary": {
            "type": "array",
            "items": {"type": "string"},
            "description": "每日行程大綱清單。若無法規劃請回傳空清單"
        },
        "packing_essentials": {
            "type": "array",
            "items": {"type": "string"},
            "description": "建議攜帶的必備物品清單。若無法規劃請回傳空清單"
        }
    },
    "required": ["trip_title", "vibe_description", "daily_itinerary", "packing_essentials"],
    "additionalProperties": False
}

FIELD_LABELS = {
    "trip_title": "✈️ 旅遊主題名稱",
    "vibe_description": "💡 行程風格與貼心提醒",
    "daily_itinerary": "📅 每日行程大綱",
    "packing_essentials": "🎒 必備物品清單"
}

# ---------- 2. 輔助函式 ----------
def read_setting(name, default=""):
    try:
        return st.secrets.get(name, os.getenv(name, default))
    except FileNotFoundError:
        return os.getenv(name, default)

def check_result(data):
    if not isinstance(data, dict) or set(data) != set(SCHEMA["properties"]):
        raise ValueError("回傳欄位不完整或包含未定義欄位。")

    for name, rule in SCHEMA["properties"].items():
        value = data[name]
        if rule["type"] == "string":
            if not isinstance(value, str) or not value.strip():
                raise ValueError("文字欄位必須是非空字串。")
        else:
            if not isinstance(value, list):
                raise ValueError("清單欄位必須是 list。")
            for item in value:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError("清單項目必須是非空字串。")

# ---------- 3. 畫面與狀態初始化 ----------
st.title(APP_TITLE)
st.caption("依原文處理資料；請勿輸入個資、機密或未授權內容。")

enable_api = st.checkbox("啟用真實 API（可能產生費用）", value=False)
st.caption("未啟用時只檢查輸入與設計，不產生 AI 結果。每次有效送出最多 1 次請求。")

st.session_state.setdefault("record", None)
st.session_state.setdefault("error", "")

if st.session_state.get("api_mode") != enable_api:
    st.session_state.record = None
    st.session_state.error = ""
    st.session_state.api_mode = enable_api

if st.button("清除結果"):
    st.session_state.record = None
    st.session_state.error = ""

# ---------- 4. 表單收集原文 ----------
with st.form("project_form"):
    source = st.text_area("請輸入想去的地方、天數與偏好", height=200, placeholder="例如：下週末想去宜蘭兩天一夜，喜歡看海跟吃海鮮，不要太累")
    submitted = st.form_submit_button("規劃行程")

# ---------- 5. 處理與 API 呼叫 ----------
if submitted:
    st.session_state.record = None
    st.session_state.error = ""

    try:
        if not source.strip():
            raise ValueError("請先輸入要處理的原文。")

        if len(source) > 6000:
            raise ValueError("請縮短到 6000 字元以內；不會默默截斷原文。")

        if not APP_TITLE.strip() or not INSTRUCTIONS.strip() or not SCHEMA:
            raise ValueError("請先完成專題名稱、任務規則與輸出欄位設計。")

        fields = SCHEMA.get("properties", {})
        if (SCHEMA.get("type") != "object" or not fields
                or set(SCHEMA.get("required", [])) != set(fields)
                or SCHEMA.get("additionalProperties") is not False):
            raise ValueError("Schema 須是 object，全部欄位必填，且禁止多餘欄位。")

        for rule in fields.values():
            if rule.get("type") == "string" and set(rule) <= {"type", "description"}:
                continue
            if (rule.get("type") == "array" and rule.get("items") == {"type": "string"}
                    and set(rule) <= {"type", "description", "items"}):
                continue
            raise ValueError("此起點只支援 string 與 array of string；其他限制需自行擴充驗證。")

        if not enable_api:
            st.info("輸入與基本設計檢查通過，尚未呼叫 API；這不是模型成果。")
        else:
            key = read_setting("OPENAI_API_KEY")
            if not key:
                raise ValueError("缺少 OPENAI_API_KEY，請設定本機 .env 或平台 Secrets。")

            with OpenAI(api_key=key, max_retries=0, timeout=60.0) as client:
                response = client.responses.create(
                    model=read_setting("OPENAI_MODEL", "gpt-4o-mini"),
                    instructions=INSTRUCTIONS,
                    input="以下是待規劃的旅遊需求：\n" + source,
                    store=False,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": "itinerary_planner",
                            "schema": SCHEMA,
                            "strict": True,
                        },
                    },
                )

            for output in response.output:
                if output.type == "message":
                    for content in output.content:
                        if content.type == "refusal":
                            raise ValueError("模型拒答；請調整資料或任務。")

            if response.status != "completed":
                raise ValueError("回應未完成，未保存部分結果。")
            if not response.output_text.strip():
                raise ValueError("模型沒有回傳可用文字。")

            data = json.loads(response.output_text)
            check_result(data)

            st.session_state.record = {"input": source, "data": data}

    except ValueError as exc:
        st.session_state.error = str(exc)

    except Exception as exc:
        st.session_state.error = (
            "本次未保存結果；請檢查金鑰、模型、網路或額度。錯誤類型："
            + type(exc).__name__
        )

# ---------- 6. 結果顯示 ----------
if st.session_state.error:
    st.error(st.session_state.error)

if st.session_state.record is not None:
    record = st.session_state.record
    st.success("真實 API 結果：格式檢查通過，內容仍需人工核對。")
    st.write("本筆輸入需求：", record["input"])

    for name, value in record["data"].items():
        st.subheader(FIELD_LABELS.get(name, name))
        if isinstance(value, list):
            if not value:
                st.write("無法規劃，此項目無內容。")
            for item in value:
                st.write("• " + item)
        else:
            st.write(value)

    with st.expander("查看原始 JSON"):
        st.json(record["data"])