"""城市路口三维重建智能体：按步骤编排重建任务。"""

import time
from pathlib import Path
from typing import collections.abc.Generator

from autodl_client import (
    connect,
    download_results,
    load_config,
    run_remote_inference,
    upload_photos,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def list_photos(photos_dir: Path) -> list[Path]:
    if not photos_dir.exists():
        return []
    return sorted(
        p for p in photos_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS
    )


def save_uploaded_photos(uploaded_files, target_dir: Path) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for uploaded in uploaded_files:
        dest = target_dir / uploaded.name
        dest.write_bytes(uploaded.getbuffer())
        saved.append(dest)
    return saved


def validate_photos(photos: list[Path]) -> tuple[bool, str]:
    if not photos:
        return False, "未找到照片，请上传或确认 photos 文件夹中有图片"
    if len(photos) < 8:
        return False, f"照片数量过少（{len(photos)} 张），建议至少 8 张多视角照片"
    bad = [p.name for p in photos if p.suffix.lower() not in IMAGE_EXTENSIONS]
    if bad:
        return False, f"存在不支持的格式：{', '.join(bad[:3])}"
    return True, f"照片校验通过，共 {len(photos)} 张"


def collect_results(output_dir: Path) -> dict:
    ply_file = output_dir / "gaussians.ply"
    pointcloud = output_dir / "pts_from_pointmap.ply"
    rendered = output_dir / "rendered.mp4"
    depth_dir = output_dir / "depth"
    depth_images = sorted(depth_dir.glob("*.png")) if depth_dir.exists() else []

    return {
        "ply_file": ply_file if ply_file.exists() else None,
        "pointcloud": pointcloud if pointcloud.exists() else None,
        "rendered_video": rendered if rendered.exists() else None,
        "depth_images": depth_images,
    }


def run_reconstruction(
    photos_dir: Path,
    output_dir: Path,
    *,
    demo_mode: bool = True,
    pause_seconds: float = 0.6,
    config_path: Path | None = None,
    max_photos: int | None = None,
) -> Generator[dict, None, None]:
    """按步骤执行重建任务。demo_mode=False 时走 AutoDL 真推理。"""
    photos = list_photos(photos_dir)
    if max_photos and len(photos) > max_photos:
        photos = photos[:max_photos]

    ok, message = validate_photos(photos)
    yield {"level": "success" if ok else "error", "step": 1, "message": message}
    if not ok:
        return

    if demo_mode:
        yield from _run_demo(photos, output_dir, pause_seconds)
        return

    yield from _run_autodl(photos, output_dir, config_path)


def _run_demo(
    photos: list[Path],
    output_dir: Path,
    pause_seconds: float,
) -> Generator[dict, None, None]:
    yield {
        "level": "running",
        "step": 2,
        "message": f"步骤 2/4：整理输入数据（{len(photos)} 张航拍照片）...",
    }
    time.sleep(pause_seconds)

    yield {
        "level": "running",
        "step": 3,
        "message": "步骤 3/4：调用 HunyuanWorld-Mirror 三维重建（AutoDL A800）...",
    }
    time.sleep(pause_seconds * 1.5)
    yield {
        "level": "info",
        "step": 3,
        "message": "演示模式：使用已下载的重建结果（无需重新推理）",
    }

    yield {"level": "running", "step": 4, "message": "步骤 4/4：加载三维模型与附属结果..."}
    time.sleep(pause_seconds)
    yield from _finish_task(photos, output_dir)


def _run_autodl(
    photos: list[Path],
    output_dir: Path,
    config_path: Path | None,
) -> Generator[dict, None, None]:
    cfg_file = config_path or Path(__file__).parent / "config.toml"
    try:
        config = load_config(cfg_file)
    except FileNotFoundError as exc:
        yield {"level": "error", "step": 2, "message": str(exc)}
        return

    yield {
        "level": "running",
        "step": 2,
        "message": f"步骤 2/5：连接 AutoDL 并上传 {len(photos)} 张照片...",
    }

    ssh = None
    sftp = None
    try:
        ssh, sftp = connect(config)
        upload_photos(sftp, photos, config.remote_input)

        yield {
            "level": "success",
            "step": 2,
            "message": f"上传完成：{len(photos)} 张照片 → {config.remote_input}",
        }

        yield {
            "level": "running",
            "step": 3,
            "message": f"步骤 3/5：远程运行 {config.infer_script}（{len(photos)} 张，约需 10–30 分钟）...",
        }

        for line in run_remote_inference(ssh, config):
            if line.strip():
                yield {"level": "remote", "step": 3, "message": line}

        yield {"level": "success", "step": 3, "message": "远程推理完成"}

        yield {
            "level": "running",
            "step": 4,
            "message": "步骤 4/5：下载重建结果到本地...",
        }

        downloaded = download_results(sftp, config, output_dir)
        names = ", ".join(p.name for p in downloaded[:5])
        extra = f" 等 {len(downloaded)} 个文件" if len(downloaded) > 5 else ""
        yield {
            "level": "success",
            "step": 4,
            "message": f"下载完成：{names}{extra}",
        }

        yield {"level": "running", "step": 5, "message": "步骤 5/5：加载本地结果..."}
        yield from _finish_task(photos, output_dir, final_step=5)

    except Exception as exc:
        yield {"level": "error", "step": 3, "message": f"AutoDL 推理失败：{exc}"}
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()


def _finish_task(
    photos: list[Path],
    output_dir: Path,
    final_step: int = 4,
) -> Generator[dict, None, None]:
    results = collect_results(output_dir)
    ply_file = results["ply_file"]

    if ply_file is None:
        yield {
            "level": "error",
            "step": final_step,
            "message": "未找到 gaussians.ply，请确认推理和下载是否成功",
        }
        return

    size_mb = ply_file.stat().st_size / 1024 / 1024
    yield {
        "level": "success",
        "step": final_step,
        "message": f"重建完成！三维模型 gaussians.ply（{size_mb:.1f} MB）",
    }

    yield {
        "level": "done",
        "step": final_step,
        "message": "任务完成",
        "photos": photos,
        "results": results,
    }
