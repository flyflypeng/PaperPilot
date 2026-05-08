# PaperPilot

<div align="center">

<img src="static/images/paperpilot-github-banner.png" width="100%" />

**一个全开源的AI原生的论文阅读与管理平台**

[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC%20BY--NC%204.0-lightgrey.svg)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Status](https://img.shields.io/badge/Status-Alpha-orange)]()

[English](README.md) | [中文](README_zh.md)

</div>

---

> 这个项目是基于 [Resophy](https://github.com/Mountchicken/Resophy) 开源项目二次开发而来，非常感谢原作者有趣的创造。

## 📖 简介

<div align="center">
  <iframe src="//player.bilibili.com/player.html?bvid=BV1kGcGzdEYk&page=1&high_quality=1" scrolling="no" border="0" frameborder="no" allowfullscreen="true" width="100%"></iframe>
</div>

**PaperPilot** 是您的下一代科研助手，旨在优化您的学术工作流。通过将先进的 AI 能力与强大的文档管理系统深度融合，PaperPilot 帮助您以前所未有的效率发现、阅读、理解和管理研究论文。

无论您是追踪最新的 ArXiv 预印本，还是深度研读复杂的 PDF 文献，PaperPilot 都是您的智能副驾驶。

> **Note**: 本项目基于 **Trae Coding Agent**，使用了 2 种模型（**Gemini-3-Pro-Preview** 和 **GPT-5.2**，其中 Gemini-3-Pro-Preview 主要用于代码功能开发，GPT-5.2 主要用于 Bugfix 和性能优化）**Vibe Coding** 实现，这真的对于我一个没有写过现代意义上 Web 前端代码的我简直不可思议 🤯（上一次写 Web 代码还是读本科时用 HTML 和 CSS 手写网页）。

## ✨ 核心功能

### 📚 智能论文管理
- **无缝上传**：支持拖拽上传 PDF，自动提取元数据。
- **高效整理**：自定义分类、文件夹管理及全文检索。
- **Zotero 集成**：支持从 Zotero RDF 库一键导入文献。
- **阅读热力图**：内置 GitHub 风格的贡献图，可视化您的阅读习惯。

### 🤖 AI 阅读助手
- **AI 翻译**：基于 **BabelDOC** 实现像素级英汉（及多语种）翻译，完美保留原始排版和图表。
- **AI 深度解读**：利用 **MinerU** (PDF转Markdown) 和 LLM 对论文进行深度分析，生成结构化摘要（摘要、方法、实验、结论）。
- **论文对话**：与文档进行交互式问答，快速厘清概念与细节。

### 📡 Daily ArXiv 学术雷达
- **自动追踪**：定时抓取指定 ArXiv 领域（如 `cs.CV`, `cs.AI`）的最新论文。
- **智能筛选**：支持按关键词、机构权重进行过滤和高亮。
- **AI 摘要**：自动为新论文生成简明扼要的中文摘要。
- **离线可用**：即使没有 LLM 连接也能正常抓取（仅跳过摘要/机构信息）。

## 📸 功能展示

### 📡 Daily ArXiv 每日论文追踪
自动抓取最新论文，生成 AI 摘要，助您紧跟前沿。
<div align="center">
  <img src="static/images/snapshots/Daily-arxiv-1.png" width="48%" />
  <img src="static/images/snapshots/Daily-arXiv-2.png" width="48%" />
</div>

### 🤖 AI 深度解读与对话
基于全文的深度分析与交互式问答，打破语言与理解障碍。
<div align="center">
  <img src="static/images/snapshots/AI-Interpretion.png" width="48%" />
  <img src="static/images/snapshots/AI-Chat.png" width="48%" />
</div>

### 📚 论文管理与配置
高效的阅读列表管理与灵活的系统配置。
<div align="center">
  <img src="static/images/snapshots/Reading-List.png" width="48%" />
  <img src="static/images/snapshots/setting-overview.png" width="48%" />
</div>

### 🔐 安全鉴权与访问控制
支持用户登录鉴权，保障私密访问，方便公网部署。
<div align="center">
  <img src="static/images/snapshots/login.png" width="48%" />
</div>

## 🛠️ 技术栈

- **后端**：Python 3.10+, Flask
- **前端**：HTML5, CSS3, 原生 JS (响应式设计)
- **数据库**：SQLite (元数据), Supabase (可选鉴权)
- **AI 核心**：
  - [MinerU](https://github.com/opendatalab/MinerU) (高保真 PDF 解析)
  - [BabelDOC](https://github.com/funstory-ai/BabelDOC) (文档翻译)
  - OpenAI 兼容 LLM 接口

## 🚀 安装指南

推荐使用 [uv](https://github.com/astral-sh/uv) 进行快速可靠的依赖管理。

### 前置要求
- Python 3.10 或更高版本
- `uv` 包管理器

### 安装步骤

1. **克隆仓库**
   ```bash
   git clone https://github.com/flyflypeng/PaperPilot
   cd PaperPilot
   ```

2. **初始化环境**
   ```bash
   uv venv
   source .venv/bin/activate  # Linux/macOS
   # .\.venv\Scripts\activate # Windows
   ```

3. **安装依赖**
   
   **选项 A: 标准版 (仅客户端)**
   如果您主要使用外部 API 进行 AI 任务，推荐此选项。
   ```bash
   uv pip install -e ".[local]"
   ```

   **选项 B: 完整版 (本地 AI)**
   包含本地运行 MinerU 和 VLM 推理所需的依赖。
   ```bash
   uv pip install -e ".[server]"
   ```

4. **Supabase Auth 鉴权（可选）**
   PaperPilot 的登录/注册基于 Supabase Auth（邮箱+密码）。启用后，前端会在浏览器中通过 `supabase-js` 获取会话令牌，并在请求 `/api/*` 时携带 `Authorization: Bearer <access_token>`；后端会用 Supabase 的 `/auth/v1/user` 接口校验令牌有效性。
   若未配置 `SUPABASE_URL` 与 `SUPABASE_ANON_KEY`，系统将默认关闭鉴权：前端不会显示登录界面，后端 `/api/*` 接口不要求 `Authorization` 头，直接进入管理界面。

   1）创建 Supabase 项目并获取密钥
   - 进入 https://supabase.com/ 创建 Project
   - 在 Supabase 控制台进入 **Project Settings → API**
   - 复制 **Project URL** 作为 `SUPABASE_URL`
   - 复制 **Project API keys → anon public** 作为 `SUPABASE_ANON_KEY`

   2）在 Supabase 控制台启用 Email 登录
   - 进入 **Authentication → Providers**
   - 启用 **Email**（Email/Password）
   - 如仅用于本地/内网试用，可在 **Authentication → Settings** 中关闭邮箱确认（Email confirmations），避免注册后必须点邮件验证

   3）配置回调地址（非常重要）
   - 进入 **Authentication → URL Configuration**
   - 将 **Site URL** 设置为你的站点根地址，例如：
   - 本地：`http://localhost:7191`
   - 线上：`https://your-domain.com`
   - 在 **Redirect URLs** 中添加允许的回调地址（至少包含站点根地址），例如：
   - `http://localhost:7191/`
   - `https://your-domain.com/`

   4）在 PaperPilot 中启用鉴权
   在项目根目录复制并编辑环境变量：
   ```bash
   cp .env.example .env
   # 编辑 .env 文件填入 SUPABASE_URL 和 SUPABASE_ANON_KEY
   ```
   重启服务后访问页面，若 Supabase 配置正确会出现登录/注册入口。

   **安全提示**
   - 仅使用 `anon public` key；不要把 `service_role` key 放进 `.env` 或发到前端
   - 本项目会把 `SUPABASE_URL` 与 `SUPABASE_ANON_KEY` 注入到页面中（用于浏览器侧登录），这是预期行为

5. **启动应用**

   ```bash
   python app.py
   ```
   访问 Web 界面：`http://localhost:7191`（默认端口）

   **自定义启动参数：**
   `app.py` 支持以下命令行参数，方便用户自定义运行配置：

   | 参数 | 默认值 | 说明 |
   | :--- | :--- | :--- |
   | `--papers-dir` | `./papers` | 指定论文存储目录路径（绝对路径或相对路径） |
   | `--host` | `0.0.0.0` | 服务器监听地址 |
   | `--port` | `7191` | 服务器监听端口 |
   | `--debug` | `False` | 启用调试模式（开发用） |

   **典型配置方案：**

   - **指定数据存储位置**（适合数据盘挂载场景）：
     ```bash
     python app.py --papers-dir /mnt/data/my_papers
     ```

   - **修改服务端口**（当默认端口被占用时）：
     ```bash
     python app.py --port 8080
     ```

   - **仅允许本地访问**（增强安全性）：
     ```bash
     python app.py --host 127.0.0.1
     ```

## 🧪 测试

安装测试依赖：
```bash
uv pip install -e ".[test]"
```

运行快速单元测试，包括通过 mock 验证 arXiv 相关功能逻辑：
```bash
uv run pytest -q -m "not integration"
```

仅运行会真实访问 arXiv API、校验真实返回格式的集成测试：
```bash
uv run pytest -q -m integration
```

只运行 arXiv 相关测试：
```bash
uv run pytest -q tests/test_arxiv_api_interactions.py
```

`integration` 测试需要联网，并依赖 arXiv 服务可用性。如果遇到 arXiv 临时不可用或限流，请稍后重试。

## ⚙️ 配置

PaperPilot 主要通过 Web UI 配置。

### 仅对 arXiv 使用代理

如果只有 arXiv 元数据和 PDF 下载需要走代理，可以设置：

```bash
ARXIV_PROXY=http://127.0.0.1:7890
```

也可以使用按协议区分的变量：`ARXIV_HTTP_PROXY` 和
`ARXIV_HTTPS_PROXY`。这些变量只会应用到 `arxiv.org` 和
`export.arxiv.org`，不会影响 DBLP、LLM 服务、Supabase、MinerU 或其他后端请求。

Docker 构建时如需写入镜像默认值：

```bash
docker build --build-arg ARXIV_PROXY=http://host.docker.internal:7890 -t paperpilot .
```

## ⚙️ 配置说明

PaperPilot 支持通过 Web UI 直接进行配置。

### AI 设置 (Agentic Settings)
在 **Settings** 标签页中配置：
- **LLM 提供商**：设置 API Key、Base URL 和模型名称（如 GPT-4, Qwen, DeepSeek）。
- **MinerU**：选择本地实例或云端 API。

### Daily ArXiv
配置您的研究关注点：
- **领域 (Categories)**：选择需要监控的 ArXiv 分类。
- **关键词 (Keywords)**：定义筛选和高亮的关键词。
- **计划任务**：设置自动抓取的时间间隔。
- **每日最大论文数 (Max Papers per Day)**：限制每个 arXiv 日期最多抓取的论文总数，推荐默认值为 `50`。
- **单次每类新增上限 (Max New Papers per Category per Fetch)**：限制每次同步时每个分类最多新增多少篇论文，便于一天内多次同步时持续接收后续发布的论文。
- **替换候选上限 (Replacement Candidate Limit)**：当某个分类配额已满时，最多筛选多少篇较新的候选论文用于替换判断。

核心论文筛选流水线如下：

1. **arXiv 分类与日期过滤**：PaperPilot 会按每个配置的分类发起 `cat:<category>` 查询，按最新提交排序，只保留属于目标 arXiv 公告日期的论文；已经下载过的 Daily ArXiv 论文会跳过。
2. **关键词硬过滤**：如果 **Keywords** 非空，论文标题或摘要必须命中至少一个配置关键词才会进入后续流程。匹配时会忽略大小写，并归一化标点和空白。
3. **配额过滤**：候选论文必须同时满足每日总名额和当前分类名额；每次同步还会遵守 **单次每类新增上限**，避免过早占满当天名额。
4. **机构 tier 硬过滤**：arXiv 元数据不提供机构信息，因此 PaperPilot 会先下载候选 PDF，通过已配置的 LLM 从首页提取机构，再按当前质量策略做硬过滤：
   - `strict`：保留 Tier S/A，拒绝 Tier B/C 和未知机构。
   - `balanced`：保留 Tier S/A/B，并允许未知机构；拒绝 Tier C。
   - `discovery`：保留 Tier S/A/B/C，并允许未知机构。
   被该规则拒绝的论文不会保存、不会生成摘要，也不会出现在 Daily ArXiv 列表中。
5. **AI 信息补全**：通过筛选的论文会生成缩略图；当 Daily ArXiv 的 LLM 配置可用时，还会补全机构、国家、项目链接、Brief summary 和关键词标签。
6. **满额后的替换筛选**：当某个分类配额已满时，PaperPilot 可以让 LLM 比较少量较新的候选论文和当前已保留论文；只有当候选明显更有价值时，才替换已有论文。

Daily ArXiv 支持两种每日抓取名额分配方式：

- **自定义分类比例**：在 **arXiv Categories** 中为每个分类设置百分比，例如 `cs.CV 60%`、`cs.AI 25%`、`cs.LG 15%`。只要显式配置比例，比例总和必须等于 `100%`；超过或不足 100% 时会提示用户重新分配。
- **自动加权分配**：如果没有显式配置比例，PaperPilot 会继续保持原有的加权分配策略。

当使用自动分配且配置了多个 arXiv 分类时，Daily ArXiv 会使用增量式加权配额策略：

1. **加权保底**：PaperPilot 会根据当前 **Categories** 列表动态重新计算每个分类的配额。`cs.AI`、`cs.CV`、`cs.LG` 等高流量 AI 分类权重略低，`cs.DC`、`cs.OS`、`cs.NI`、`cs.PF` 等系统/基础设施类小众分类权重更高，避免被大类挤占。
2. **增量接收**：每次同步时，每个分类最多只新增 **单次每类新增上限** 指定的论文数量，避免早上触发同步时一次性占满全天名额，错过当天后续发布的论文。
3. **LLM 替换筛选**：当某个分类配额已满时，PaperPilot 可以把较新的候选论文和该分类下已保留的论文一起发送给配置的 LLM。输入 payload 会包含论文元数据、摘要、机构、国家，以及当前 **Institution tiers** 配置。LLM 只有在候选论文明显更有价值时才应替换已有论文；第一作者机构等级只作为质量和相关性接近时的辅助信号。

这样既能保留小众分类的曝光，又能避免过早占满每日名额，并允许当天较晚出现的高价值论文淘汰较弱的早期结果。

## ⚠️ 注意事项

- **多用户支持**：当前版本 PaperPilot 专为个人或小团队设计，尚未完全支持多用户隔离（Multi-tenancy）。虽然支持通过 Supabase 进行鉴权，但所有用户共享同一套后台配置和论文库。建议在私有网络或受信任的环境中部署。
- **BabelDOC 翻译**：基于 BabelDOC 功能的中英文对照翻译功能内存开销较大，并且整个 AI 翻译过程较长，建议需要特别精读论文时使用。

## 🗺️ Roadmap

> 欢迎提 Issue/PR 参与共建。Roadmap 会根据需求与资源动态调整。

### 近期（Next）
- [ ] 阅读标注：高亮、批注、书签与引用片段一键复制
- [ ] 论文对话增强：回答可溯源到页码/段落/引用片段
- [ ] Daily ArXiv 规则升级：关键词组合、排除词、正则
- [ ] 部署与运维：Docker Compose、自动备份/恢复、健康检查

### 中期（Mid）
- [ ] 语义检索：本地 embedding 索引（可选向量库），支持跨库搜索
- [ ] 个人知识库：研究笔记/摘要沉淀成可查询的研究日志（主题/时间线）
- [ ] 任务队列与进度中心：翻译/解读/索引统一队列、重试与优先级

### 长期（Future）
- [ ] 多用户隔离：按用户/团队隔离论文库与设置
- [ ] 论文推荐与关系图谱：基于引用网络与阅读行为的个性化推荐
- [ ] 协作工作区：共享文件夹、团队注释与权限控制
- [ ] 多模态理解：图表/公式/表格结构化提取与可检索
- [ ] 移动端/PWA：离线阅读、跨设备同步

### 性能与体验优化（持续）
- [ ] 更快的 PDF 渲染、分页缓存与长文档按需加载
- [ ] 全局搜索与索引增量更新（避免全量重扫）
- [ ] 配置校验与一键诊断（LLM/MinerU/BabelDOC 依赖检查）
- [ ] 统一日志与可观测性（任务耗时、失败原因统计）

## 📄 许可证

本项目采用 **CC BY-NC 4.0** 许可证。详情请参阅 [LICENSE](LICENSE) 文件。

---
<div align="center">
Made with ❤️ by the PaperPilot Team
</div>
