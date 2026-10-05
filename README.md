# 城市路口三维场景重建智能体

> Urban Intersection 3D Reconstruction Agent — 基于腾讯混元世界模型（HunyuanWorld-Mirror）的城市路口三维场景智能重建工具

输入无人机多视角航拍照片，一键完成三维场景重建，并在浏览器中展示 3D 高斯模型、点云、深度图与新视角渲染视频。适用于智慧交通数字孪生、自动驾驶仿真场景构建等场景。

---

## 项目简介

本工具面向「城市路口」这一典型动态交通场景，将多视角航拍照片送入 AutoDL GPU 云平台上的 **HunyuanWorld-Mirror（混元世界模型）** 进行三维重建，产出：

- `gaussians.ply` —— 3D 高斯泼溅（3D Gaussian Splatting）模型，可在 SuperSplat 等查看器中交互浏览；
- `pts_from_pointmap.ply` —— 稠密点云；
- `rendered.mp4` —— 新视角渲染视频；
- `depth/`、`normal/` —— 深度图与法线图。

项目是国家自然科学基金重点项目“超大规模多模式交通系统仿真关键技术与软件研发”课题一数据模型子课题「面向自动驾驶仿真训练的典型动态交通场景重建」的工程实现子项目之一，重点验证**世界模型驱动的城市路口场景重建闭环**。

## 技术栈

| 层次 | 技术 |
| --- | --- |
| 语言 / 运行时 | Python 3.13 |
| 前端交互 | Streamlit |
| 远程调用 | paramiko（SSH / SFTP） |
| 云端推理 | AutoDL GPU 云平台（A800）+ HunyuanWorld-Mirror |
| 三维表示 | 3D Gaussian Splatting（`.ply`）、稠密点云 |
| 内网穿透 | Cloudflare Tunnel（cloudflared） |
| 配置管理 | TOML（`tomllib`） |

## 架构设计

项目采用三层解耦结构，职责单一、易于维护与测试：

```
app.py            —— 界面层（Streamlit UI、上传/展示/下载）
agent.py          —— 编排层（任务步骤编排，生成器流式返回日志）
autodl_client.py  —— 基础设施层（SSH/SFTP 连接、远程推理、结果下载）
```

## 实现流程

```
1. 照片校验  —— 校验多视角照片数量（≥8 张）与格式
2. 连接上传  —— SSH 连接 AutoDL，SFTP 上传照片到远程输入目录
3. 远程推理  —— conda 激活 hunyuanworld-mirror，执行 python infer_plus.py
4. 结果下载  —— SFTP 拉取 gaussians.ply / 点云 / rendered.mp4 / depth / normal
5. 本地展示  —— Streamlit 页面展示并支持下载、跳转 SuperSplat 查看
```

同时提供**演示模式（demo_mode）**：不连接 GPU，直接加载本地已有重建结果，便于离线演示与课程验收。

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
pip install -r requirements.txt

# 2. 准备配置文件（填入 AutoDL 实例信息）
cp config.example.toml config.toml

# 3. 启动界面
streamlit run app.py

# 4.（可选）创建公网临时链接分享给他人
start_share.bat   # 依赖 tools/cloudflared.exe
```

## 目录结构

```
intersection_project/
├── app.py              # Streamlit 界面
├── agent.py            # 重建任务编排
├── autodl_client.py    # AutoDL SSH/SFTP 客户端
├── config.example.toml # 配置模板（占位符）
├── requirements.txt    # 依赖清单
├── pack_source.ps1     # 源码打包脚本（毕设归档用）
├── start_share.bat     # 一键启动 + cloudflared 公网分享
├── photos/             # 多视角航拍照片（示例数据）
└── output/             # 重建结果输出目录
```

## 安全说明

- `config.toml` 包含 AutoDL 实例凭据，**严禁提交到版本库**（已在 `.gitignore` 中排除）；
- 请使用 `config.example.toml` 作为模板自行填写；
- `photos/` 原始航拍照片可能含 GPS EXIF 元数据，公开分享前建议脱敏或仅放少量示例图。

## 项目背景

　　本人参与东南大学交通学院国家自然科学基金重点项目“超大规模多模式交通系统仿真关键技术与软件研发”。课题1数据模型子课题的工程实现子项目，核心思想为：**利用生成式世界模型的多模态先验，将真实城市路口航拍数据重建为可交互、可编辑的三维场景资产**，服务于交通数字孪生与端到端自动驾驶仿真训练。

