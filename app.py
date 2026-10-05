import streamlit as st
from pathlib import Path

from agent import collect_results, list_photos, run_reconstruction, save_uploaded_photos
from autodl_client import load_config, test_connection

st.set_page_config(page_title="路口三维重建", layout="wide")

PROJECT_DIR = Path(__file__).parent
PHOTOS_DIR = PROJECT_DIR / "photos"
UPLOAD_DIR = PROJECT_DIR / "uploads"
OUTPUT_DIR = PROJECT_DIR / "output"
CONFIG_PATH = PROJECT_DIR / "config.toml"

st.title("城市路口三维场景重建智能体")
st.caption("基于 HunyuanWorld-Mirror · 输入多视角照片 → AutoDL 真推理 → 本地展示结果")

if "logs" not in st.session_state:
    st.session_state.logs = []
if "results" not in st.session_state:
    st.session_state.results = None
if "active_photos" not in st.session_state:
    st.session_state.active_photos = list_photos(PHOTOS_DIR)


def render_log_line(line: str) -> None:
    if any(k in line for k in ("完成", "校验通过", "上传完成", "推理完成", "下载完成")):
        st.success(line)
    elif any(k in line for k in ("失败", "未找到", "错误")):
        st.error(line)
    elif "演示模式" in line or "[stderr]" in line:
        st.warning(line)
    elif line.startswith("步骤"):
        st.info(line)
    else:
        st.text(line)


with st.sidebar:
    st.header("任务配置")
    scene_name = st.text_input("场景名称", value="城市路口-01")
    demo_mode = st.checkbox("演示模式（不连 AutoDL，用本地已有结果）", value=False)

    max_photos = None
    if not demo_mode:
        st.subheader("AutoDL 连接")
        if CONFIG_PATH.exists():
            st.success("已找到 config.toml")
        else:
            st.error("请先创建 config.toml")
            st.code("copy config.example.toml config.toml", language="powershell")

        limit = st.number_input(
            "最多使用照片数（0 = 全部）",
            min_value=0,
            value=20,
            help="建议先用 20 张测试流程，通了再用 0（全部 184 张）",
        )
        max_photos = None if limit == 0 else int(limit)

        if st.button("测试 AutoDL 连接", use_container_width=True):
            try:
                ok, msg = test_connection(load_config(CONFIG_PATH))
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
            except Exception as exc:
                st.error(str(exc))

    st.divider()
    st.subheader("上传照片（可选）")
    uploaded = st.file_uploader(
        "选择路口多视角照片",
        type=["jpg", "jpeg", "png"],
        accept_multiple_files=True,
    )
    if uploaded:
        st.info(f"已选择 {len(uploaded)} 张，点击「开始重建」后保存并使用")

    st.divider()
    start = st.button("开始重建", type="primary", use_container_width=True)

if start:
    st.session_state.logs = []
    st.session_state.results = None

    photos_dir = PHOTOS_DIR
    if uploaded:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for old in UPLOAD_DIR.iterdir():
            if old.is_file():
                old.unlink()
        save_uploaded_photos(uploaded, UPLOAD_DIR)
        photos_dir = UPLOAD_DIR

    log_box = st.empty()
    logs: list[str] = []

    for event in run_reconstruction(
        photos_dir,
        OUTPUT_DIR,
        demo_mode=demo_mode,
        config_path=CONFIG_PATH,
        max_photos=max_photos,
    ):
        message = event["message"]
        logs.append(message)

        with log_box.container():
            st.subheader("智能体执行日志")
            for line in logs[-30:]:
                render_log_line(line)
            if len(logs) > 30:
                st.caption(f"（仅显示最近 30 条，共 {len(logs)} 条）")

        if event["level"] == "done":
            st.session_state.logs = logs
            st.session_state.results = event["results"]
            st.session_state.active_photos = event["photos"]
            break

        if event["level"] == "error":
            st.session_state.logs = logs
            break

elif st.session_state.logs:
    st.subheader("智能体执行日志")
    for line in st.session_state.logs[-30:]:
        render_log_line(line)

st.header("1. 输入照片")
active_photos = st.session_state.active_photos or list_photos(PHOTOS_DIR)
st.write(f"场景：**{scene_name}** · 共 **{len(active_photos)}** 张照片")

if active_photos:
    cols = st.columns(4)
    for i, photo in enumerate(active_photos[:8]):
        cols[i % 4].image(str(photo), caption=photo.name, use_container_width=True)
    if len(active_photos) > 8:
        st.caption(f"仅预览前 8 张，共 {len(active_photos)} 张")
else:
    st.warning("暂无照片")

st.header("2. 重建结果")
results = st.session_state.results or collect_results(OUTPUT_DIR)

ply_file = results.get("ply_file")
if ply_file and ply_file.exists():
    size_mb = ply_file.stat().st_size / 1024 / 1024
    st.success(f"三维高斯模型：gaussians.ply（{size_mb:.1f} MB）")
    col1, col2 = st.columns(2)
    with col1:
        with open(ply_file, "rb") as f:
            st.download_button(
                "下载 gaussians.ply",
                data=f,
                file_name="gaussians.ply",
                mime="application/octet-stream",
                use_container_width=True,
            )
    with col2:
        st.link_button(
            "在 SuperSplat 中打开 3D 模型",
            "https://playcanvas.com/supersplat/editor",
            use_container_width=True,
        )
else:
    st.info("尚未重建，请在左侧点击「开始重建」")

rendered = results.get("rendered_video")
if rendered and rendered.exists():
    st.subheader("新视角渲染")
    st.video(str(rendered))

depth_images = results.get("depth_images") or []
if depth_images:
    st.subheader("深度图预览")
    dcols = st.columns(4)
    for i, depth_img in enumerate(depth_images[:4]):
        dcols[i % 4].image(str(depth_img), caption=depth_img.name, use_container_width=True)
