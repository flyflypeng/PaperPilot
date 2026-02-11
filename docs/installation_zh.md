## 安装


<div align=center>
  <img src="https://github.com/user-attachments/assets/73d25cfa-5791-4b54-a131-d816f51afebb" >
  <div style="margin-top:8px; color: #555; font-size: 16px;">
    PaperPilot 采用前后端分离的架构
  </div>
</div>


- [安装](#安装)
    - [1. PaperPilot 架构概述](#1-paperpilot-架构概述)
    - [1.1. Local 端（PaperPilot Core - 主服务）](#11-local-端paperpilot-core---主服务)
    - [1.2. AI 端（可选 - AI 服务器）](#12-ai-端可选---ai-服务器)
  - [2. 安装 PaperPilot Local 端](#2-安装-paperpilot-local-端)
  - [3. 安装 PaperPilot AI 端（可选）](#3-安装-paperpilot-ai-端可选)
    - [3.1 部署 MinerU](#31-部署-mineru)
    - [3.2 配置 LLM 服务器](#32-配置-llm-服务器)


#### 1. PaperPilot 架构概述

PaperPilot 采用**双端分离架构**，包含两个独立的部署端：

#### 1.1. Local 端（PaperPilot Core - 主服务）

- **技术栈**：HTML + CSS + JavaScript + Python Flask
- **功能**：包含 PaperPilot 的所有核心功能
  - 论文管理（上传、分类、搜索）
  - 文献管理（树形分类、全文搜索、元数据管理）
  - 导入导出（Zotero 导入、JSON 导出）
  - 阅读历史追踪
  - 用户界面和交互
- **部署要求**：可以部署在任何机器上（无需 GPU）
- **依赖**：轻量级，不包含 AI 功能依赖
- **启动方式**：`python app.py --host 0.0.0.0 --port 7890`

#### 1.2. AI 端（可选 - AI 服务器）

- **功能**：提供 AI 增强功能
  - AI 翻译（PDF 双语翻译）
  - AI 解读（深度论文分析）
  - Daily arXiv（智能论文筛选）
- **组件**：
  - **LLM 服务器**：使用 lmdeploy 或 vllm 部署（推荐 Qwen3-4B-Instruct）
  - **MinerU 服务器**：用于 PDF 到 Markdown 解析（MinerU2.5-2509-1.2B 模型）
- **部署要求**：
  - 需要 GPU 支持（CUDA）
  - 可以部署在与 Local 端不同的机器上
  - 通过 API 与 Local 端通信
- **通信方式**：Local 端通过 HTTP API 调用 AI 端服务


### 2. 安装 PaperPilot Local 端

PaperPilot 使用 `uv` 进行依赖管理。

在需要运行 PaperPilot 主服务的机器上，安装本地端版本（不包含 AI 服务器依赖）：


<details open>
<summary><strong>Linux 端安装</strong></summary>

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 克隆仓库
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# 创建虚拟环境（推荐）
uv venv
source .venv/bin/activate
# 安装本地端版本（不包含 AI 服务器依赖）
uv pip install -e ".[local]"
```

</details>

<details close>
<summary><strong>Mac 端安装</strong></summary>

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc
# 克隆仓库
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# 创建虚拟环境（推荐）
uv venv
source .venv/bin/activate
# 安装本地端版本（不包含 AI 服务器依赖）
uv pip install -e ".[local]"
```

</details>

</details>

<details close>
<summary><strong>Windows 端安装</strong></summary>
以 PowerShell 安装为例


```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# 请将下方 USERNAME 替换为用户名
[System.Environment]::SetEnvironmentVariable("Path", "$env:Path;C:\Users\USERNAME\.local\bin", [System.EnvironmentVariableTarget]::User)
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', [System.EnvironmentVariableTarget]::User)
uv --version
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.venv\Scripts\activate.ps1
uv pip install -e ".[local]"
```

</details>

**启动 PaperPilot 主服务**

```bash
python app.py --papers-dir ./papers --host 0.0.0.0 --port 7890
```

参数说明：
- `--papers-dir`: 论文存储目录路径（默认: `./papers`）
- `--host`: 服务器监听地址（默认: `0.0.0.0`）
- `--port`: 服务器监听端口（默认: `7890`）

服务启动后，在浏览器中访问 `http://0.0.0.0:7890` 即可访问 PaperPilot 界面。

> **注意**：本地端安装不包含 AI 功能所需的依赖。如果你需要使用 AI 翻译、AI 解读等功能，需要：
> - 在另一台机器上部署 AI 服务器（见 1.2 节），或
> - 使用远程 AI API 服务（如 OpenAI、DeepSeek 等），在 PaperPilot 设置中配置 API 地址和密钥

### 3. 安装 PaperPilot AI 端（可选）

> **重要说明**：AI 服务器可以在与 PaperPilot 主服务不同的机器上部署。PaperPilot 主服务只需要这些 AI 服务器的 API 地址即可使用 AI 功能。你可以根据资源情况，将 AI 服务器部署在有 GPU 的机器上，而 PaperPilot 主服务可以部署在任何机器上。


在需要部署 MinerU 和 LLM 服务器的机器上（推荐有 GPU 的机器），安装服务器端版本：

<details open>
<summary><strong>Linux 端安装</strong></summary>

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh
# 克隆仓库
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# 创建虚拟环境（推荐）
uv venv
source .venv/bin/activate
# 安装本地端版本（不包含 AI 服务器依赖）
uv pip install -e ".[server]"
```

</details>

<details close>
<summary><strong>Mac 端安装</strong></summary>

```bash
# 安装 uv（如果尚未安装）
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc
# 克隆仓库
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# 创建虚拟环境（推荐）
uv venv
source .venv/bin/activate
# 安装本地端版本（不包含 AI 服务器依赖）
uv pip install -e ".[server]"
```

</details>

</details>

<details close>
<summary><strong>Windows 端安装</strong></summary>
以 PowerShell 安装为例


```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# 请将下方 USERNAME 替换为用户名
[System.Environment]::SetEnvironmentVariable("Path", "$env:Path;C:\Users\USERNAME\.local\bin", [System.EnvironmentVariableTarget]::User)
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', [System.EnvironmentVariableTarget]::User)
uv --version
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.venv\Scripts\activate.ps1
uv pip install -e ".[server]"
```

</details>

PaperPilot 的 AI 功能（**AI 翻译**、**AI 解读**、**Daily arXiv**）依赖于以下服务：

- **LLM API Access**：用于论文翻译、解读生成和 arXiv 论文智能分析
- **MinerU 服务**：用于将 PDF 解析为 Markdown 格式，支持高质量的文档结构识别

以下是详细的部署步骤：

#### 3.1 部署 MinerU

MinerU 用于将 PDF 文档解析为结构化的 Markdown 格式，是 AI 解读功能的基础。

您有两种方式使用 MinerU：

**方式一：使用 MinerU 官方云端 API（推荐，快速上手）**

这是最简单的方式，无需 GPU 支持：

1. **获取 API Token**：访问 [https://mineru.net/](https://mineru.net/) 注册并获取您的 API Token
2. **在 PaperPilot 中配置**：
   - 进入设置 → Agentic 标签页
   - 在 "MinerU 模式" 下选择 "Cloud API"
   - 输入您的 API Token
   - 点击 "Test" 验证连接
   - 保存设置

完成！您现在可以使用 MinerU 的云端服务进行 PDF 解析，无需任何本地部署。

**方式二：本地部署 MinerU（需要 GPU）**

如果您希望在自己的服务器上部署 MinerU：

**Step1: 下载 MinerU2.5 模型**

MinerU 需要下载对应的模型文件。模型文件应放置在 `ai_server/` 目录下：

```bash
mkdir ai_server
# download from huggingface
huggingface-cli download opendatalab/MinerU2.5-2509-1.2B --local-dir ai_server/MinerU2.5-2509-1.2B

# or donwload from modelscope (for chinese users)
uv add modelscope
modelscope download opendatalab/MinerU2.5-2509-1.2B --local_dir ai_server/MinerU2.5-2509-1.2B
```

**Step2. 启动 MinerU vLLM 服务器**

```bash
mineru-vllm-server \
  --model ai_server/MinerU2.5-2509-1.2B \
  --host 0.0.0.0 \
  --port 6001
```

MinerU 将会在 `http://0.0.0.0:6001` 启动一个 API 服务器，用于将 PDF 解析为 Markdown 格式。

**Step3. 在 PaperPilot 中配置**：
- 进入设置 → Agentic 标签页
- 在 "MinerU 模式" 下选择 "Local Deployment"
- 输入您的 MinerU 服务器地址（如：`http://0.0.0.0:6001`）
- 点击 "Test" 验证连接
- 保存设置

> **注意**：MinerU 服务器需要 GPU 支持。如果使用 CPU 推理，请参考 [MinerU 官方文档](https://github.com/opendatalab/MinerU?tab=readme-ov-file#local-deployment) 进行配置。

#### 3.2 配置 LLM 服务器

PaperPilot 的 AI 功能需要访问 LLM API。你可以使用以下两种方式之一：

**方式一：使用本地部署的 LLM（推荐）**

使用 `lmdeploy` 或 `vllm` 部署本地 LLM 模型。在我们的实际测试中，采用 `Qwen3-4B-Instruct` 作为基座模型即可取得较好的效果


**Step1: 下载模型权重**

```bash
# download from huggingface
mkdir ai_server
huggingface-cli download Qwen/Qwen3-4B-Instruct-2507 --local-dir ai_server/Qwen3-4B-Instruct-2507

# or donwload from modelscope (for chinese users)
# 如果你安装了 paperpilot[server]，modelscope 已经包含在内
modelscope download Qwen/Qwen3-4B-Instruct-2507 --local_dir ai_server/Qwen3-4B-Instruct-2507
```

**Step2: 启动 LLM 服务器**

```bash
# 单 GPU 部署示例（4B 模型）
vllm serve ai_server/Qwen3-4B-Instruct-2507 \
  --api-key token-abc123 \
  --host 0.0.0.0 \
  --port 6002 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.6 \
```

**方式二：使用远程 LLM API**

如果你使用 OpenAI、DeepSeek、OpenRouter 等远程 API 服务，可以直接在 PaperPilot 设置中配置 API 地址和密钥，无需本地部署