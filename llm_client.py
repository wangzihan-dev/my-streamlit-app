# llm_client.py
# -*- coding: utf-8 -*-

import os
import requests

# 本地开发用 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-chat"


def _get_api_key():
    """兼容本地.env和Streamlit Cloud Secrets"""
    # 1. 先尝试环境变量（本地开发）
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if key:
        return key
    
    # 2. 再尝试 Streamlit Secrets（云端部署）
    try:
        import streamlit as st
        key = st.secrets.get("DEEPSEEK_API_KEY", "")
        if key:
            return key
    except Exception:
        pass
    
    return ""


# 这个类让 app.py 里的 "if not DEEPSEEK_API_KEY:" 判断能正确工作
class _KeyProxy:
    def __bool__(self):
        return bool(_get_api_key())
    def __str__(self):
        return _get_api_key()

DEEPSEEK_API_KEY = _KeyProxy()


def chat_completion(prompt: str) -> str:
    api_key = _get_api_key()
    if not api_key:
        print("警告：未配置 DEEPSEEK_API_KEY")
        return None

    url = f"{BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "max_tokens": 2000,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"API 调用失败：{e}")
        return None
