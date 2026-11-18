import base64
import io
import os
import re
import shutil
import time

import fitz
import pytesseract
import streamlit as st
from openai import APIStatusError, OpenAI, RateLimitError
from PIL import Image

# Tự tìm Tesseract trên Windows nếu chưa có trong PATH
if os.name == "nt" and not shutil.which("tesseract"):
    _tesseract_exe = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.isfile(_tesseract_exe):
        pytesseract.pytesseract.tesseract_cmd = _tesseract_exe

REFINE_PROMPT = """Bạn là chuyên gia hiệu đính văn bản OCR.
Nhiệm vụ: sửa lỗi nhận dạng ký tự, từ, dấu câu tiếng Việt và tiếng Anh từ kết quả OCR thô.
- Giữ nguyên nội dung và ý nghĩa, không thêm thông tin không có trong bản gốc.
- Sửa lỗi chính tả, tách/gộp từ sai, số và ký tự lạ do OCR.
- Giữ cấu trúc đoạn văn, xuống dòng hợp lý.
- Chỉ trả về văn bản đã chỉnh, không giải thích.

Văn bản OCR:
"""

VISION_PROMPT = """Trích xuất toàn bộ văn bản trong ảnh tài liệu này.
- Giữ đúng ngôn ngữ gốc (tiếng Việt, tiếng Anh hoặc hỗn hợp).
- Giữ cấu trúc: đoạn văn, danh sách; bảng dùng markdown nếu cần.
- Chỉ trả về nội dung văn bản, không mô tả ảnh."""

QA_SYSTEM_PROMPT = """Bạn là trợ lý phân tích tài liệu.
Trả lời câu hỏi dựa CHỈ trên nội dung văn bản được trích xuất dưới đây.
- Nếu thông tin không có trong văn bản, nói rõ là không tìm thấy.
- Trả lời bằng tiếng Việt (trừ khi người dùng hỏi bằng ngôn ngữ khác).
- Trích dẫn ngắn gọn từ văn bản khi cần thiết.

--- VĂN BẢN TRÍCH XUẤT ---
"""

MAX_DOC_CHARS_QA = 12_000
MAX_HISTORY_MESSAGES = 6
MAX_RETRIES = 6
VISION_PAGE_DELAY_SEC = 1.0

# ========================================================================================
# CẤU HÌNH TRANG
# ========================================================================================
st.set_page_config(
    page_title="Trợ lý OCR Thông minh",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded",   # Luôn mở sidebar khi load
)

# ========================================================================================
# CUSTOM CSS — MODERN UI
# ========================================================================================
st.markdown("""
<style>
/* ── Google Fonts ── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

/* ── Global ── */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
}

/* ── Ẩn menu và footer mặc định ── */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }

/* ── Nút toggle sidebar — luôn hiển thị rõ ràng ── */
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarOpenButton"] button {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 6px 10px !important;
    box-shadow: 0 4px 14px rgba(99,102,241,0.6) !important;
    opacity: 1 !important;
    visibility: visible !important;
    display: flex !important;
    transition: all 0.2s !important;
}
[data-testid="stSidebarCollapseButton"] button:hover,
[data-testid="stSidebarOpenButton"] button:hover {
    transform: scale(1.1) !important;
    box-shadow: 0 6px 20px rgba(99,102,241,0.8) !important;
}
[data-testid="stSidebarCollapseButton"] button svg,
[data-testid="stSidebarOpenButton"] button svg {
    fill: white !important;
    stroke: white !important;
}

/* ── Nút nổi "⚙ Cài đặt" khi sidebar bị collapse ── */
.fab-settings {
    position: fixed;
    bottom: 2rem;
    right: 2rem;
    z-index: 9999;
    background: linear-gradient(135deg, #6366f1, #8b5cf6);
    color: white;
    border: none;
    border-radius: 50px;
    padding: 0.75rem 1.3rem;
    font-size: 0.95rem;
    font-weight: 600;
    font-family: 'Inter', sans-serif;
    cursor: pointer;
    box-shadow: 0 6px 20px rgba(99,102,241,0.6);
    transition: all 0.2s;
    display: flex;
    align-items: center;
    gap: 0.4rem;
    text-decoration: none;
}
.fab-settings:hover {
    transform: translateY(-3px) scale(1.05);
    box-shadow: 0 10px 30px rgba(99,102,241,0.8);
}
    border: none !important;
}
/* Ẩn decoration trong header nhưng GIỮ nút ── */
header[data-testid="stHeader"] > div:last-child {
    visibility: hidden !important;
}

/* ══════════════════════════════════════════
   NÚT TOGGLE SIDEBAR — HIỂN THỊ RÕ RÀNG
══════════════════════════════════════════ */

/* Nút đóng (❮) khi sidebar đang mở — nằm trong sidebar */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapseButton"] button {
    visibility: visible !important;
    opacity: 1 !important;
    display: flex !important;
}
[data-testid="stSidebarCollapseButton"] button {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 6px 10px !important;
    box-shadow: 0 4px 14px rgba(99,102,241,0.6) !important;
    transition: all 0.2s !important;
}
[data-testid="stSidebarCollapseButton"] button:hover {
    transform: scale(1.1) !important;
    box-shadow: 0 6px 20px rgba(99,102,241,0.8) !important;
}
[data-testid="stSidebarCollapseButton"] button svg {
    fill: white !important;
    stroke: white !important;
    color: white !important;
}

/* Nút mở (☰) khi sidebar đã đóng — nằm góc trên trái main */
[data-testid="stSidebarOpenButton"],
[data-testid="stSidebarOpenButton"] button {
    visibility: visible !important;
    opacity: 1 !important;
    display: flex !important;
}
[data-testid="stSidebarOpenButton"] button {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 6px 10px !important;
    box-shadow: 0 4px 14px rgba(99,102,241,0.6) !important;
    transition: all 0.2s !important;
}
[data-testid="stSidebarOpenButton"] button:hover {
    transform: scale(1.1) !important;
    box-shadow: 0 6px 20px rgba(99,102,241,0.8) !important;
}
[data-testid="stSidebarOpenButton"] button svg {
    fill: white !important;
    stroke: white !important;
    color: white !important;
}

/* Fallback: target mọi button trong vùng header của sidebar ── */
[data-testid="stSidebar"] button[kind="header"],
[data-testid="stSidebar"] [data-testid="stBaseButton-headerNoPadding"] {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    border-radius: 10px !important;
    padding: 6px 10px !important;
    box-shadow: 0 4px 14px rgba(99,102,241,0.6) !important;
    visibility: visible !important;
    opacity: 1 !important;
}
[data-testid="stSidebar"] button[kind="header"] svg,
[data-testid="stSidebar"] [data-testid="stBaseButton-headerNoPadding"] svg {
    fill: white !important;
    stroke: white !important;
}

/* ── Page background ── */
.stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    min-height: 100vh;
}

/* ── Sidebar container ── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%) !important;
    border-right: 1px solid rgba(99,102,241,0.3);
}

/* ── Sidebar text chung ── */
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] div {
    color: #e2e8f0 !important;
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    color: #a5b4fc !important;
    font-weight: 600;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(99,102,241,0.3) !important;
}

/* ── Help text / tooltip bên dưới input ── */
[data-testid="stSidebar"] [data-testid="InputInstructions"],
[data-testid="stSidebar"] .st-emotion-cache-ue6h4q,
[data-testid="stSidebar"] small {
    color: #94a3b8 !important;
    font-size: 0.78rem !important;
}

/* ── Input wrapper (xóa nền trắng) ── */
[data-testid="stSidebar"] [data-baseweb="base-input"],
[data-testid="stSidebar"] [data-baseweb="input"] {
    background: #1e1b4b !important;
    border-radius: 10px !important;
}

/* ── Text input (API Key) ── */
[data-testid="stSidebar"] input[type="password"],
[data-testid="stSidebar"] input[type="text"] {
    background: #1e1b4b !important;
    border: 1.5px solid #6366f1 !important;
    border-radius: 10px !important;
    color: #f1f5f9 !important;
    padding: 0.5rem 0.75rem !important;
    caret-color: #a5b4fc !important;
}
[data-testid="stSidebar"] input[type="password"]:focus,
[data-testid="stSidebar"] input[type="text"]:focus {
    border-color: #a5b4fc !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.25) !important;
    outline: none !important;
}

/* ── Selectbox (Model) — BaseWeb container ── */
[data-testid="stSidebar"] [data-baseweb="select"] > div:first-child {
    background: #1e1b4b !important;
    border: 1.5px solid #6366f1 !important;
    border-radius: 10px !important;
    color: #f1f5f9 !important;
    transition: border-color 0.2s, box-shadow 0.2s;
}
[data-testid="stSidebar"] [data-baseweb="select"] > div:first-child:hover {
    border-color: #a5b4fc !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.2) !important;
}

/* ── Text hiển thị trong ô selectbox đã chọn ── */
[data-testid="stSidebar"] [data-baseweb="select"] [data-baseweb="single-value"] *,
[data-testid="stSidebar"] [data-baseweb="select"] [class*="singleValue"] *,
[data-testid="stSidebar"] [data-baseweb="select"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div[class*="ValueContainer"] span,
[data-testid="stSidebar"] [data-baseweb="select"] div[class*="ValueContainer"] div {
    color: #f1f5f9 !important;
    background: transparent !important;
}

/* ── Mũi tên dropdown icon ── */
[data-testid="stSidebar"] [data-baseweb="select"] svg {
    fill: #a5b4fc !important;
}

/* ── Selectbox dropdown menu ── */
[data-baseweb="popover"] [data-baseweb="menu"] {
    background: #1e1b4b !important;
    border: 1px solid rgba(99,102,241,0.5) !important;
    border-radius: 10px !important;
}
[data-baseweb="popover"] [role="option"] {
    background: transparent !important;
    color: #e2e8f0 !important;
}
[data-baseweb="popover"] [role="option"]:hover,
[data-baseweb="popover"] [aria-selected="true"] {
    background: rgba(99,102,241,0.3) !important;
    color: #a5b4fc !important;
}

/* ── Toggle (switch) ── */
[data-testid="stSidebar"] [data-baseweb="checkbox"] label,
[data-testid="stSidebar"] [data-testid="stToggle"] p {
    color: #cbd5e1 !important;
    font-weight: 500;
}

/* ── Radio buttons ── */
[data-testid="stSidebar"] [data-testid="stRadio"] label {
    color: #cbd5e1 !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] [data-baseweb="radio"] div:first-child {
    border-color: #6366f1 !important;
    background: transparent !important;
}
[data-testid="stSidebar"] [data-testid="stRadio"] [aria-checked="true"] [data-baseweb="radio"] div:first-child {
    background: #6366f1 !important;
    border-color: #6366f1 !important;
}

/* ── Caption / small text ── */
[data-testid="stSidebar"] small,
[data-testid="stSidebar"] .stCaption {
    color: #94a3b8 !important;
}

/* ── Hero header ── */
.hero-header {
    background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 50%, #06b6d4 100%);
    border-radius: 20px;
    padding: 2.5rem 2rem;
    margin-bottom: 2rem;
    text-align: center;
    box-shadow: 0 20px 60px rgba(99,102,241,0.4);
    position: relative;
    overflow: hidden;
}
.hero-header::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(circle, rgba(255,255,255,0.08) 0%, transparent 60%);
    animation: shimmer 4s infinite;
}
@keyframes shimmer {
    0%   { transform: rotate(0deg); }
    100% { transform: rotate(360deg); }
}
.hero-title {
    font-size: 2.4rem;
    font-weight: 700;
    color: white;
    margin: 0;
    text-shadow: 0 2px 10px rgba(0,0,0,0.3);
    letter-spacing: -0.5px;
}
.hero-subtitle {
    font-size: 1.05rem;
    color: rgba(255,255,255,0.85);
    margin-top: 0.6rem;
    font-weight: 400;
}

/* ── Cards ── */
.card {
    background: rgba(255,255,255,0.05);
    backdrop-filter: blur(16px);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 16px;
    padding: 1.5rem;
    margin-bottom: 1.2rem;
    transition: transform 0.2s, box-shadow 0.2s;
}
.card:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 40px rgba(99,102,241,0.25);
}

/* ── Badge chips ── */
.badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.5px;
    text-transform: uppercase;
}
.badge-purple { background: rgba(99,102,241,0.25); color: #a5b4fc; border: 1px solid rgba(99,102,241,0.4); }
.badge-cyan   { background: rgba(6,182,212,0.2);   color: #67e8f9; border: 1px solid rgba(6,182,212,0.4); }
.badge-green  { background: rgba(16,185,129,0.2);  color: #6ee7b7; border: 1px solid rgba(16,185,129,0.4); }

/* ── Section title ── */
.section-title {
    font-size: 1.3rem;
    font-weight: 600;
    color: #e2e8f0;
    margin-bottom: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.section-title::after {
    content: '';
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, rgba(99,102,241,0.5), transparent);
    margin-left: 0.5rem;
}

/* ── Upload zone ── */
[data-testid="stFileUploader"] {
    background: rgba(99,102,241,0.08) !important;
    border: 2px dashed rgba(99,102,241,0.5) !important;
    border-radius: 16px !important;
    transition: all 0.3s;
}
[data-testid="stFileUploader"]:hover {
    border-color: #6366f1 !important;
    background: rgba(99,102,241,0.14) !important;
}
[data-testid="stFileUploader"] label {
    color: #a5b4fc !important;
    font-weight: 500;
}

/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(135deg, #6366f1, #8b5cf6) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    padding: 0.5rem 1.5rem !important;
    font-weight: 600 !important;
    font-family: 'Inter', sans-serif !important;
    transition: all 0.2s !important;
    box-shadow: 0 4px 15px rgba(99,102,241,0.35) !important;
}
.stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(99,102,241,0.5) !important;
}

/* ── Download button ── */
[data-testid="stDownloadButton"] > button {
    background: linear-gradient(135deg, #0ea5e9, #06b6d4) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 600 !important;
    box-shadow: 0 4px 15px rgba(6,182,212,0.3) !important;
    transition: all 0.2s !important;
}
[data-testid="stDownloadButton"] > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 8px 25px rgba(6,182,212,0.5) !important;
}

/* ── Text areas ── */
.stTextArea textarea {
    background: rgba(15,12,41,0.7) !important;
    border: 1px solid rgba(99,102,241,0.3) !important;
    border-radius: 12px !important;
    color: #e2e8f0 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 0.9rem !important;
    line-height: 1.6 !important;
    transition: border-color 0.2s;
}
.stTextArea textarea:focus {
    border-color: #6366f1 !important;
    box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important;
}

/* ── Chat ── */
[data-testid="stChatMessage"] {
    background: rgba(255,255,255,0.05) !important;
    border-radius: 14px !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    margin-bottom: 0.8rem !important;
}
[data-testid="stChatInput"] textarea {
    background: rgba(255,255,255,0.08) !important;
    border: 1px solid rgba(99,102,241,0.4) !important;
    border-radius: 12px !important;
    color: #f1f5f9 !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.1) !important;
    border-radius: 14px !important;
    overflow: hidden;
}
[data-testid="stExpander"] summary {
    color: #a5b4fc !important;
    font-weight: 600 !important;
    font-size: 1rem !important;
}

/* ── Info / Warning / Error boxes ── */
[data-testid="stAlert"] {
    border-radius: 12px !important;
    border-left-width: 4px !important;
}

/* ── Progress bar ── */
[data-testid="stProgressBar"] > div > div {
    background: linear-gradient(90deg, #6366f1, #06b6d4) !important;
    border-radius: 10px !important;
}

/* ── Toggle & Radio ── */
[data-testid="stToggle"] span {
    color: #a5b4fc !important;
}
.stRadio label {
    color: #cbd5e1 !important;
}

/* ── Divider ── */
hr {
    border-color: rgba(99,102,241,0.25) !important;
}

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: rgba(255,255,255,0.03); }
::-webkit-scrollbar-thumb { background: rgba(99,102,241,0.5); border-radius: 10px; }
::-webkit-scrollbar-thumb:hover { background: #6366f1; }

/* ── Main content text ── */
.stMarkdown, .stText, p, li, label {
    color: #cbd5e1;
}
h1, h2, h3, h4 {
    color: #e2e8f0 !important;
}
</style>
""", unsafe_allow_html=True)

# ========================================================================================
# HÀM HỖ TRỢ (LOGIC XỬ LÝ)
# ========================================================================================


def get_openai_client(api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, max_retries=0)


def parse_retry_seconds(error: Exception, attempt: int) -> float:
    msg = str(error)
    match = re.search(r"try again in ([\d.]+)\s*s", msg, re.IGNORECASE)
    if match:
        return float(match.group(1)) + 0.5
    match = re.search(r"try again in (\d+)\s*ms", msg, re.IGNORECASE)
    if match:
        return int(match.group(1)) / 1000 + 0.5
    return min(60.0, 2**attempt)


def chat_completion_with_retry(client: OpenAI, **kwargs):
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as e:
            last_error = e
            time.sleep(parse_retry_seconds(e, attempt))
        except APIStatusError as e:
            if e.status_code == 429:
                last_error = e
                time.sleep(parse_retry_seconds(e, attempt))
            else:
                raise
    raise last_error or RuntimeError("Vượt quá số lần thử khi gọi OpenAI.")


def select_relevant_excerpt(document_text: str, question: str, max_chars: int) -> str:
    if len(document_text) <= max_chars:
        return document_text

    words = [w.lower() for w in re.findall(r"\w+", question) if len(w) > 2]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", document_text) if p.strip()]

    if not paragraphs:
        return document_text[:max_chars] + "\n\n[... phần còn lại đã được cắt bớt ...]"

    scored = sorted(
        paragraphs,
        key=lambda p: sum(1 for w in words if w in p.lower()),
        reverse=True,
    )

    selected, total = [], 0
    for paragraph in scored:
        if total + len(paragraph) + 2 > max_chars:
            continue
        selected.append(paragraph)
        total += len(paragraph) + 2

    if not selected:
        return document_text[:max_chars] + "\n\n[... phần còn lại đã được cắt bớt ...]"

    excerpt = "\n\n".join(selected)
    if len(excerpt) < max_chars * 0.6:
        head = document_text[: max_chars - len(excerpt) - 40]
        excerpt = head + "\n\n[...]\n\n" + excerpt

    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars]
    return excerpt + "\n\n[... các phần khác đã được lược bớt để tránh vượt giới hạn API ...]"


def get_openai_api_key() -> str:
    key = st.session_state.get("openai_api_key", "").strip()
    if key:
        return key
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        return st.secrets.get("OPENAI_API_KEY", "").strip()
    except Exception:
        return ""


def pdf_bytes_to_images(file_bytes, dpi=200):
    """Chuyển PDF thành danh sách ảnh PIL (không cần cài Poppler)."""
    images = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        scale = dpi / 72
        matrix = fitz.Matrix(scale, scale)
        for page in doc:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    finally:
        doc.close()
    return images


@st.cache_resource
def get_ocr_lang():
    """Chọn ngôn ngữ OCR theo gói ngôn ngữ Tesseract đã cài."""
    try:
        installed = set(pytesseract.get_languages(config=""))
        if {"vie", "eng"}.issubset(installed):
            return "vie+eng"
        if "vie" in installed:
            return "vie"
        return "eng"
    except Exception:
        return "eng"


def image_to_base64(image: Image.Image) -> str:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return base64.standard_b64encode(buf.getvalue()).decode("utf-8")


def refine_text_with_openai(raw_text: str, api_key: str, model: str) -> str:
    client = get_openai_client(api_key)
    text = raw_text[:MAX_DOC_CHARS_QA * 4]
    response = chat_completion_with_retry(
        client,
        model=model,
        messages=[{"role": "user", "content": REFINE_PROMPT + text}],
        temperature=0.2,
    )
    return (response.choices[0].message.content or "").strip()


def extract_text_from_image_with_vision(
    image: Image.Image, api_key: str, model: str
) -> str:
    client = get_openai_client(api_key)
    b64 = image_to_base64(image)
    response = chat_completion_with_retry(
        client,
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                ],
            }
        ],
        temperature=0.2,
        max_tokens=4096,
    )
    return (response.choices[0].message.content or "").strip()


def ask_about_document(
    question: str,
    document_text: str,
    api_key: str,
    model: str,
    history: list[dict],
) -> str:
    client = get_openai_client(api_key)
    doc = select_relevant_excerpt(document_text, question, MAX_DOC_CHARS_QA)
    recent_history = history[-MAX_HISTORY_MESSAGES:]

    messages = [{"role": "system", "content": QA_SYSTEM_PROMPT + doc}]
    messages.extend(recent_history)
    messages.append({"role": "user", "content": question})

    response = chat_completion_with_retry(
        client,
        model=model,
        messages=messages,
        temperature=0.3,
        max_tokens=2048,
    )
    return (response.choices[0].message.content or "").strip()


def render_document_qa(file_name: str, document_text: str, api_key: str, model: str):
    """Giao diện hỏi đáp OpenAI về nội dung đã trích xuất."""
    st.markdown("---")
    st.subheader("💬 Hỏi đáp về nội dung")

    if not api_key:
        st.info("Nhập **OpenAI API Key** ở thanh bên trái để đặt câu hỏi về tài liệu.")
        return

    if len(document_text) > MAX_DOC_CHARS_QA:
        st.caption(
            f"Tài liệu dài ({len(document_text):,} ký tự): mỗi câu hỏi chỉ gửi ~{MAX_DOC_CHARS_QA:,} "
            "ký tự liên quan để tránh vượt giới hạn API."
        )

    chat_key = f"chat_{file_name}"
    if chat_key not in st.session_state:
        st.session_state[chat_key] = []

    for msg in st.session_state[chat_key]:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    if st.button("Xóa lịch sử hỏi đáp", key=f"clear_chat_{file_name}"):
        st.session_state[chat_key] = []
        st.rerun()

    question = st.chat_input(
        "Đặt câu hỏi về tài liệu này...",
        key=f"chat_input_{file_name}",
    )

    if question:
        with st.spinner("OpenAI đang trả lời (có thể chờ vài giây nếu API đang bận)..."):
            try:
                answer = ask_about_document(
                    question,
                    document_text,
                    api_key,
                    model,
                    st.session_state[chat_key],
                )
                st.session_state[chat_key].append({"role": "user", "content": question})
                st.session_state[chat_key].append(
                    {"role": "assistant", "content": answer}
                )
                st.rerun()
            except RateLimitError:
                st.error(
                    "OpenAI đang quá tải (giới hạn TPM). "
                    "Vui lòng đợi 30–60 giây rồi gửi lại câu hỏi, hoặc dùng tài liệu ngắn hơn."
                )
            except Exception as e:
                if "rate_limit" in str(e).lower() or "429" in str(e):
                    st.error(
                        "OpenAI đang quá tải. Đợi khoảng 1 phút rồi thử lại, "
                        "hoặc chuyển sang model khác trong sidebar."
                    )
                else:
                    st.error(f"Không thể trả lời: {e}")


@st.cache_data
def run_tesseract_ocr(file_bytes, file_extension):
    """OCR bằng Tesseract (không gọi OpenAI)."""
    lang_code = get_ocr_lang()
    if file_extension == "pdf":
        images = pdf_bytes_to_images(file_bytes)
        parts = [pytesseract.image_to_string(img, lang=lang_code) for img in images]
        return "\n\n--- Hết trang ---\n\n".join(parts)
    if file_extension in ("png", "jpg", "jpeg"):
        image = Image.open(io.BytesIO(file_bytes))
        return pytesseract.image_to_string(image, lang=lang_code)
    raise ValueError(f"Định dạng không hỗ trợ: {file_extension}")


def process_file(
    file_bytes,
    file_extension,
    use_openai: bool,
    openai_mode: str,
    api_key: str,
    model: str,
):
    """
    Xử lý file và trả về (văn bản, lỗi).
    openai_mode: "refine" | "vision"
    """
    try:
        if use_openai and not api_key:
            return None, "Vui lòng nhập OpenAI API Key ở thanh bên trái."

        if use_openai and openai_mode == "vision":
            if file_extension == "pdf":
                images = pdf_bytes_to_images(file_bytes)
            elif file_extension in ("png", "jpg", "jpeg"):
                images = [Image.open(io.BytesIO(file_bytes))]
            else:
                return None, f"Định dạng không hỗ trợ: {file_extension}"

            all_text = []
            progress_bar = st.progress(0, text="OpenAI đang đọc tài liệu...")
            for i, img in enumerate(images):
                if i > 0:
                    time.sleep(VISION_PAGE_DELAY_SEC)
                all_text.append(
                    extract_text_from_image_with_vision(img, api_key, model)
                )
                progress_bar.progress((i + 1) / len(images))
            progress_bar.empty()
            separator = "\n\n--- Hết trang ---\n\n"
            return separator.join(all_text), None

        progress = st.empty()
        progress.info("Đang OCR bằng Tesseract...")
        raw_text = run_tesseract_ocr(file_bytes, file_extension)
        progress.empty()

        if use_openai and openai_mode == "refine":
            if not raw_text.strip():
                return raw_text, None
            with st.spinner("OpenAI đang hiệu đính văn bản..."):
                refined = refine_text_with_openai(raw_text, api_key, model)
            return refined, None

        return raw_text, None
    except RateLimitError:
        return (
            None,
            "OpenAI quá tải (429). Đợi khoảng 1 phút rồi thử lại, "
            "hoặc tắt Vision và dùng Tesseract + Hiệu đính.",
        )
    except Exception as e:
        if "rate_limit" in str(e).lower() or "429" in str(e):
            return (
                None,
                "OpenAI quá tải (429). Đợi khoảng 1 phút rồi thử lại.",
            )
        return None, f"Đã xảy ra lỗi trong quá trình xử lý: {e}"


# ========================================================================================
# GIAO DIỆN CHÍNH CỦA ỨNG DỤNG
# ========================================================================================

with st.sidebar:
    st.markdown("""
    <div style="text-align:center; padding: 1rem 0 0.5rem;">
        <div style="font-size:2.5rem;">🤖</div>
        <div style="font-size:1.1rem; font-weight:700; color:#a5b4fc; letter-spacing:0.5px;">Cấu hình OpenAI</div>
    </div>
    """, unsafe_allow_html=True)

    default_key = os.environ.get("OPENAI_API_KEY", "")
    try:
        default_key = default_key or st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        pass

    api_key_input = st.text_input(
        "🔑 API Key",
        type="password",
        value=default_key,
        placeholder="sk-proj-...",
        help="Dùng cho cải thiện OCR và hỏi đáp về tài liệu.",
    )
    if api_key_input:
        st.session_state["openai_api_key"] = api_key_input

    model = st.selectbox("🧠 Model", ["gpt-4o-mini", "gpt-4o"])

    st.divider()
    use_openai = st.toggle(
        "✨ Cải thiện bằng OpenAI",
        value=bool(default_key),
        help="Dùng GPT để đọc hoặc hiệu đính văn bản chính xác hơn.",
    )
    openai_mode = st.radio(
        "⚙️ Chế độ OCR",
        options=["vision", "refine"],
        format_func=lambda x: {
            "vision": "🔭 Vision — đọc từ ảnh trực tiếp",
            "refine": "✏️ Hiệu đính — sửa sau Tesseract",
        }[x],
        index=0,
        disabled=not use_openai,
    )
    if use_openai:
        st.caption(
            "🔭 Vision: tốt nhất cho ảnh scan.\n✏️ Hiệu đính: nhanh & rẻ hơn."
        )

    st.divider()
    st.markdown("""
    <div style="font-size:0.75rem; color:#64748b; text-align:center; line-height:1.6;">
        📄 Trợ lý OCR Thông minh<br>
        Hỗ trợ PDF · PNG · JPG
    </div>
    """, unsafe_allow_html=True)

# ── Hero Header ──
st.markdown("""
<div class="hero-header">
    <div class="hero-title">📄 Trợ lý OCR Thông minh</div>
    <div class="hero-subtitle">
        Trích xuất văn bản từ ảnh & PDF · Hỗ trợ tiếng Việt & tiếng Anh · Tích hợp AI
    </div>
    <div style="margin-top:1rem; display:flex; gap:0.6rem; justify-content:center; flex-wrap:wrap;">
        <span class="badge badge-purple">🔭 OCR Vision</span>
        <span class="badge badge-cyan">✏️ AI Hiệu đính</span>
        <span class="badge badge-green">💬 Hỏi đáp tài liệu</span>
    </div>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns([3, 2], gap="large")

with col1:
    st.markdown('<div class="section-title">📁 Tải lên tài liệu</div>', unsafe_allow_html=True)
    uploaded_files = st.file_uploader(
        "Kéo thả hoặc chọn file — PDF, PNG, JPG, JPEG",
        type=["pdf", "png", "jpg", "jpeg"],
        accept_multiple_files=True,
        label_visibility="visible",
    )

with col2:
    st.markdown('<div class="section-title">💡 Hướng dẫn</div>', unsafe_allow_html=True)
    st.markdown("""
    <div class="card">
        <p style="margin:0 0 0.8rem; font-size:0.9rem;">
            <span style="color:#a5b4fc; font-weight:600;">🔭 Vision (OpenAI)</span><br>
            <span style="color:#94a3b8;">Đọc trực tiếp từ ảnh — chính xác nhất với tài liệu scan.</span>
        </p>
        <p style="margin:0 0 0.8rem; font-size:0.9rem;">
            <span style="color:#67e8f9; font-weight:600;">✏️ Hiệu đính (OpenAI)</span><br>
            <span style="color:#94a3b8;">Tesseract OCR trước, GPT sửa lỗi chính tả & định dạng.</span>
        </p>
        <p style="margin:0 0 0.8rem; font-size:0.9rem;">
            <span style="color:#6ee7b7; font-weight:600;">💬 Hỏi đáp</span><br>
            <span style="color:#94a3b8;">Sau trích xuất, đặt câu hỏi về nội dung tài liệu.</span>
        </p>
        <p style="margin:0; font-size:0.85rem; color:#64748b;">
            ⚡ Nhập API Key ở sidebar · Ảnh rõ nét cho kết quả tốt nhất
        </p>
    </div>
    """, unsafe_allow_html=True)

if uploaded_files:
    st.markdown('<div class="section-title" style="margin-top:1.5rem;">📋 Kết quả trích xuất</div>', unsafe_allow_html=True)

    api_key = get_openai_api_key()

    for uploaded_file in uploaded_files:
        ext = uploaded_file.name.split(".")[-1].upper()
        with st.expander(f"📄 {uploaded_file.name}  ·  {ext}", expanded=True):
            with st.spinner(f"Đang xử lý '{uploaded_file.name}'..."):
                file_bytes = uploaded_file.getvalue()
                file_extension = uploaded_file.name.split(".")[-1].lower()

                text, error = process_file(
                    file_bytes,
                    file_extension,
                    use_openai=use_openai,
                    openai_mode=openai_mode,
                    api_key=api_key,
                    model=model,
                )

            if error:
                st.error(error)
            else:
                mode_label = "✨ Văn bản (OpenAI):" if use_openai else "📝 Văn bản (Tesseract):"
                st.markdown(f"<p style='color:#a5b4fc; font-weight:600; margin-bottom:0.4rem;'>{mode_label}</p>", unsafe_allow_html=True)
                st.text_area("", text, height=300, key=f"text_{uploaded_file.name}", label_visibility="collapsed")
                st.download_button(
                    label="📥 Tải kết quả này",
                    data=text.encode("utf-8"),
                    file_name=f"ket_qua_{uploaded_file.name}.txt",
                    mime="text/plain",
                    key=f"download_{uploaded_file.name}",
                )
                render_document_qa(uploaded_file.name, text, api_key, model)
