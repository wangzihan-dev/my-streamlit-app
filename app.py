# app.py
# -*- coding: utf-8 -*-

"""
AI 旅行规划助手（Streamlit 版本）
使用方式：
1) 安装依赖：pip install streamlit
2) 运行应用：streamlit run app.py
"""

import json
import re
import time
import streamlit as st

from city_database import get_city_guide, get_city_names, lookup_attraction
from llm_client import chat_completion, DEEPSEEK_API_KEY

# =========================
# 0. 浏览器渲染兼容性兜底
# =========================
# 这里新增“基础渲染探针”和“配置兜底”，用于排查 Chrome 出现空白页但无明显报错的场景。
# 注意：不会影响原有业务逻辑，只是增加更稳妥的渲染方式。
st.write("界面加载成功")

# 某些环境下 set_page_config 可能因重复调用或版本差异触发异常，
# 为避免页面首屏渲染中断，这里做一次兼容性兜底。
try:
    # =========================
    # 1. 页面基础配置
    # =========================
    # 这里设置网页标题、图标和布局方式。
    # page_title 会显示在浏览器标签页中；
    # layout="wide" 可以让页面更宽一些，展示内容更舒服。
    st.set_page_config(
        page_title="AI 旅行规划助手",
        page_icon="🧳",
        layout="wide"
    )
except Exception:
    # 降级方案：如果高级配置失败，使用默认配置继续渲染，保证页面可见。
    pass

# 用最基础 HTML 输出一段可见文本，作为“基本 HTML 渲染”验证点。
# 该写法只依赖 Streamlit 原生 markdown 的 HTML 能力，不引入额外复杂前端组件。
st.markdown(
    "<div style='font-size:14px;color:#666;'>基础渲染模式已启用（兼容性兜底）</div>",
    unsafe_allow_html=True
)

# 页面主标题（必须与题目要求一致）
st.title("AI 旅行规划助手")
st.caption("输入你的旅行需求，点击按钮即可生成结构清晰的行程方案。")


# =========================
# 2. 侧边栏输入区域（sidebar）
# =========================
# 双模式：顶层 radio 切换「城市探索」与「景点打卡」，下方控件随模式变化。
with st.sidebar:
    app_mode = st.radio(
        "规划模式",
        ["城市探索", "景点打卡"],
        horizontal=True,
        help="城市探索：按天生成上午/下午行程；景点打卡：按景点输出住宿/美食/交通攻略。",
    )

    st.header("旅行参数设置")

    # 默认值，保证主流程变量始终存在（景点打卡模式下部分字段为占位）
    spots_raw = ""
    spot_city_hint = "自动（全库匹配）"

    if app_mode == "城市探索":
        # 模式一：目的地支持「下拉选城市」或「其他→手动输入」
        _city_list = get_city_names()
        _dest_options = _city_list + ["其他（手动输入）"]
        dest_pick = st.selectbox(
            "目的地",
            options=_dest_options,
            index=min(2, len(_dest_options) - 1) if len(_city_list) > 2 else 0,
            help="优先从内置攻略库选城市；选「其他」可自由输入。",
        )
        if dest_pick == "其他（手动输入）":
            destination = st.text_input(
                "手动输入目的地",
                value="",
                placeholder="例如：苏州、青岛",
            )
        else:
            destination = dest_pick

        budget = st.text_input(
            "预算",
            value="3000元",
            placeholder="例如：3000元",
        )

        days = st.number_input(
            "天数",
            min_value=1,
            max_value=30,
            value=3,
            step=1,
        )

        travel_preference = st.selectbox(
            "旅行偏好",
            options=["文艺", "美食", "历史"],
            index=0,
            help="影响模拟行程文风与主题侧重。",
        )

        per_capita_budget = st.number_input(
            "人均预算（元，全程）",
            min_value=0,
            max_value=500000,
            value=3000,
            step=100,
            help="用于计算每日平均可支配金额，并与 fee_items 比对触发熔断提示。",
        )

    else:
        # 模式二：逗号分隔景点 + 所在城市（限定检索范围）
        spot_city_hint = st.selectbox(
            "所在城市",
            options=["自动（全库匹配）"] + get_city_names(),
            index=0,
            help="优先选城市可提高匹配准确度；自动模式将全库模糊匹配景点名。",
        )
        spots_raw = st.text_area(
            "景点列表（逗号分隔）",
            value="万岁山,清明上河园",
            height=88,
            placeholder="例如：万岁山,清明上河园",
            help="多个景点请用中文或英文逗号分隔。",
        )
        destination = ""
        budget = ""
        days = 1
        travel_preference = "美食"
        per_capita_budget = 0

    st.markdown("---")

    # 目的地攻略：折叠区域；景点条目可展开查看「周边酒店 / 周边美食」模拟数据
    with st.expander("目的地攻略", expanded=False):
        guide_city = st.selectbox(
            "选择城市",
            options=get_city_names(),
            index=0,
            help="查询内置攻略库；与「规划模式」独立。",
        )
        guide = get_city_guide(guide_city)
        if guide is None:
            st.caption("暂无该城市攻略数据。")
        else:
            query_kind = st.radio(
                "查询类型",
                options=["景点", "美食"],
                horizontal=True,
            )
            st.markdown(f"**{guide_city} · {query_kind}**")
            if query_kind == "景点":
                for row in guide.get("景点", []):
                    nm = row.get("名称", "")
                    brief = row.get("简介", "")
                    tip = row.get("贴士", "")
                    st.markdown(f"- **{nm}**：{brief} *（贴士：{tip}）*")
                    hotels = row.get("周边酒店") or []
                    foods = row.get("周边美食") or []
                    if hotels:
                        with st.expander(f"「{nm}」周边酒店", expanded=False):
                            for h in hotels:
                                st.caption(
                                    f"{h.get('档次', '')} · {h.get('名称', '')}："
                                    f"{h.get('推荐理由', '')}"
                                )
                    if foods:
                        with st.expander(f"「{nm}」周边美食", expanded=False):
                            for fd in foods:
                                st.caption(
                                    f"{fd.get('名称', '')}（{fd.get('特色', '')}）"
                                    f" — {fd.get('AI食评', '')}"
                                )
            else:
                for row in guide.get("美食", []):
                    name = row.get("名称", "")
                    brief = row.get("简介", "")
                    rec = row.get("推荐", "")
                    st.markdown(f"- **{name}**：{brief} *（推荐：{rec}）*")

    st.markdown("---")
    if app_mode == "城市探索":
        st.info("提示：填写参数后点击右侧「开始规划」生成分天行程。")
    else:
        st.info("提示：输入景点名后点击「开始规划」；未命中库内景点时将输出示例占位内容。")

    # API Key 状态检测
    if not DEEPSEEK_API_KEY:
        st.error("⚠️ 未配置 DeepSeek API Key！请在项目根目录 `.env` 文件中填写 `DEEPSEEK_API_KEY=sk-你的密钥`")
    else:
        st.success("✅ DeepSeek API 已配置")


# =========================
# 3. 右侧按钮区域
# =========================
# 为了让按钮更偏右，我们在主区域使用列布局。
# left_col 占比较大空间，right_col 放按钮，视觉上更靠右。
left_col, right_col = st.columns([4, 1])

with right_col:
    start_plan = st.button("开始规划", use_container_width=True)
    # 视觉亮点：一键根据当前缓存行程生成富有文采的游记（此处为模拟大模型返回）
    gen_memoir = st.button("一键生成游记", use_container_width=True)

# 在主区域放一个占位说明，避免页面看起来太空。
with left_col:
    st.subheader("你的专属行程将在这里生成")
    if app_mode == "城市探索":
        st.write("城市探索模式：点击右侧「开始规划」将生成分天上午/下午行程，并支持预算熔断。")
    else:
        st.write("景点打卡模式：按景点输出住宿圈、美食圈（含短食评）与交通贴士。")

# 主界面指标：模式一显示每日平均预算；模式二显示已输入景点数量
if app_mode == "城市探索":
    _daily_avg = float(per_capita_budget) / float(days) if int(days) > 0 else 0.0
    st.metric(
        label="每日平均预算（人均÷天数）",
        value=f"{_daily_avg:.0f} 元",
        help="由侧边栏「人均预算」与「天数」自动计算，用于预算熔断与平替提示。",
    )
else:
    _n_spots = len([p for p in re.split(r"[,，、;；]", spots_raw or "") if p.strip()])
    st.metric(
        label="打卡点数（已输入）",
        value=f"{_n_spots} 个",
        help="根据景点文本框中逗号分隔的有效名称计数。",
    )


# =========================
# 4. 生成旅行计划的核心函数
# =========================
# 该函数改为：先拼装结构化 Prompt（含 RAG 片段与多约束），再调用大模型 API（此处为模拟），
# 解析模型返回的 JSON，最后转为 Markdown 供原有界面 st.markdown 展示。
# 行程仍包含“每天上午/下午”的安排，满足题目要求。

# RAG 模拟：硬编码的景区运营时间知识，将拼入 Prompt，供模型规划时参考（如避开闭馆日）。
RAG_KNOWLEDGE_SNIPPET = """
【检索到的本地运营信息（知识库片段，模拟 RAG 召回）】
- 故宫博物院：每周一全天闭馆（法定节假日除外）；开放日旺季通常 08:30-17:00。规划含故宫的行程时，不得将故宫安排在周一。
- 中国国家博物馆：每周一闭馆；周二至周日 09:00-17:00（以官方公告为准）。
"""


def build_llm_prompt(
    dest: str,
    bud: str,
    total_days: int,
    travel_pref: str,
    per_capita_yuan: float,
) -> str:
    """
    Prompt 工程：将用户目的地、天数、预算与 RAG 片段、优化约束拼装成结构化指令。
    参数：
        dest: 目的地
        bud: 预算
        total_days: 旅行天数
        travel_pref: 旅行偏好（自然风光 / 人文历史）
        per_capita_yuan: 人均全程预算（元），用于模型在 JSON 中输出 fee_items 并做费用约束
    返回：
        prompt: 发送给大模型的完整提示词文本
    """
    # 多约束优化说明：写入 Prompt，约束模型在空间与时间上的安排方式。
    constraint_geo_transfer = (
        "请将地理位置相近的景点尽量安排在同一天游览；"
        "同一天内相邻两个活动之间的转场时间不得超过 1 小时（含步行、地铁/公交等），"
        "并在 JSON 的 transfer_note 字段中简要说明交通方式或预估路程。"
    )

    prompt = f"""你是一位专业旅行规划师。请严格根据以下用户参数、知识片段与硬约束，输出**仅包含一个合法 JSON 对象**的回答。
不要输出 Markdown 代码围栏、不要输出 JSON 以外的任何解释文字。

【用户参数】
- 目的地：{dest}
- 旅行天数：{total_days}
- 预算：{bud}
- 旅行偏好：{travel_pref}
- 人均全程预算（元）：{per_capita_yuan:.0f}（请据此在 daily_plan 各天给出 fee_items 预估费用，便于做预算熔断）

{RAG_KNOWLEDGE_SNIPPET}

【多约束优化】
- {constraint_geo_transfer}
- 凡行程涉及上述知识片段中的景点，必须遵守其闭馆日与开放时间，不得安排在闭馆日访问。
- 每天必须包含 morning（上午）与 afternoon（下午）两段中文描述，内容具体、可执行。

【JSON 输出 Schema（字段名必须一致）】
{{
  "destination": "与输入目的地一致",
  "budget": "与输入预算一致",
  "total_days": {total_days},
  "travel_preference": "{travel_pref}",
  "per_capita_budget_yuan": {per_capita_yuan:.0f},
  "style": "与旅行偏好一致的一句话风格描述",
  "daily_plan": [
    {{
      "day": 1,
      "morning": "上午行程文字",
      "afternoon": "下午行程文字",
      "transfer_note": "说明当天景点聚类及转场≤1小时的安排",
      "fee_items": [
        {{"name": "景点或项目名", "cost": 0, "alternative": "若超支时的平替建议（免费或低价方案）"}}
      ]
    }}
  ],
  "budget_suggestions": [
    "交通占比建议",
    "住宿占比建议",
    "餐饮占比建议",
    "门票与体验占比建议",
    "备用金建议"
  ],
  "warm_tips": [
    "温馨提示一",
    "温馨提示二",
    "温馨提示三"
  ]
}}

请保证 daily_plan 数组长度等于 total_days，且 day 从 1 连续递增到 {total_days}。
每天 fee_items 至少 2 条，cost 为数字（元），alternative 为字符串。
"""
    return prompt.strip()


def call_travel_llm_api(
    prompt: str,
    dest: str,
    bud: str,
    total_days: int,
    travel_pref: str,
    per_capita_yuan: float,
) -> str:
    """
    调用真实的 DeepSeek API 生成行程。
    如果 API 失败，返回一个带错误提示的 JSON，保证页面不崩溃。
    """
    raw = chat_completion(prompt)
    
    if raw is None:
        # API 失败时的降级 JSON
        error_data = {
            "destination": dest or "未命名目的地",
            "budget": bud,
            "total_days": total_days,
            "travel_preference": travel_pref,
            "per_capita_budget_yuan": per_capita_yuan,
            "style": "API调用失败",
            "daily_plan": [
                {
                    "day": 1,
                    "morning": "API 调用失败。请检查：1) .env 文件是否填写了正确的 DEEPSEEK_API_KEY；2) 网络连接是否正常；3) 是否已安装 requests 库。",
                    "afternoon": "配置完成后刷新页面重试即可。",
                    "transfer_note": "无",
                    "fee_items": [{"name": "错误提示", "cost": 0, "alternative": "检查 .env 文件中的密钥"}],
                }
            ],
            "budget_suggestions": ["请检查 API 配置"],
            "warm_tips": ["请检查 .env 文件中的 DEEPSEEK_API_KEY"],
        }
        return json.dumps(error_data, ensure_ascii=False)
    
    return raw


def parse_travel_plan_json(json_text: str) -> dict:
    """
    解析大模型返回的 JSON 字符串；若模型误加代码围栏，先剥离后再 json.loads。
    参数：
        json_text: 模型输出的原始文本
    返回：
        data: 解析后的字典
    """
    raw = json_text.strip()
    # 兼容少数模型在 JSON 外包裹 ```json ... ``` 的情况
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return json.loads(raw)


def travel_plan_dict_to_markdown(data: dict) -> str:
    """
    将解析后的行程字典转换为 Markdown，保持与原界面展示层级相近（标题、列表、分天小节）。
    参数：
        data: 符合 Schema 的字典
    返回：
        markdown_text: 可直接用 st.markdown 展示的内容
    """
    dest = data.get("destination", "未命名目的地")
    bud = data.get("budget", "")
    total_days = int(data.get("total_days", 0))
    style = data.get("style", "轻松游览 + 文化体验 + 美食探索")
    daily_plan = data.get("daily_plan", [])

    plan_lines = [
        f"## {dest} {total_days}天旅行规划方案",
        "",
        f"- **目的地**：{dest}",
        f"- **预算**：{bud}",
        f"- **天数**：{total_days}天",
    ]
    pref = data.get("travel_preference", "")
    if pref:
        plan_lines.append(f"- **旅行偏好**：{pref}")
    per_cap = data.get("per_capita_budget_yuan")
    if per_cap is not None:
        plan_lines.append(f"- **人均全程预算**：{float(per_cap):.0f} 元")
    plan_lines.extend(
        [
            f"- **规划风格**：{style}",
            "",
            "### 每日详细安排",
            "",
        ]
    )

    for item in daily_plan:
        day_num = item.get("day", 0)
        morning_task = item.get("morning", "")
        afternoon_task = item.get("afternoon", "")
        transfer_note = item.get("transfer_note", "")
        fee_items = item.get("fee_items") or []
        fee_lines = []
        for fi in fee_items:
            nm = fi.get("name", "")
            ct = fi.get("cost", 0)
            fee_lines.append(f"  - {nm}：约 {float(ct):.0f} 元")
        fee_block = "\n".join(fee_lines) if fee_lines else "  - （无分项费用模拟）"
        plan_lines.extend(
            [
                f"#### 第 {day_num} 天",
                f"- **上午**：{morning_task}",
                f"- **下午**：{afternoon_task}",
                f"- **转场与聚类**：{transfer_note}",
                f"- **当日费用模拟（用于预算熔断）**：\n{fee_block}",
                "- **建议**：预留机动时间，灵活调整节奏，避免行程过于紧凑。",
                "",
            ]
        )

    budget_list = data.get("budget_suggestions", [])
    tips_list = data.get("warm_tips", [])

    plan_lines.append("### 预算建议（可按实际调整）")
    for line in budget_list:
        plan_lines.append(f"- {line}")
    plan_lines.append("")
    plan_lines.append("### 温馨提示")
    for line in tips_list:
        plan_lines.append(f"- {line}")

    return "\n".join(plan_lines)


def compute_budget_fuse_warnings(
    data: dict,
    per_capita_yuan: float,
    total_days: int,
) -> list:
    """
    预算实时熔断：计算单日总费用，若超过人均预算÷天数则报警。
    修复了原逻辑中「顺序扣减导致负数后连锁报警」的 Bug。
    """
    if not data or total_days <= 0 or per_capita_yuan <= 0:
        return []
    daily_allowance = float(per_capita_yuan) / float(total_days)
    messages = []
    for item in data.get("daily_plan", []) or []:
        day = item.get("day", 0)
        day_total = 0.0
        alt_text = ""
        for fee in item.get("fee_items", []) or []:
            try:
                cost = float(fee.get("cost", 0))
            except (TypeError, ValueError):
                cost = 0.0
            day_total += cost
            # 取第一个有平替建议的文本作为提示
            if not alt_text and fee.get("alternative"):
                alt_text = str(fee.get("alternative"))

        if day_total > daily_allowance:
            if not alt_text:
                alt_text = "建议减少高价体验项目，选择免费景点或社区餐饮。"
            messages.append(
                f"【预算熔断】第{day}天：当日预估总费用 **{day_total:.0f} 元**，"
                f"超过单日可支配额度 **{daily_allowance:.0f} 元**（人均÷天数）。"
                f"**平替建议**：{alt_text}"
            )
    return messages


def parse_spot_input(text: str) -> list:
    """解析逗号分隔的景点名，支持中英文逗号及顿号。"""
    parts = re.split(r"[,，、;；]", text or "")
    return [p.strip() for p in parts if p.strip()]


def build_spot_checkin_prompt(spot_names: list, city_hint: str) -> str:
    """
    Prompt 工程（景点打卡）：要求模型仅输出 JSON，结构含每景点住宿圈/美食圈/交通贴士。
    真实接入大模型时发送本字符串；当前项目仍以本地模拟填充为主。
    """
    names_txt = "、".join(spot_names)
    return f"""你是一位旅行攻略作者。用户将按景点打卡，请输出**仅一个合法 JSON 对象**。
不要 Markdown 代码围栏，不要输出 JSON 外文字。

【输入】
- 景点列表：{names_txt}
- 城市限定：{city_hint}

【输出 Schema】
{{
  "mode": "spot_guide",
  "city_hint": "{city_hint}",
  "spots": [
    {{
      "name": "景点名",
      "city": "所属城市",
      "住宿圈": [
        {{"tier": "经济型", "name": "酒店名", "reason": "推荐理由"}},
        {{"tier": "舒适型", "name": "...", "reason": "..."}},
        {{"tier": "高端", "name": "...", "reason": "..."}}
      ],
      "美食圈": [
        {{"name": "餐馆名", "tag": "标签", "ai_review": "15-20字网感食评"}}
      ],
      "交通贴士": "从最近枢纽到景点的简述",
      "data_source": "database 或 placeholder"
    }}
  ]
}}
""".strip()


def call_spot_guide_llm_api(
    prompt: str,
    spot_names: list,
    city_hint: str,
) -> str:
    """
    调用真实的 DeepSeek API 生成景点打卡攻略。
    如果 API 失败，回退到本地数据库查询。
    """
    raw = chat_completion(prompt)
    if raw is not None:
        return raw

    # API 失败时，回退到本地数据库
    ch = city_hint if city_hint and city_hint != "自动（全库匹配）" else None
    spots_out = []
    for raw_name in spot_names:
        hit = lookup_attraction(ch, raw_name)
        if hit:
            cname = hit.get("_matched_city", "")
            hotels = []
            for h in (hit.get("周边酒店") or [])[:3]:
                hotels.append(
                    {
                        "tier": h.get("档次", ""),
                        "name": h.get("名称", ""),
                        "reason": h.get("推荐理由", ""),
                    }
                )
            foods = []
            for f in (hit.get("周边美食") or [])[:3]:
                foods.append(
                    {
                        "name": f.get("名称", ""),
                        "tag": f.get("特色", ""),
                        "ai_review": f.get("AI食评", ""),
                    }
                )
            hub = hit.get("交通枢纽", "当地枢纽")
            trans = hit.get("交通贴士") or (
                f"建议从「{hub}」出发，地铁/打车组合前往景区入口（请用导航实时核对）。"
            )
            spots_out.append(
                {
                    "name": hit.get("名称", raw_name),
                    "city": cname,
                    "住宿圈": hotels,
                    "美食圈": foods,
                    "交通贴士": trans,
                    "data_source": "database",
                }
            )
        else:
            spots_out.append(
                {
                    "name": raw_name,
                    "city": city_hint if city_hint != "自动（全库匹配）" else "未指定",
                    "住宿圈": [
                        {
                            "tier": "经济型",
                            "name": f"{raw_name}周边·示例快捷酒店",
                            "reason": "占位示例：未命中本地库，请用地图检索真实预订与评价。",
                        },
                        {
                            "tier": "舒适型",
                            "name": f"{raw_name}周边·示例精选酒店",
                            "reason": "占位示例：关注含早、取消政策与离店时间。",
                        },
                        {
                            "tier": "高端",
                            "name": f"{raw_name}周边·示例度假酒店",
                            "reason": "占位示例：适合纪念日与景观房需求。",
                        },
                    ],
                    "美食圈": [
                        {
                            "name": "周边社区餐厅（示例）",
                            "tag": "平价小碗菜",
                            "ai_review": "未到先香干饭人灵魂一秒归位啦",
                        },
                        {
                            "name": "夜市烧烤摊（示例）",
                            "tag": "夜宵人格",
                            "ai_review": "炭火一串快乐直接拉满谁懂啊",
                        },
                    ],
                    "交通贴士": (
                        "未命中攻略库：建议先到该城市主要交通枢纽，再用地图App检索实时路线"
                        "（示例数据，请务必核实）。"
                    ),
                    "data_source": "placeholder",
                }
            )

    payload = {
        "mode": "spot_guide",
        "city_hint": city_hint or "自动",
        "spots": spots_out,
    }
    return json.dumps(payload, ensure_ascii=False)


def spot_guide_dict_to_markdown(data: dict) -> str:
    """将景点打卡 JSON 转为 Markdown 展示。"""
    lines = ["## 景点打卡 · 一站式攻略", ""]
    lines.append(f"- **检索范围**：{data.get('city_hint', '')}")
    lines.append("")
    for sp in data.get("spots", []) or []:
        nm = sp.get("name", "")
        lines.append(f"### {nm}")
        if sp.get("city"):
            lines.append(f"- **所属城市**：{sp.get('city')}")
        if sp.get("data_source") == "placeholder":
            lines.append("- **提示**：未命中内置攻略库，以下为示例占位，出行前请自行核实。")
        lines.append("#### 住宿圈")
        for h in sp.get("住宿圈", []) or []:
            lines.append(
                f"- **{h.get('tier', '')} | {h.get('name', '')}**：{h.get('reason', '')}"
            )
        lines.append("#### 美食圈")
        for f in sp.get("美食圈", []) or []:
            lines.append(
                f"- **{f.get('name', '')}**（{f.get('tag', '')}）"
                f"「AI食评」：_{f.get('ai_review', '')}_"
            )
        lines.append("#### 交通贴士")
        lines.append(sp.get("交通贴士", ""))
        lines.append("")
    return "\n".join(lines)


def build_spot_checkin_plan(spots_raw: str, city_hint: str) -> tuple:
    """
    景点打卡：Prompt → 模拟 API → 解析 JSON → Markdown。
    返回 (markdown_text, plan_data 或 None)。
    """
    names = parse_spot_input(spots_raw)
    if not names:
        return "## 提示\n\n请至少输入一个景点名称。", None
    prompt = build_spot_checkin_prompt(names, city_hint)
    json_raw = call_spot_guide_llm_api(prompt, names, city_hint)
    try:
        data = parse_travel_plan_json(json_raw)
        md = spot_guide_dict_to_markdown(data)
        return md, data
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return (
            f"## JSON 解析失败\n\n```\n{json_raw[:2000]}\n```\n\n错误：`{e}`",
            None,
        )


def simulate_ai_travel_memoir(plan_data: dict) -> str:
    """
    调用 DeepSeek API 根据行程 JSON 撰写游记。
    API 失败时回退到本地模板。
    """
    if not plan_data:
        return "（暂无行程数据，请先生成攻略）"

    # ===== 调用真实 DeepSeek API 生成游记 =====
    if plan_data.get("mode") == "spot_guide":
        spots = plan_data.get("spots", [])
        spot_names = [s.get("name", "") for s in spots if s.get("name")]
        prompt = f"""你是一位旅行博主，文风温暖细腻。用户刚刚打卡了以下景点：{', '.join(spot_names)}。
请撰写一篇 300 字左右的散文游记，带适当 emoji，直接输出正文，不要输出标题、JSON 或代码块。"""
    else:
        dest = plan_data.get("destination", "远方")
        days = plan_data.get("total_days", 0)
        pref = plan_data.get("travel_preference", "")
        daily = plan_data.get("daily_plan", []) or []
        # 提取行程精华（避免 prompt 过长）
        summary = ""
        for item in daily[:3]:
            d = item.get("day", 0)
            m = item.get("morning", "")[:35]
            a = item.get("afternoon", "")[:35]
            summary += f"第{d}天：上午{m}... 下午{a}... "
        prompt = f"""你是一位旅行博主。用户完成了「{dest}」{days} 天旅行，偏好：{pref}。
行程摘要：{summary}
请撰写一篇 400 字左右的温暖散文游记，带适当 emoji。直接输出正文，不要输出标题、JSON 或代码块。"""

    raw = chat_completion(prompt)
    if raw:
        raw = raw.strip()
        # 清理可能的 markdown 代码围栏
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:markdown)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```\s*$", "", raw)
        return f"## AI 旅行游记\n\n{raw}"

    # ===== API 失败时，回退到本地硬编码模板 =====
    if plan_data.get("mode") == "spot_guide":
        lines = ["## 浮光掠影 · 景点打卡手记", ""]
        for sp in plan_data.get("spots", []) or []:
            nm = sp.get("name", "")
            city = sp.get("city", "")
            trans = sp.get("交通贴士", "")
            foods = sp.get("美食圈") or []
            bite = foods[0].get("ai_review", "") if foods else ""
            lines.append(f"### 与「{nm}」对坐的一小段时间")
            lines.append(
                f"坐标落在**{city}**附近的风里。{trans} "
                f"味蕾先替我打卡：{bite}"
            )
            lines.append("")
        lines.extend(
            [
                "### 尾声",
                "",
                "把地图折成纸船，任它漂向下一个心动坐标；"
                "我知道，最好的风景永远在「出发」这一秒。",
            ]
        )
        return "\n".join(lines)

    dest = plan_data.get("destination", "远方")
    pref = plan_data.get("travel_preference", "")
    style = plan_data.get("style", "")
    bud = plan_data.get("budget", "")
    daily = plan_data.get("daily_plan", []) or []

    lines = [
        f"## 归途仍念 · {dest}行记",
        "",
        f"> 偏好：**{pref}**；行色：**{style}**；行囊所系：**{bud}**。",
        "",
        "若把旅程比作一封写给时光的信，那邮戳便是地铁闸机的轻响，是风掠过檐角时的一声低语。"
        f"在**{dest}**，我把日程折成纸鹤，一只只放进晨昏的缝隙里。",
        "",
    ]

    for item in daily:
        d = item.get("day", 0)
        morning = item.get("morning", "")
        afternoon = item.get("afternoon", "")
        transfer = item.get("transfer_note", "")
        lines.append(f"### 第 {d} 日的浮光")
        lines.append(
            f"清晨，我把自己交给街巷与晨光——{morning} "
            f"午后，光影斜斜地落在肩头，{afternoon} "
            f"转场时我仍记得要把步履放慢：{transfer}"
        )
        lines.append("")

    lines.extend(
        [
            "### 尾声",
            "",
            "当最后一班列车把城市拉成一条温柔的灯河，我忽然明白：所谓旅行，"
            "不是抵达某个坐标，而是让心在陌生的秩序里学会柔软地靠岸。"
            "愿此游记可作你案头的一盏小灯，来日再翻，仍有温度。",
        ]
    )
    return "\n".join(lines)

    
def simulate_social_share_copy(plan_data: dict, result_type: str) -> str:
    """
    调用 DeepSeek API 生成分享文案；API 失败时回退到本地模板。
    """
    if not plan_data:
        return "（暂无行程数据，请先生成攻略）"

    # ===== 新增：调用真实 DeepSeek API 生成分享文案 =====
    if plan_data.get("mode") == "spot_guide" or result_type == "spot_guide":
        spots = [s.get("name", "") for s in plan_data.get("spots", []) if s.get("name")]
        spot_names = "、".join(spots[:6])
        prompt = f"""你是一位小红书旅行博主。用户打卡了以下景点：{spot_names}。
请写一段 80 字左右的分享文案，带 emoji 和 3-4 个话题标签（#xxx 格式）。
直接输出文案，不要输出标题、JSON、代码块或任何解释。"""
    else:
        dest = plan_data.get("destination", "这座城")
        days = plan_data.get("total_days", 0)
        prompt = f"""你是一位小红书旅行博主。用户刚完成「{dest}」{days} 天旅行。
请写一段 80 字左右的分享文案，带 emoji 和 3-4 个话题标签（#xxx 格式）。
直接输出文案，不要输出标题、JSON、代码块或任何解释。"""

    raw = chat_completion(prompt)
    if raw:
        raw = raw.strip()
        # 清理可能的 markdown 代码围栏
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:markdown)?\s*", "", raw, flags=re.IGNORECASE)
            raw = re.sub(r"\s*```\s*$", "", raw)
        return raw

    # ===== API 失败时，回退到原有硬编码模板 =====
    if result_type == "spot_guide" or plan_data.get("mode") == "spot_guide":
        names = [s.get("name", "") for s in plan_data.get("spots", []) if s.get("name")]
        head = "、".join(names[:6])
        return (
            "出发啦✨今天把快乐调成「暴走+干饭」模式～\n"
            f"打卡清单：{head}\n"
            "用脚步收藏一座城，用胃里的小宇宙签收人间烟火🍜\n"
            "#旅行碎片 #周末出逃 #吃货地图 #城市漫游"
        )
    dest = plan_data.get("destination", "这座城")
    daily = plan_data.get("daily_plan", []) or []
    hook = ""
    if daily:
        m0 = daily[0].get("morning", "") or ""
        hook = m0[:56] + ("…" if len(m0) > 56 else "")
    return (
        f"在{dest}把日子过成慢镜头📸 {hook}\n"
        "把晚霞装进口袋，把地图折成风铃——下一站继续发光✨\n"
        "#旅行碎片 #城市漫步 #今日份治愈"
    )


def build_travel_plan(
    dest: str,
    bud: str,
    total_days: int,
    travel_pref: str,
    per_capita_yuan: float,
) -> tuple:
    """
    根据目的地、预算和天数：拼装 Prompt → 调用（模拟）大模型 API → 解析 JSON → 生成 Markdown。
    参数：
        dest: 目的地
        bud: 预算
        total_days: 旅行天数
        travel_pref: 旅行偏好（用户画像）
        per_capita_yuan: 人均全程预算（元），用于 Prompt 与预算熔断
    返回：
        (markdown_text, plan_data 或 None)：Markdown 供展示；plan_data 供熔断检测
    """
    # 如果用户没有输入目的地，给一个默认值，避免展示空内容
    if not dest.strip():
        dest = "未命名目的地"

    # 1）Prompt 工程：结构化指令
    prompt = build_llm_prompt(dest, bud, total_days, travel_pref, per_capita_yuan)
    # 2）大模型 API（真实 DeepSeek）：获取 JSON 字符串
    json_raw = call_travel_llm_api(
        prompt, dest, bud, total_days, travel_pref, per_capita_yuan
    )
    # 3）解析 JSON 并转为 Markdown，供原有界面展示
    try:
        data = parse_travel_plan_json(json_raw)
        markdown_text = travel_plan_dict_to_markdown(data)
        return markdown_text, data
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        # 解析失败时仍输出可读说明，避免页面空白且无反馈
        markdown_text = (
            "## 行程解析提示\n\n"
            f"模型返回的 JSON 无法解析，已显示原始片段供排查：\n\n```\n{json_raw[:2000]}\n```\n\n"
            f"错误信息：`{e}`"
        )
        return markdown_text, None


# =========================
# 5. 按钮触发：模拟 AI 思考 + 展示结果
# =========================
if start_plan:
    if app_mode == "城市探索":
        if not budget.strip():
            st.warning("请先输入预算，再开始规划。")
            st.stop()
        if not (destination or "").strip():
            st.warning("请选择或输入目的地。")
            st.stop()
    else:
        _spots_chk = parse_spot_input(spots_raw)
        if not _spots_chk:
            st.warning("请在景点列表中输入至少一个景点名（逗号分隔）。")
            st.stop()

    # 显示状态文字和进度条
    st.subheader("AI 正在思考中，请稍候...")
    progress_bar = st.progress(0)
    status_text = st.empty()

    for percent in range(1, 101):
        progress_bar.progress(percent)
        if app_mode == "城市探索":
            if percent <= 30:
                status_text.markdown("正在分析目的地热门玩法...")
            elif percent <= 60:
                status_text.markdown("正在评估预算与出行节奏...")
            elif percent <= 90:
                status_text.markdown("正在生成每日上午/下午行程...")
            else:
                status_text.markdown("正在整理最终旅行建议...")
        else:
            if percent <= 40:
                status_text.markdown("正在解析景点列表并检索本地攻略库...")
            elif percent <= 75:
                status_text.markdown("正在组装住宿圈 / 美食圈 / 交通贴士...")
            else:
                status_text.markdown("正在生成 Markdown 攻略...")
        time.sleep(0.02)

    if app_mode == "城市探索":
        final_plan, plan_data = build_travel_plan(
            destination,
            budget,
            int(days),
            travel_preference,
            float(per_capita_budget),
        )
        st.session_state["last_result_type"] = "city_daily"
        st.session_state["last_per_capita"] = float(per_capita_budget)
        st.session_state["last_days"] = int(days)
    else:
        final_plan, plan_data = build_spot_checkin_plan(spots_raw, spot_city_hint)
        st.session_state["last_result_type"] = "spot_guide"
        st.session_state["last_per_capita"] = 0.0
        st.session_state["last_days"] = max(1, len(parse_spot_input(spots_raw)))

    st.session_state["last_plan_md"] = final_plan
    st.session_state["last_plan_data"] = plan_data
    st.session_state["last_app_mode"] = app_mode
    st.session_state.pop("travel_memoir", None)
    st.session_state.pop("share_copy_text", None)

elif not st.session_state.get("last_plan_md"):
    st.markdown(
        """
### 使用说明
1. **规划模式**：顶部选择 **城市探索** 或 **景点打卡**。  
2. **城市探索**：选目的地（或「其他」手动输入）、预算、天数、文艺/美食/历史偏好、人均预算；生成分天行程与预算熔断。  
3. **景点打卡**：输入逗号分隔景点名，并选择所在城市或「自动全库匹配」；按景点输出住宿圈、美食圈（含短食评）与交通贴士。  
4. 可展开 **目的地攻略** 查询多城数据（见 `city_database.py`）。  
5. 生成后可用 **一键生成游记**（右侧）；在攻略正文下方点击 **一键生成分享文案** 可复制发圈/小红书风格短文。  
        """
    )

# 统一展示：最近一次成功规划的 Markdown；城市模式才跑预算熔断
if st.session_state.get("last_plan_md"):
    st.success("规划完成！以下是你的 AI 旅行方案：")
    st.markdown(st.session_state["last_plan_md"])

    _pdata = st.session_state.get("last_plan_data")
    _rtype = st.session_state.get("last_result_type", "city_daily")
    _pc = float(st.session_state.get("last_per_capita", 0) or 0)
    _dy = int(st.session_state.get("last_days", 0) or 0)
    if (
        _rtype == "city_daily"
        and _pdata is not None
        and _pc > 0
        and _pdata.get("mode") != "spot_guide"
    ):
        for msg in compute_budget_fuse_warnings(_pdata, _pc, _dy):
            st.warning(msg)

    # 分享文案按钮放在攻略正文下方，便于答辩演示「社交化输出」动线
    if st.button("一键生成分享文案", use_container_width=True, key="gen_share_under_plan"):
        if not st.session_state.get("last_plan_data"):
            st.warning("请先生成行程或攻略，再点击「一键生成分享文案」。")
        else:
            with st.spinner("AI 正在撰写分享文案..."):
                time.sleep(0.45)
                rt = st.session_state.get("last_result_type", "city_daily")
                st.session_state["share_copy_text"] = simulate_social_share_copy(
                    st.session_state["last_plan_data"], rt
                )

if gen_memoir:
    if not st.session_state.get("last_plan_data"):
        st.warning("请先生成行程或攻略，再点击「一键生成游记」。")
    else:
        with st.spinner("AI 正在提笔撰写游记..."):
            time.sleep(0.6)
            st.session_state["travel_memoir"] = simulate_ai_travel_memoir(
                st.session_state["last_plan_data"]
            )

if st.session_state.get("travel_memoir"):
    st.divider()
    st.subheader("一键游记 · AI 旅行回顾")
    st.markdown(st.session_state["travel_memoir"])

if st.session_state.get("share_copy_text"):
    st.divider()
    st.subheader("一键生成分享文案（可复制发圈/小红书）")
    st.text_area(
        "分享文案",
        value=st.session_state["share_copy_text"],
        height=140,
        help="已带话题标签与表情符号，可直接复制。",
    )