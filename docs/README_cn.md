<div align="center" xmlns="http://www.w3.org/1999/html">
<!-- logo -->
<p align="center">
  <img src="https://github.com/user-attachments/assets/d6472d7d-fce6-4c86-814e-2d490255e85a" width="500px" style="vertical-align:middle;">
</p>

<p align="center">


  <!-- Stars Badge -->
  <img src="https://img.shields.io/github/stars/Mountchicken/Resophy?style=social&color=D3C1D9" alt="Stars">

  <!-- Forks Badge -->
  <img src="https://img.shields.io/github/forks/Mountchicken/Resophy?style=social&color=D3C1D9" alt="Forks">

  <!-- Open Issues Badge -->
  <a href="https://github.com/Mountchicken/Resophy/issues">
    <img src="https://img.shields.io/github/issues-raw/Mountchicken/Resophy?color=D3C1D9" alt="Open Issues">
  </a>

  <!-- Issue Resolution Badge -->
  <a href="https://github.com/Mountchicken/Resophy/issues">
    <img src="https://img.shields.io/github/issues-closed-raw/Mountchicken/Resophy?color=32CD32" alt="Issue Resolution">
  </a>

  <!-- Pull Requests Badge -->
  <img src="https://img.shields.io/github/issues-pr/Mountchicken/Resophy?color=FFFF00" alt="Pull Requests">

  <!-- Platform Support Badge (Windows, Mac, Linux) with Light Green -->
  <img src="https://img.shields.io/badge/Platform-Windows%2C%20Mac%2C%20Linux-D3C1D9" alt="Platform Support">

  <!-- UV Installation Badge (Custom) -->
  <img src="https://img.shields.io/badge/Install-UV-D3C1D9?style=flat" alt="UV Installation">

  <img src="https://img.shields.io/badge/License-CC%20BY--NC%204.0-FFCDC9" alt="License">
</p>


[English](docs/README_en.md) | [简体中文](README.md) | [安装文档](installation_zh.md)

<span style="color:rgb(154, 46, 222);">***Resophy 所有代码都采用 Cusor (Sonnet 4.5/Auto) 生成，人工校验的方式搭建***</span>

</div>

----


[![Video Name](https://github.com/user-attachments/assets/bced2c0f-0d4c-4c5d-a264-47bfc533ca31)](https://github.com/user-attachments/assets/13bfb7ab-a9b6-4f09-86c2-c513a6a8f221)

----

# Resophy

## 🆕 最新动态

**MinerU 官方 API 支持**：Resophy 现已支持 MinerU 官方云端 API！您可以使用 MinerU 的云端服务进行 PDF 解析，无需部署自己的 MinerU 服务器。只需在设置 → Agentic → MinerU 模式中选择"Cloud API"，并输入从 [https://mineru.net/](https://mineru.net/) 获取的 API Token 即可。这使得无需 GPU 也能轻松使用 AI 解读功能。

---

在如今信息爆炸的时代，科研人员面对海量的论文，常常感到疲惫不堪。如何快速获取精华、理解前沿成果，成了每个研究者的痛点。Resophy 诞生的初衷就是要让你告别低效的论文阅读，赋能科研者，让读论文变得更高效、更智能📚⚡。

Resophy 是一个完全开源、Vibe Coding 导向的现代论文阅读器，它通过简洁的技术栈（HTML + JavaScript + Python Flask）和 AI 功能，帮助你快速理解论文的核心内容🤖💡。从自动翻译到论文解析，从智能推荐到一键导入 Zotero，Resophy 一站式解决你的论文阅读需求📑✨。最重要的是，你可以随时通过 **Vibe Coding** 的方式自定义功能，打造成专属于你的论文助手🎨🛠️。


#### 🚀 核心功能



<div align="center" xmlns="http://www.w3.org/1999/html">
<!-- logo -->
<p align="center">
  <img src="https://github.com/user-attachments/assets/76507160-fbbe-44cd-bd0f-8905fdd3611c"  style="vertical-align:middle;">
</p>
</div>


----

## 目录

- [Resophy](#resophy)
      - [🚀 核心功能](#-核心功能)
  - [目录](#目录)
  - [1. 安装](#1-安装)
  - [2. 快速上手](#2-快速上手)
    - [2.1 ⚙️ 第一步，进行初始配置](#21-️-第一步进行初始配置)
      - [📸 用户设置（User Settings）](#-用户设置user-settings)
      - [🤖 Agentic 设置（AI 功能配置）](#-agentic-设置ai-功能配置)
      - [📰 Daily arXiv 设置](#-daily-arxiv-设置)
      - [📥 从 Zotero 导入](#-从-zotero-导入)
    - [2.2 基本操作](#22-基本操作)
    - [2.3. AI 翻译](#23-ai-翻译)
    - [2.4 AI 解读](#24-ai-解读)
    - [2.5. Daily arXiv](#25-daily-arxiv)
  - [3. 💻 Vibe Coding](#3--vibe-coding)
    - [🚀 开始 Vibe Coding](#-开始-vibe-coding)
      - [第一步：让 AI 理解代码库](#第一步让-ai-理解代码库)
      - [第二步：描述你的需求](#第二步描述你的需求)
    - [📁 项目结构](#-项目结构)
    - [💡 编写 Prompt 的技巧](#-编写-prompt-的技巧)
    - [🎨 自定义示例](#-自定义示例)
    - [⚠️ 注意事项](#️-注意事项)
  - [4. LICENSE](#4-license)

----

## 1. 安装

<div align=center>
  <img src="https://github.com/user-attachments/assets/73d25cfa-5791-4b54-a131-d816f51afebb">
  <div style="margin-top:8px; color: #555; font-size: 16px;">
    Resophy 采用前后端分离的架构
  </div>
</div>


1. **主服务（Resophy Core）**：HTML + JavaScript + Python Flask 后端服务，提供论文管理、分类、搜索等核心功能
2. **AI 服务** 包括：
   - **LLM 服务器**：用于 AI 翻译、解读和 arXiv 论文分析的 LLM 推理服务（可选，支持本地部署或远程 API）
   - **MinerU 服务器**：用于 PDF 到 Markdown 解析的文档解析服务（可选，用于 AI 功能）
  
Resophy 使用 `uv` 进行依赖管理，支持分离部署架构。你可以将 Resophy 主服务和 AI 服务器部署在不同的机器上。安装和配置说明，请参考：

<div align="center">
  <table>
    <thead>
      <tr>
        <th>系统</th>
        <th>文档</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Windows / Mac / Linux</td>
        <td><a href="installation_zh.md">安装文档</a></td>
      </tr>
    </tbody>
  </table>
</div>

---- 

## 2. 快速上手

在这一节，我们简要介绍一些 Resophy 的使用方法


### 2.1 ⚙️ 第一步，进行初始配置

<div align=center>
  <img src="https://github.com/user-attachments/assets/6cc2292a-d3df-45d2-8bda-15f9edd13189">
  <div style="margin-top:8px; color: #555; font-size: 16px;">
    第一步，设置参数以及从 Zotero 进行论文迁移
  </div>
</div>


<div align="center">

| 配置模块 | 位置 | 主要功能 | 使用方法 |
|---------|------|---------|---------|
| **📸 用户设置** | 设置界面 → "User" 标签页 | • 头像上传<br>• 用户名设置<br>• 阅读热力图颜色主题<br>• 最近阅读记录 | 1. 点击界面右上角头像<br>2. 进入 "User" 标签页<br>3. 上传头像、设置用户名、选择颜色<br>4. 设置自动保存 |
| **🤖 Agentic 设置** | 设置界面 → "Agentic" 标签页 | • LLM API 配置（模型名、URL、密钥）<br>• MinerU 服务器配置<br>• AI 解读提示词自定义 | 1. 进入 "Agentic" 标签页<br>2. 配置 LLM API 和 MinerU 地址<br>3. （可选）自定义提示词<br>4. 测试连接并保存 |
| **📰 Daily arXiv** | 设置界面 → "Daily arXiv" 标签页 | • arXiv 分区配置（cs.CV、cs.AI 等）<br>• 抓取设置（保留天数、检查间隔）<br>• 关键词列表（用于智能分类）<br>• 机构配置 | 1. 进入 "Daily arXiv" 标签页<br>2. 添加 arXiv 分区<br>3. 配置抓取参数和关键词<br>4. （可选）添加自定义机构<br>5. 保存设置 |
| **📥 Zotero 导入** | 设置界面 → "Import" 标签页 | • 目标目录选择<br>• RDF 文件拖拽上传<br>• 导入进度显示<br>• 导入结果统计 | 1. 在 Zotero 中导出为 RDF 格式<br>2. 进入 "Import" 标签页<br>3. （可选）选择目标目录<br>4. 拖拽 RDF 文件上传<br>5. 查看导入进度和结果 |

</div>

<details open>
<summary><strong>展开详细介绍</strong></summary>


#### 📸 用户设置（User Settings）

**功能详情**：
- **头像上传**：点击头像区域上传自定义头像，支持预览和裁剪
- **用户名设置**：输入用户名（默认：Paper Reader）
- **阅读热力图颜色**：选择颜色主题（绿色/蓝色/玫瑰粉），用于可视化每日阅读时间
- **最近阅读记录**：显示最近阅读的论文列表，快速访问历史记录

#### 🤖 Agentic 设置（AI 功能配置）

**功能详情**：
- **LLM API 配置**：
  - Model Name：输入模型名称（如：`Qwen3-4B-Instruct-2507`）
  - Base URL：输入 API 地址（本地：`http://0.0.0.0:6002/v1` 或远程 API）
  - API Key：输入访问密钥
  - 测试按钮：验证 API 连接
- **MinerU 配置**：
  - **模式选择**：选择 "Local Deployment"（本地部署）或 "Cloud API"（云端 API）
  - **本地部署**：输入服务器地址（如：`http://0.0.0.0:6001`），用于自建 MinerU 服务器
  - **云端 API**：输入从 [https://mineru.net/](https://mineru.net/) 获取的 API Token，使用 MinerU 云端服务
  - 测试按钮：验证连接（服务器或 API Token）
- **AI 解读提示词**：大型文本编辑器，可自定义 System Prompt，控制 AI 解读生成风格

**用途**：统一的 AI 功能配置，用于翻译、解读、Daily arXiv 等所有 AI 功能

#### 📰 Daily arXiv 设置

**功能详情**：
- **arXiv 分区配置**：添加/删除分区标签（cs.CV、cs.AI 等），提供常用分区快捷按钮
- **抓取设置**：论文保留天数（1-30 天）、检查间隔（5-60 分钟）
- **关键词列表**：添加关键词标签，设置最多关键词数（1-3），用于 AI 自动分类
- **机构配置**：添加自定义机构，支持编辑缩写和全称变体

#### 📥 从 Zotero 导入

**功能详情**：
- **目标目录选择**：下拉菜单选择导入位置（可选，默认根目录）
- **文件上传区域**：大型拖拽上传区，支持拖拽 `.rdf` 文件
- **导入进度显示**：进度条、状态文本、取消按钮
- **导入结果统计**：成功/失败/跳过/重复数量

**使用步骤**：
1. 在 Zotero 中导出文献库为 RDF 格式
2. 在 Resophy 设置界面进入 "Import" 标签页
3. （可选）选择目标目录
4. 拖拽 RDF 文件到上传区域
5. 系统自动解析并导入论文，显示导入进度和结果

</details>

### 2.2 基本操作

<details open>
<summary><strong>查看基本操作</strong></summary>


| 操作模块 | 主要功能 | 使用方法 |
|---------|---------|---------|
| **📚 论文管理** | • 上传论文（拖拽 PDF 或输入 arXiv URL）<br>• 分类管理（创建/重命名/删除分类，移动论文）<br>• 全文搜索（标题、作者、摘要） | 1. 拖拽 PDF 到上传区域或输入 arXiv URL<br>2. 左侧分类树管理分类结构<br>3. 顶部搜索框进行全文搜索 |
| **📖 论文查看** | • 查看论文详情<br>• PDF 阅读器<br>• 自动记录阅读时间 | 1. 点击论文卡片进入详情页<br>2. 查看元数据和摘要<br>3. 点击 "查看 PDF" 打开阅读器 |
| **✏️ 元数据管理** | • 编辑论文信息（标题、作者、摘要等）<br>• 添加备注和标签<br>• 管理 BibTeX 引用<br>• 设置链接（GitHub、主页） | 1. 进入论文详情页<br>2. 点击 "编辑" 按钮<br>3. 修改信息并保存 |
| **📈 阅读历史** | • 自动记录阅读时间<br>• 阅读热力图（可视化每日阅读统计）<br>• 最近阅读记录 | 在用户设置中查看阅读热力图和最近阅读列表 |
| **📥 导出功能** | • 导出论文库为 JSON 格式<br>• 包含元数据和分类结构 | 1. 进入设置界面<br>2. 选择导出范围<br>3. 下载 JSON 文件 |



**📝 论文元数据自动获取**：

当上传论文时（通过 arXiv URL 或拖拽 PDF），系统会自动获取论文元数据：

1. **通过 arXiv API 获取基本信息**：
   - 调用 arXiv API 获取论文的标题（title）、作者（authors）、摘要（abstract）、年份（year）等信息
   - 下载 PDF 文件

2. **通过 DBLP API 获取 BibTeX**：
   - 使用论文标题和作者信息调用 DBLP API
   - 尝试获取更准确的 BibTeX 引用格式
   - 如果 DBLP 获取成功，则使用 DBLP 的 BibTeX；否则使用 arXiv 的 BibTeX

3. **拖拽上传 PDF 的处理流程**：
   - 系统会尝试从文件名或 PDF 元数据中提取 arXiv ID
   - 如果找到 arXiv ID，则调用 arXiv API 获取信息
   - 后台异步调用 DBLP API 更新 BibTeX
  
</details>

### 2.3. AI 翻译

<details open>
<summary><strong>查看 AI 翻译</strong></summary>


**实现方式**：

Resophy 的 AI 翻译功能使用 [Babeldoc](https://github.com/funstory-ai/BabelDOC) 工具实现 PDF 双语翻译：

1. **调用 babeldoc**：
   - 传入配置的 LLM API 信息（模型、URL、密钥）

2. **翻译流程**：
   - babeldoc 读取原始 PDF 文件
   - 调用 LLM API 进行翻译（支持 OpenAI 兼容接口）
   - 生成双语对照 PDF（`.zh.dual.pdf`），原版和中文翻译并排显示

**使用方法**：
1. 在主界面选择一篇论文
2. 点击 "AI 翻译" 按钮
3. 系统后台执行翻译任务
4. 翻译完成后可在论文详情页查看双语 PDF

</details>


### 2.4 AI 解读

<details open>
<summary><strong>查看 AI 解读</strong></summary>

**实现方式**：

Resophy 的 AI 解读功能采用两步流程，深度分析论文内容：

1. **PDF 解析为 Markdown**：
   - 使用 [MinerU](https://github.com/opendatalab/MinerU) 工具将 PDF 解析为结构化 Markdown
   - 支持两种模式：
     - **云端 API**：使用 MinerU 官方云端服务（无需 GPU，配置简单）
     - **本地部署**：连接到自建的 MinerU 服务器（支持 vLLM 部署）
   - 保留图片、表格等元素，生成高质量的 Markdown 文档

2. **LLM 深度解读**：
   - 使用 `openai` 库调用 LLM API（支持 OpenAI 兼容接口）
   - 将 Markdown 内容作为输入，结合自定义 System Prompt
   - LLM 生成结构化解读报告（摘要、方法、实验、结论等）
   - 支持自定义提示词，控制解读风格和内容格式

**使用方法**：
1. 选择一篇论文，点击 "AI 解读" 按钮
2. 系统启动后台任务：
   - 第一步：MinerU 解析 PDF 为 Markdown
   - 第二步：LLM 深度分析并生成解读报告
3. 在 "解读任务" 页面查看进度和日志
4. 解读完成后，点击论文进入解读视图查看详细分析

</details>

### 2.5. Daily arXiv

<details open>
<summary><strong>查看 Daily arXiv 功能</strong></summary>

**实现方式**：

Daily arXiv 功能自动爬取最新 arXiv 论文，并使用 AI 进行智能分析和筛选：

1. **论文爬取**：
   - 使用 `arxiv` Python 库爬取指定分区的论文
   - 支持定时自动检查（可配置检查间隔）
   - 按日期和分区组织论文

2. **AI 功能应用**：

   **a. 机构信息提取**：
   - 使用 `openai` 库调用 LLM API
   - 从 PDF 第一页文本中提取机构名称（affiliations）
   - 提取机构所在国家（countries）
   - 提取项目主页（homepage）和 GitHub 仓库 URL
   - 支持机构名称标准化和缩写识别

   **b. 摘要总结和关键词提取**：
   - 使用 `openai` 库调用 LLM API
   - 从论文英文摘要生成中文总结（100-200 字）
   - 从预设关键词列表中选择最能代表论文类型的关键词（1-3 个）
   - 关键词用于后续的智能筛选和分类

3. **智能筛选**：
   - 根据配置的关键词列表筛选论文
   - 根据机构信息筛选论文
   - 支持自定义机构映射和标准化

4. **后台任务**：
   - 定时自动检查新论文（可配置间隔）
   - 后台下载 PDF 文件
   - 异步执行 AI 分析任务
   - 自动清理过期论文（可配置保留天数）

**使用方法**：
1. 在设置中配置 arXiv 分区（如 cs.CV、cs.AI）
2. 设置关键词列表和筛选条件
3. 点击 "Daily arXiv" 按钮获取今日论文
4. 系统自动爬取、下载、分析论文
5. 浏览匹配的论文列表，批量导入到阅读列表

</details>

----

### 2.6 用户注册与登录（基于 Supabase）

Resophy 现已支持通过 Supabase Auth 实现用户注册与登录，并在后端对所有 `/api/*` 路由进行会话鉴权（必须携带 `Authorization: Bearer <access_token>`）。以下为配置与使用指南。

#### 一、准备工作（在 Supabase 控制台）
- 创建一个 Supabase Project
- 获取以下两项：
  - `SUPABASE_URL`（形如 `https://xxxx.supabase.co`）
  - `SUPABASE_ANON_KEY`（anon/publishable key）
- 配置邮箱确认跳转（保证邮件确认后的跳转正确）：
  - 控制台 → Authentication → URL Configuration
    - Site URL：设置为 `http://127.0.0.1:7191`（或你的实际域名/端口）
    - Redirect URLs：添加 `http://127.0.0.1:7191/*` 与 `http://localhost:7191/*`
  - 这样邮件里的确认链接会跳回 Resophy 的端口，而不是默认的 `localhost:3000`
- 是否允许公开注册（可选）：
  - 控制台 → Authentication → Providers → Email → Email Signups
  - 开启：任何人都可注册；关闭：仅已存在用户可登录（页面上 Sign Up 会提示被拒绝）

#### 二、后端环境变量（必须）
Resophy 后端会把 Supabase 配置注入到前端，并通过 Supabase 的 `/auth/v1/user` 接口校验会话 token。请在启动服务前设置：

```bash
export SUPABASE_URL="https://xxxx.supabase.co"
export SUPABASE_ANON_KEY="你的anon_key"
python app.py --port 7191 --debug
```

说明：
- 前端的 Supabase 客户端会自动从后端注入的变量中读取这两个值（无需手动改前端文件）。
- 后端在 `@app.before_request` 拦截所有 `/api/*`，要求带 `Authorization: Bearer <access_token>`，否则返回 `401 未登录`。

#### 三、前端使用方法
- 打开首页后会看到登录弹窗：
  - Log In：邮箱 + 密码登录，成功后自动加载主界面并对所有 `/api/*` 请求注入 Bearer token
  - Sign Up：邮箱 + 密码注册（受 Supabase 控制台“公开注册”开关影响）
- 邮件确认跳转地址：
  - 注册时前端会传入 `emailRedirectTo = window.location.origin + '/'`
  - 同时需确保 Supabase 控制台的 Site URL/Redirect URLs 已按上文“一、准备工作”配置

#### 四、后端鉴权行为
- 所有 `/api/*` 请求均需携带 `Authorization: Bearer <access_token>`
- 后端使用 `SUPABASE_URL` + `SUPABASE_ANON_KEY` 调用 Supabase 的 `/auth/v1/user` 校验 token，并做 60 秒缓存
- 未配置这两个变量时，接口会返回 `500` 并提示需要配置

#### 五、常见问题与排查
- 点击邮件确认链接跳到 `localhost:3000`：未在 Supabase 控制台正确配置 Site URL/Redirect URLs；请参考上文“一、准备工作”
- 登录后接口仍返回 `401 未登录`：前端未拿到 session 或未为 `/api/*` 注入 token；强制刷新页面（Ctrl+F5/Cmd+Shift+R）后重试
- 注册按钮提示被拒绝：Supabase 控制台关闭了 Email Signups；根据需要打开或保留关闭

## 3. 💻 Vibe Coding

Resophy 采用 **Vibe Coding** 的开发理念，这意味着你可以通过自然语言与 AI Coding Agent 对话，轻松自定义和扩展功能。无需深入了解复杂的代码结构，只需描述你的需求，AI 就能帮你实现。

[![Video Name](https://github.com/user-attachments/assets/bced2c0f-0d4c-4c5d-a264-47bfc533ca31)](https://github.com/user-attachments/assets/a7c218eb-f045-4b59-9076-fff93e5e4861)

<div align="center">
  <div style="margin-top:8px; color: #555; font-size: 14px;">
    点击观看 Vibe Coding 演示视频
  </div>
</div>

### 🚀 开始 Vibe Coding

使用 Vibe Coding 自定义功能非常简单，只需两步：

#### 第一步：让 AI 理解代码库

在与 Coding Agent 对话时，首先输入以下 prompt：

```
请理解这个论文阅读平台的功能
```

这个 prompt 会让 AI 自动分析整个代码库的结构、功能和实现方式，建立对项目的全面理解。AI 会：
- 分析项目架构（前端 HTML/JS + 后端 Flask）
- 理解核心功能模块（论文管理、AI 翻译、AI 解读、Daily arXiv 等）
- 熟悉代码组织方式（路由、工具函数、数据模型等）
- 掌握现有的代码风格和设计模式

#### 第二步：描述你的需求

当 AI 理解代码库后，你就可以直接描述想要实现的功能了。例如：

**示例 1：添加黑夜模式**
```
请为我添加一个黑夜模式，在右上角加入一个按钮，点击后切换到黑夜模式，方便我在光线较暗的情况下读论文
```

**示例 2：添加论文标签功能**
```
我想添加一个论文标签功能，可以为每篇论文添加多个标签，并且可以根据标签筛选论文
```

**示例 3：导出为 BibTeX**
```
请添加一个功能，可以将选中的论文导出为 BibTeX 格式的文件
```

**示例 4：自定义快捷键**
```
我想添加键盘快捷键，比如按 'j' 和 'k' 键可以在论文列表中上下导航
```

### 📁 项目结构

了解项目结构有助于你更好地描述需求。Resophy 采用清晰的分层架构：

```
Resophy/
├── app.py                    # Flask 应用入口，路由注册
├── resophy/
│   ├── core/                 # 核心数据模型
│   │   ├── base_paper.py     # 论文数据模型
│   │   ├── paper_store.py    # 论文存储管理
│   │   └── search_index.py   # 全文搜索索引
│   ├── routes/               # 路由处理
│   │   ├── basic_routes/     # 基础功能路由（论文操作、分类、搜索等）
│   │   └── agent_routes/     # AI 功能路由（翻译、解读）
│   └── tools/                 # 工具函数
│       ├── basic_tools/      # 基础工具（arXiv、PDF 处理、分类管理等）
│       └── agent_tools/      # AI 工具（翻译、解读）
├── templates/                 # HTML 模板
│   ├── index.html           # 主界面
│   ├── pdf_viewer.html      # PDF 阅读器
│   └── analysis_viewer.html # AI 解读查看器
├── static/
│   ├── css/
│   │   └── style.css        # 样式文件
│   └── js/
│       └── app.js           # 前端 JavaScript
└── papers/                   # 论文存储目录（用户数据）
```

**关键概念**：
- **路由（Routes）**：处理 HTTP 请求，定义 API 端点
- **工具函数（Tools）**：封装业务逻辑，可被路由调用
- **数据模型（Core）**：定义数据结构（如 `Paper` 类）
- **前端（Templates + Static）**：用户界面和交互逻辑

### 💡 编写 Prompt 的技巧

为了让 AI 更好地理解你的需求，建议在 prompt 中包含：

1. **功能描述**：清晰说明要实现什么功能
2. **交互方式**：描述用户如何操作（点击按钮、快捷键、菜单等）
3. **界面位置**：指定功能在界面的哪个位置（右上角、侧边栏、论文卡片等）
4. **数据存储**：是否需要保存用户偏好（如黑夜模式开关）
5. **特殊要求**：如有特殊样式、动画效果等需求，一并说明

**好的 Prompt 示例**：
```
请为我添加一个黑夜模式功能：
1. 在右上角导航栏（头像按钮旁边）添加一个月亮图标按钮
2. 点击后切换到深色主题，图标变为太阳
3. 再次点击切换回浅色主题
4. 用户的偏好设置需要保存，刷新页面后自动恢复
5. 深色主题需要适配所有界面元素（导航栏、侧边栏、论文卡片、设置页面等）
```

### 🎨 自定义示例

以下是一些常见的自定义需求示例，你可以参考这些思路：

| 功能 | Prompt 示例 |
|------|-----------|
| **主题定制** | "请添加一个主题选择器，支持多种颜色主题（蓝色、绿色、紫色），用户可以在设置中选择" |
| **导出功能** | "添加一个功能，可以将论文列表导出为 CSV 文件，包含标题、作者、年份等信息" |
| **批量操作** | "实现批量标记功能，可以同时为多篇论文添加收藏标记或标签" |
| **搜索增强** | "增强搜索功能，支持按年份范围、作者、关键词组合搜索" |
| **阅读统计** | "添加阅读统计面板，显示总阅读时间、阅读论文数量、最常阅读的分类等" |
| **快捷操作** | "添加右键菜单，在论文卡片上右键可以快速执行翻译、解读、删除等操作" |

### ⚠️ 注意事项

1. **代码风格**：AI 会自动遵循项目现有的代码风格，保持一致性
2. **测试建议**：添加新功能后，建议手动测试确保功能正常
3. **兼容性**：如果修改了核心功能，注意检查是否影响现有功能
4. **数据备份**：在添加可能影响数据的功能前，建议先备份 `papers/` 目录

----

## 4. LICENSE
Resophy 采用 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en) 开源许可证，请参考 [LICENSE](LICENSE) 文件。
