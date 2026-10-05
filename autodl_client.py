"""AutoDL SSH/SFTP 客户端：上传照片、远程推理、下载结果。"""

from __future__ import annotations

import posixpath
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Generator, Iterable

import paramiko


@dataclass
class AutoDLConfig:
    host: str
    port: int
    username: str
    password: str
    mirror_dir: str
    remote_input: str
    remote_output: str
    conda_env: str = "hunyuanworld-mirror"
    infer_script: str = "infer_plus.py"
    model_dir: str = "./ckpts"


def load_config(config_path: Path) -> AutoDLConfig:
    if not config_path.exists():
        raise FileNotFoundError(
            f"未找到 {config_path.name}，请复制 config.example.toml 为 config.toml 并填写 AutoDL 信息"
        )
    data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    autodl = data["autodl"]
    paths = data["paths"]
    return AutoDLConfig(
        host=autodl["host"],
        port=int(autodl["port"]),
        username=autodl["username"],
        password=autodl["password"],
        mirror_dir=paths["mirror_dir"],
        remote_input=paths["remote_input"],
        remote_output=paths["remote_output"],
        conda_env=paths.get("conda_env", "hunyuanworld-mirror"),
        infer_script=paths.get("infer_script", "infer_plus.py"),
        model_dir=paths.get("model_dir", "./ckpts"),
    )


def connect(config: AutoDLConfig) -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=config.host,
        port=config.port,
        username=config.username,
        password=config.password,
        timeout=30,
        banner_timeout=30,
        auth_timeout=30,
    )
    sftp = ssh.open_sftp()
    return ssh, sftp


def test_connection(config: AutoDLConfig) -> tuple[bool, str]:
    try:
        ssh, sftp = connect(config)
        mirror = config.mirror_dir
        infer_path = posixpath.join(mirror, config.infer_script)
        model_path = posixpath.join(mirror, config.model_dir.lstrip("./"))
        checks = [
            (f"test -d {mirror} && echo OK", f"项目目录不存在：{mirror}"),
            (f"test -f {infer_path} && echo OK", f"推理脚本不存在：{infer_path}"),
            (f"test -f {posixpath.join(model_path, 'model.safetensors')} && echo OK", f"本地模型不存在：{model_path}/model.safetensors"),
        ]
        for cmd, err_msg in checks:
            _, stdout, _ = ssh.exec_command(cmd)
            if stdout.read().decode().strip() != "OK":
                sftp.close()
                ssh.close()
                return False, err_msg
        sftp.close()
        ssh.close()
        return True, f"连接成功，已找到 {config.infer_script} 和本地模型"
    except Exception as exc:
        return False, f"连接失败：{exc}"


def _mkdir_p(sftp: paramiko.SFTPClient, remote_path: str) -> None:
    parts = PurePosixPath(remote_path).parts
    current = ""
    for part in parts:
        if not part or part == "/":
            current = "/"
            continue
        current = posixpath.join(current, part) if current != "/" else f"/{part}"
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def _clear_remote_dir(sftp: paramiko.SFTPClient, remote_dir: str) -> None:
    try:
        for entry in sftp.listdir_attr(remote_dir):
            remote_path = posixpath.join(remote_dir, entry.filename)
            if stat.S_ISDIR(entry.st_mode):
                _clear_remote_dir(sftp, remote_path)
                sftp.rmdir(remote_path)
            else:
                sftp.remove(remote_path)
    except OSError:
        pass


def upload_photos(
    sftp: paramiko.SFTPClient,
    photos: Iterable[Path],
    remote_dir: str,
    on_progress: Callable[[int, int, str], None] | None = None,
) -> None:
    _mkdir_p(sftp, remote_dir)
    _clear_remote_dir(sftp, remote_dir)

    photo_list = list(photos)
    total = len(photo_list)
    for index, photo in enumerate(photo_list, start=1):
        # Linux 上 infer.py 的 glob 区分大小写，统一用小写 .jpg
        remote_name = photo.stem + photo.suffix.lower()
        remote_path = posixpath.join(remote_dir, remote_name)
        sftp.put(str(photo), remote_path)
        if on_progress:
            on_progress(index, total, remote_name)


def _build_infer_command(config: AutoDLConfig) -> str:
    input_dir = config.remote_input
    output_dir = config.remote_output
    mirror_dir = config.mirror_dir
    conda_env = config.conda_env
    infer_script = config.infer_script
    return (
        "set -e && "
        "source /root/miniconda3/etc/profile.d/conda.sh && "
        f"conda activate {conda_env} && "
        f"cd {mirror_dir} && "
        f"python {infer_script} --input_path {input_dir} --output_path {output_dir}"
    )


def run_remote_inference(
    ssh: paramiko.SSHClient,
    config: AutoDLConfig,
) -> Generator[str, None, None]:
    command = _build_infer_command(config)
    _, stdout, stderr = ssh.exec_command(command, get_pty=True)

    while True:
        line = stdout.readline()
        if not line:
            break
        yield line.rstrip()

    exit_code = stdout.channel.recv_exit_status()
    err = stderr.read().decode(errors="replace").strip()
    if err:
        for err_line in err.splitlines():
            yield f"[stderr] {err_line}"

    if exit_code != 0:
        raise RuntimeError(f"远程 {config.infer_script} 失败，退出码 {exit_code}")


def _remote_result_dir(config: AutoDLConfig) -> str:
    input_name = PurePosixPath(config.remote_input.rstrip("/")).name
    return posixpath.join(config.remote_output, input_name)


def _download_file(sftp: paramiko.SFTPClient, remote_path: str, local_path: Path) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    sftp.get(remote_path, str(local_path))


def _download_tree(
    sftp: paramiko.SFTPClient,
    remote_dir: str,
    local_dir: Path,
    *,
    max_depth: int = 3,
    depth: int = 0,
) -> list[Path]:
    downloaded: list[Path] = []
    if depth > max_depth:
        return downloaded

    try:
        entries = sftp.listdir_attr(remote_dir)
    except OSError:
        return downloaded

    for entry in entries:
        remote_path = posixpath.join(remote_dir, entry.filename)
        local_path = local_dir / entry.filename
        if stat.S_ISDIR(entry.st_mode):
            local_path.mkdir(parents=True, exist_ok=True)
            downloaded.extend(
                _download_tree(sftp, remote_path, local_path, max_depth=max_depth, depth=depth + 1)
            )
        else:
            _download_file(sftp, remote_path, local_path)
            downloaded.append(local_path)
    return downloaded


def download_results(
    sftp: paramiko.SFTPClient,
    config: AutoDLConfig,
    local_output: Path,
) -> list[Path]:
    remote_dir = _remote_result_dir(config)
    local_output.mkdir(parents=True, exist_ok=True)

    priority_files = [
        "gaussians.ply",
        "pts_from_pointmap.ply",
        "rendered.mp4",
        "scene.glb",
    ]
    downloaded: list[Path] = []

    for name in priority_files:
        remote_path = posixpath.join(remote_dir, name)
        local_path = local_output / name
        try:
            sftp.stat(remote_path)
            _download_file(sftp, remote_path, local_path)
            downloaded.append(local_path)
        except OSError:
            continue

    for sub in ("depth", "normal"):
        remote_sub = posixpath.join(remote_dir, sub)
        local_sub = local_output / sub
        try:
            sftp.stat(remote_sub)
            downloaded.extend(_download_tree(sftp, remote_sub, local_sub, max_depth=1))
        except OSError:
            continue

    return downloaded
