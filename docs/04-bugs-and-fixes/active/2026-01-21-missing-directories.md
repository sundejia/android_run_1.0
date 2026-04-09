# 图片和头像目录缺失问题分析

## 问题描述

项目部署到新工作电脑后，发现 `conversation_images` 和 `avatars` 目录不存在，导致图片和头像无法保存。

> 更新说明（2026-04-02）：这份文档最初假设同步媒体默认写入项目根目录的 `conversation_*`。当前同步启动链路已调整为默认写入 `device_storage/<serial>/conversation_images|conversation_videos|conversation_voices`。因此，这里的“根目录 conversation\_\* 缺失”仅适用于旧流程或显式自定义输出目录；对当前默认同步流程，更应该检查 `device_storage/<serial>/...` 是否存在。

## 问题原因分析

### 1. 目录创建时机问题

这些目录应该在以下情况创建：

| 目录                                           | 创建时机                     | 代码位置                                |
| ---------------------------------------------- | ---------------------------- | --------------------------------------- |
| `avatars/`                                     | `AvatarManager.__init__()`   | `avatar.py`                             |
| `device_storage/<serial>/conversation_images/` | 同步启动时解析并在运行期创建 | `device_manager.py` / `initial_sync.py` |
| `device_storage/<serial>/conversation_videos/` | 同步启动时解析并在运行期创建 | `device_manager.py` / `initial_sync.py` |
| `device_storage/<serial>/conversation_voices/` | 同步启动时解析并在运行期创建 | `device_manager.py` / `initial_sync.py` |

### 2. 可能的问题点

#### a) 相对路径问题

旧逻辑默认配置使用相对路径：

```python
images_dir = images_dir or "conversation_images"  # 旧相对路径
```

当前同步链路已把默认媒体输出切换为按设备隔离的 `device_storage/<serial>/...`，这样可以避免多设备并发时共用一个输出根目录。

#### b) 权限问题

在某些 Windows 环境下，可能没有权限在程序目录创建子目录。

#### c) 首次运行未执行到目录创建代码

目录只有在需要时才创建。如果 FollowUp 系统没有执行到保存图片的代码，目录就不会创建。

## 解决方案

### 方案 1: 应用启动时预创建目录（推荐）

在后端 `main.py` 启动时预先创建公共目录，在同步启动链路里按设备解析运行期媒体目录：

```python
# wecom-desktop/backend/main.py

from pathlib import Path

def ensure_directories():
    """在应用启动时确保所有必需目录存在"""
    project_root = Path(__file__).parent.parent

    directories = [
        project_root / "avatars",
        project_root / "conversation_images",   # 兼容旧流程/显式自定义路径
        project_root / "conversation_videos",   # 兼容旧流程/显式自定义路径
        project_root / "conversation_voices",   # 兼容旧流程/显式自定义路径
    ]

    for dir_path in directories:
        dir_path.mkdir(parents=True, exist_ok=True)
        print(f"✓ Ensured directory exists: {dir_path}")

# 在 app 启动时调用
ensure_directories()
```

### 方案 2: 立即手动创建目录

如果你在排查旧流程或手工运行脚本导致的目录缺失，可在项目根目录中运行：

```powershell
# PowerShell
New-Item -ItemType Directory -Force -Path avatars
New-Item -ItemType Directory -Force -Path conversation_images
New-Item -ItemType Directory -Force -Path conversation_videos
New-Item -ItemType Directory -Force -Path conversation_voices
```

## 代码修复

当前需要同时确认两类目录：

1. 公共目录：`avatars/`、`logs/`
2. 当前设备运行目录：`device_storage/<serial>/conversation_*`

## 相关文件

| 文件                                               | 说明                                                             |
| -------------------------------------------------- | ---------------------------------------------------------------- |
| `wecom-desktop/backend/main.py`                    | 后端入口，预创建公共目录                                         |
| `wecom-desktop/backend/services/device_manager.py` | 多设备同步启动，解析按设备隔离的输出目录                         |
| `wecom-desktop/backend/scripts/initial_sync.py`    | 同步子进程入口，接收并展开 `output_root` / `conversation_*` 路径 |
| `src/wecom_automation/services/user/avatar.py`     | 头像管理器                                                       |

## 验证步骤

1. 启动后端服务
2. 检查项目根目录下是否存在以下公共目录：
   - `avatars/`
   - `logs/`
3. 启动一个实际设备同步，检查 `device_storage/<serial>/` 下是否存在：
   - `conversation_images/`
   - `conversation_videos/`
   - `conversation_voices/`
4. 执行同步或 FollowUp，验证图片/头像能否正常保存
