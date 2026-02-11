<div align="center" xmlns="http://www.w3.org/1999/html">
<!-- logo -->
<p align="center">
  <img src="https://github.com/user-attachments/assets/d6472d7d-fce6-4c86-814e-2d490255e85a" width="500px" style="vertical-align:middle;">
</p>

<p align="center">


  <!-- Stars Badge -->
  <img src="https://img.shields.io/github/stars/Mountchicken/PaperPilot?style=social&color=D3C1D9" alt="Stars">

  <!-- Forks Badge -->
  <img src="https://img.shields.io/github/forks/Mountchicken/PaperPilot?style=social&color=D3C1D9" alt="Forks">

  <!-- Open Issues Badge -->
  <a href="https://github.com/Mountchicken/PaperPilot/issues">
    <img src="https://img.shields.io/github/issues-raw/Mountchicken/PaperPilot?color=D3C1D9" alt="Open Issues">
  </a>

  <!-- Issue Resolution Badge -->
  <a href="https://github.com/Mountchicken/PaperPilot/issues">
    <img src="https://img.shields.io/github/issues-closed-raw/Mountchicken/PaperPilot?color=32CD32" alt="Issue Resolution">
  </a>

  <!-- Pull Requests Badge -->
  <img src="https://img.shields.io/github/issues-pr/Mountchicken/PaperPilot?color=FFFF00" alt="Pull Requests">

  <!-- Platform Support Badge (Windows, Mac, Linux) with Light Green -->
  <img src="https://img.shields.io/badge/Platform-Windows%2C%20Mac%2C%20Linux-D3C1D9" alt="Platform Support">

  <!-- UV Installation Badge (Custom) -->
  <img src="https://img.shields.io/badge/Install-UV-D3C1D9?style=flat" alt="UV Installation">

  <img src="https://img.shields.io/badge/License-CC%20BY--NC%204.0-FFCDC9" alt="License">
</p>



[English](README.md) | [简体中文](docs/README_cn.md) | [Installation Guide](docs/installation_en.md)

<span style="color:rgb(154, 46, 222);">***All PaperPilot code is built using Cursor (Sonnet 4.5/Auto) generation with manual verification***</span>

</div>

# Key Enhancements (This Fork)

This section highlights the major enhancements and how to configure them, placed at the top for quick onboarding.

## UI Preview (Modified Frontend)

<div align="center">
  <img src="docs/assets/screenshots/paperpilot-frontend.png" width="900px" />
</div>

## 1) Unified SQLite Persistence (Backend)

- Single database file: `./db/paperpilot.db` (created automatically on startup; schema initialized automatically).
- Covered data (examples): papers/categories, user settings, reading history, reading list, Daily arXiv tasks, AI Chat sessions/history, etc.
- Backup/migration: stop the service and copy `db/paperpilot.db`; for full asset migration, also back up the `papers/` directory.

## 2) AI Chat: Conversational Deep Paper Reading

- Multi-turn conversations scoped to each paper; sessions and history are stored in SQLite.
- Built-in common prompts for interpretation / deep reading, designed for “read while you ask”.
- Model selection: uses the **Interpret** scenario model config by default (see section 3).

## 3) Fine-grained LLM Config per Feature (llmConfigs)

Configure different models/APIs for different workflows to reduce cost and improve quality:

- **Translate**: AI Translation
- **Interpret**: AI Interpretation + AI Chat
- **Daily arXiv**: Daily arXiv summarization/analysis

Where to set: Settings → Agentic → LLM Configs (fill in three groups: Translate / Interpret / Daily arXiv).

Core Agentic settings schema (stored as JSON in DB):

```json
{
  "llmConfigs": {
    "translate": { "llmModel": "xxx", "llmBaseUrl": "http://127.0.0.1:6002/v1", "llmApiKey": "sk-***" },
    "interpret": { "llmModel": "xxx", "llmBaseUrl": "http://127.0.0.1:6002/v1", "llmApiKey": "sk-***" },
    "dailyArxiv": { "llmModel": "xxx", "llmBaseUrl": "http://127.0.0.1:6002/v1", "llmApiKey": "sk-***" }
  },
  "mineruServerUrl": "http://127.0.0.1:6001",
  "mineruUseApi": false,
  "mineruApiToken": ""
}
```

Backward compatibility: legacy `llmModel/llmBaseUrl/llmApiKey` will be auto-migrated/filled into `llmConfigs.*` on first run or when saving settings.

## 4) Supabase Auth Integration (Public Deployment Ready)

The backend integrates Supabase Auth for login verification and API access control, enabling safer public deployment.

Required environment variables (recommended to set via `.env`; never commit secrets to the repo):

```bash
SUPABASE_URL="https://<your-project-ref>.supabase.co"
SUPABASE_ANON_KEY="<your-anon-key>"
```

When configured, most `/api/*` endpoints require `Authorization: Bearer <token>` (the frontend attaches it automatically after Supabase login).

## 5) UI/UX Improvements: Sidebar Toggle Buttons

- Floating toggle buttons for left/right sidebars allow quick collapse/expand, improving small-screen usability.

## 6) Enhanced Task Management UI

- **Real-time Progress Tracking**: AI Translation and Interpretation tasks now display a percentage progress bar in the Reading List.
- **Task Cancellation**: A dedicated "Cancel" button allows users to immediately stop running tasks.

## Run & Configuration (Enhanced Quick Start)

### Before You Start (Prepare These)

- **Python**: 3.10+ (see `pyproject.toml`)
- **Git**: for cloning the repo
- **uv**: dependency/venv manager
- **Supabase Auth (Required)**:
  - `SUPABASE_URL`
  - `SUPABASE_ANON_KEY`
  - In Supabase Console, enable Email/Password sign-in (Auth → Providers)
- **LLM API (for AI features)**:
  - OpenAI-compatible Base URL (e.g., `http://127.0.0.1:6002/v1` or a remote API)
  - API Key
  - Model name(s) for: Translate / Interpret / Daily arXiv
- **MinerU (for AI Interpretation / PDF parsing)**:
  - Either MinerU Cloud API token, or a self-hosted MinerU server URL

### 1) Install uv

Linux/macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows (PowerShell):

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

### 2) Clone & Install Dependencies

```bash
git clone <YOUR_REPO_URL>
cd PaperPilot
uv venv
source .venv/bin/activate
uv pip install -e .
```

### 3) Configure Environment Variables (.env)

Create a `.env` file in the repo root (it is already ignored by git):

```bash
SUPABASE_URL="https://<your-project-ref>.supabase.co"
SUPABASE_ANON_KEY="<your-anon-key>"
```

### 4) Start PaperPilot

```bash
python app.py --papers-dir ./papers --host 0.0.0.0 --port 7191
```

Key parameters:

- `--papers-dir`: PDF storage folder (default: `./papers`)
- `--host`: bind address (default: `0.0.0.0`)
- `--port`: web port (default: `7191`)

After startup, open:

- `http://localhost:7191`

### 5) First Login (Supabase)

- You will see a login overlay.
- Use **Sign Up** to create an account, then **Log In**.
- After login, the app will start calling `/api/*` with `Authorization: Bearer <token>` automatically.

### 6) Configure AI Features (Recommended)

In the UI: Settings → Agentic

- **LLM Configs**:
  - Fill in Translate / Interpret / Daily arXiv separately (Model / Base URL / API Key)
  - Tip: if you run your own OpenAI-compatible server, Base URL usually ends with `/v1`
- **MinerU**:
  - Cloud API mode: enter `mineruApiToken`
  - Local mode: set `mineruServerUrl` (e.g., `http://127.0.0.1:6001`)
  - Click **Test** and then save

Notes:

- AI Chat uses the **Interpret** LLM config by default.
- The SQLite DB is created at `./db/paperpilot.db` automatically on first run.

----


[![Video Name](https://github.com/user-attachments/assets/bced2c0f-0d4c-4c5d-a264-47bfc533ca31)](https://github.com/user-attachments/assets/13bfb7ab-a9b6-4f09-86c2-c513a6a8f221)

----

# PaperPilot

## 🆕 News

**2025-12-27：MinerU Official API Support**: PaperPilot now supports MinerU's official cloud API! You can use MinerU's cloud service for PDF parsing without deploying your own MinerU server. Simply configure your API token in Settings → Agentic → MinerU Mode (select "Cloud API") and enter your token from [https://mineru.net/](https://mineru.net/). This makes it easier to get started with AI interpretation features without GPU requirements.

---

In this era of information explosion, researchers often feel overwhelmed when facing massive amounts of papers. How to quickly extract the essence and understand cutting-edge achievements has become a pain point for every researcher. PaperPilot was born with the intention of helping you bid farewell to inefficient paper reading, empowering researchers, and making paper reading more efficient and intelligent 📚⚡.

PaperPilot is a fully open-source, Vibe Coding-oriented modern paper reader that helps you quickly understand the core content of papers through a simple tech stack (HTML + JavaScript + Python Flask) and AI features 🤖💡. From automatic translation to paper parsing, from intelligent recommendations to one-click Zotero import, PaperPilot provides a one-stop solution for your paper reading needs 📑✨. Most importantly, you can customize features at any time through **Vibe Coding**, creating a paper assistant tailored to you 🎨🛠️.


#### 🚀 Core Features



<div align="center" xmlns="http://www.w3.org/1999/html">
<!-- logo -->
<p align="center">
  <img src="https://github.com/user-attachments/assets/5fbe6d8f-570a-491d-9c54-1c008b23399d"  style="vertical-align:middle;">
</p>
</div>


----

## Table of Contents
- [PaperPilot](#paperpilot)
      - [Core Features](#-core-features)
  - [Table of Contents](#table-of-contents)
  - [1. Installation](#1-installation)
  - [2. Quick Start](#2-quick-start)
    - [2.1 ⚙️ Initial Configuration](#21-️-initial-configuration)
      - [📥 Import Papers from Zotero](#-import-papers-from-zotero)
      - [🤖 Configure LLM API](#-configure-llm-api)
      - [🔧 Configure MinerU API (for AI Interpretation)](#-configure-mineru-apifor-ai-interpretation)
    - [2.2. 🚀 Main Features Usage](#22--main-features-usage)
      - [📚 Paper Management](#-paper-management)
      - [🌐 AI Translation](#-ai-translation)
      - [🧠 AI Interpretation](#-ai-interpretation)
      - [📰 Daily arXiv](#-daily-arxiv)
      - [📊 Other Features](#-other-features)
  - [3. 💻 Vibe Coding](#3--vibe-coding)
    - [🚀 Getting Started with Vibe Coding](#-getting-started-with-vibe-coding)
    - [📁 Project Structure](#-project-structure)
    - [💡 Example: Adding New Features](#-example-adding-new-features)
  - [4. LICENSE](#4-license)

----

## 1. Installation

<div align=center>
  <img src="https://github.com/user-attachments/assets/73d25cfa-5791-4b54-a131-d816f51afebb">
  <div style="margin-top:8px; color: #555; font-size: 16px;">
    PaperPilot adopts a frontend-backend separated architecture
  </div>
</div>


1. **Main Service (PaperPilot Core)**: HTML + JavaScript + Python Flask backend service, providing core features such as paper management, classification, and search
2. **AI Services** include:
   - **LLM Server**: LLM inference service for AI translation, interpretation, and arXiv paper analysis (optional, supports local deployment or remote API)
   - **MinerU Server**: Document parsing service for PDF to Markdown parsing (optional, for AI features)
  
PaperPilot uses `uv` for dependency management and supports separated deployment architecture. You can deploy PaperPilot main service and AI servers on different machines. For installation and configuration instructions, please refer to:

<div align="center">
  <table>
    <thead>
      <tr>
        <th>System</th>
        <th>Documentation</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Windows / Mac / Linux</td>
        <td><a href="docs/installation_en.md">Installation Guide</a></td>
      </tr>
    </tbody>
  </table>
</div>

---- 

## 2. Quick Start

In this section, we briefly introduce some usage methods of PaperPilot


### 2.1 ⚙️ First Step: Initial Configuration

<div align=center>
  <img src="https://github.com/user-attachments/assets/6cc2292a-d3df-45d2-8bda-15f9edd13189">
  <div style="margin-top:8px; color: #555; font-size: 16px;">
    First step: configure parameters and migrate papers from Zotero
  </div>
</div>


<div align="center">

| Configuration Module | Location | Main Features | Usage |
|---------|------|---------|---------|
| **📸 User Settings** | Settings Interface → "User" Tab | • Avatar upload<br>• Username setting<br>• Reading heatmap color theme<br>• Recent reading records | 1. Click avatar in top right corner<br>2. Enter "User" tab<br>3. Upload avatar, set username, select color<br>4. Auto-save settings |
| **🤖 Agentic Settings** | Settings Interface → "Agentic" Tab | • LLM API configuration (model name, URL, key)<br>• MinerU server configuration<br>• AI interpretation prompt customization | 1. Enter "Agentic" tab<br>2. Configure LLM API and MinerU address<br>3. (Optional) Customize prompts<br>4. Test connection and save |
| **📰 Daily arXiv** | Settings Interface → "Daily arXiv" Tab | • arXiv category configuration (cs.CV, cs.AI, etc.)<br>• Crawling settings (retention days, check interval)<br>• Keyword list (for intelligent classification)<br>• Institution configuration | 1. Enter "Daily arXiv" tab<br>2. Add arXiv categories<br>3. Configure crawling parameters and keywords<br>4. (Optional) Add custom institutions<br>5. Save settings |
| **📥 Zotero Import** | Settings Interface → "Import" Tab | • Target directory selection<br>• RDF file drag-and-drop upload<br>• Import progress display<br>• Import result statistics | 1. Export from Zotero as RDF format<br>2. Enter "Import" tab<br>3. (Optional) Select target directory<br>4. Drag and drop RDF file<br>5. View import progress and results |

</div>

<details open>
<summary><strong>Expand for Detailed Introduction</strong></summary>


#### 📸 User Settings

**Feature Details**:
- **Avatar Upload**: Click avatar area to upload custom avatar, supports preview and cropping
- **Username Setting**: Enter username (default: Paper Reader)
- **Reading Heatmap Color**: Select color theme (green/blue/rose pink) for visualizing daily reading time
- **Recent Reading Records**: Display list of recently read papers for quick access to history

#### 🤖 Agentic Settings (AI Feature Configuration)

**Feature Details**:
- **LLM API Configuration**:
  - Model Name: Enter model name (e.g., `Qwen3-4B-Instruct-2507`)
  - Base URL: Enter API address (local: `http://0.0.0.0:6002/v1` or remote API)
  - API Key: Enter access key
  - Test Button: Verify API connection
- **MinerU Configuration**:
  - **Mode Selection**: Choose between "Local Deployment" or "Cloud API"
  - **Local Deployment**: Enter server address (e.g., `http://0.0.0.0:6001`) for self-hosted MinerU server
  - **Cloud API**: Enter API token from [https://mineru.net/](https://mineru.net/) for MinerU cloud service
  - Test Button: Verify connection (server or API token)
- **AI Interpretation Prompt**: Large text editor for customizing System Prompt, controlling AI interpretation generation style

**Purpose**: Unified AI feature configuration for translation, interpretation, Daily arXiv, and all other AI features

#### 📰 Daily arXiv Settings

**Feature Details**:
- **arXiv Category Configuration**: Add/delete category tags (cs.CV, cs.AI, etc.), provides quick buttons for common categories
- **Crawling Settings**: Paper retention days (1-30 days), check interval (5-60 minutes)
- **Keyword List**: Add keyword tags, set maximum number of keywords (1-3), for AI automatic classification
- **Institution Configuration**: Add custom institutions, supports editing abbreviations and full name variants

#### 📥 Import from Zotero

**Feature Details**:
- **Target Directory Selection**: Dropdown menu to select import location (optional, default root directory)
- **File Upload Area**: Large drag-and-drop upload area, supports dragging `.rdf` files
- **Import Progress Display**: Progress bar, status text, cancel button
- **Import Result Statistics**: Success/failure/skip/duplicate counts

**Usage Steps**:
1. Export library from Zotero as RDF format
2. Enter "Import" tab in PaperPilot settings interface
3. (Optional) Select target directory
4. Drag RDF file to upload area
5. System automatically parses and imports papers, displays import progress and results

</details>

### 2.2 Basic Operations

<details open>
<summary><strong>View Basic Operations</strong></summary>


| Operation Module | Main Features | Usage |
|---------|---------|---------|
| **📚 Paper Management** | • Upload papers (drag PDF or enter arXiv URL)<br>• Category management (create/rename/delete categories, move papers)<br>• Full-text search (title, author, abstract) | 1. Drag PDF to upload area or enter arXiv URL<br>2. Manage category structure with left category tree<br>3. Use top search box for full-text search |
| **📖 Paper Viewing** | • View paper details<br>• PDF reader<br>• Automatic reading time recording | 1. Click paper card to enter details page<br>2. View metadata and abstract<br>3. Click "View PDF" to open reader |
| **✏️ Metadata Management** | • Edit paper information (title, author, abstract, etc.)<br>• Add notes and tags<br>• Manage BibTeX citations<br>• Set links (GitHub, homepage) | 1. Enter paper details page<br>2. Click "Edit" button<br>3. Modify information and save |
| **📈 Reading History** | • Automatic reading time recording<br>• Reading heatmap (visualize daily reading statistics)<br>• Recent reading records | View reading heatmap and recent reading list in user settings |
| **📥 Export Function** | • Export paper library as JSON format<br>• Includes metadata and category structure | 1. Enter settings interface<br>2. Select export scope<br>3. Download JSON file |



**📝 Automatic Paper Metadata Retrieval**:

When uploading papers (via arXiv URL or dragging PDF), the system automatically retrieves paper metadata:

1. **Get Basic Information via arXiv API**:
   - Call arXiv API to get paper title, authors, abstract, year, etc.
   - Download PDF file

2. **Get BibTeX via DBLP API**:
   - Use paper title and author information to call DBLP API
   - Attempt to get more accurate BibTeX citation format
   - If DBLP retrieval succeeds, use DBLP BibTeX; otherwise use arXiv BibTeX

3. **Processing Flow for Drag-and-Drop PDF Upload**:
   - System attempts to extract arXiv ID from filename or PDF metadata
   - If arXiv ID is found, call arXiv API to get information
   - Asynchronously call DBLP API in background to update BibTeX
  
</details>

### 2.6 User Registration & Login (Supabase)
- Refer to the Chinese documentation for full setup and usage: [用户注册与登录（基于 Supabase）](file:///home/flyflypeng/agent/PaperPilot/docs/README_cn.md#L369-L418)

### 2.3. AI Translation

<details open>
<summary><strong>View AI Translation</strong></summary>


**Implementation Method**:

PaperPilot's AI translation feature uses the [Babeldoc](https://github.com/funstory-ai/BabelDOC) tool to implement PDF bilingual translation:

1. **Call babeldoc**:
   - Pass configured LLM API information (model, URL, key)

2. **Translation Process**:
   - babeldoc reads original PDF file
   - Call LLM API for translation (supports OpenAI-compatible interface)
   - Generate bilingual PDF (`.zh.dual.pdf`), original and Chinese translation displayed side by side

**Usage**:
1. Select a paper in main interface
2. Click "AI Translation" button
3. System executes translation task in background
4. After translation completes, view bilingual PDF in paper details page

</details>


### 2.4 AI Interpretation

<details open>
<summary><strong>View AI Interpretation</strong></summary>

**Implementation Method**:

PaperPilot's AI interpretation feature uses a two-step process to deeply analyze paper content:

1. **Parse PDF to Markdown**:
   - Use [MinerU](https://github.com/opendatalab/MinerU) tool to parse PDF into structured Markdown
   - Supports two modes:
     - **Cloud API**: Use MinerU's official cloud service (no GPU required, easy setup)
     - **Local Deployment**: Connect to self-hosted MinerU server (supports vLLM deployment)
   - Preserve images, tables, and other elements, generate high-quality Markdown document

2. **LLM Deep Interpretation**:
   - Use `openai` library to call LLM API (supports OpenAI-compatible interface)
   - Use Markdown content as input, combined with custom System Prompt
   - LLM generates structured interpretation report (summary, methods, experiments, conclusions, etc.)
   - Supports custom prompts to control interpretation style and content format

**Usage**:
1. Select a paper, click "AI Interpretation" button
2. System starts background task:
   - Step 1: MinerU parses PDF to Markdown
   - Step 2: LLM deeply analyzes and generates interpretation report
3. View progress and logs in "Interpretation Tasks" page
4. After interpretation completes, click paper to enter interpretation view for detailed analysis
5. **Export Report**: Click the "Export" button in the top right corner to save the report as **Markdown** or **PDF** (optimized for printing)

</details>

### 2.5. Daily arXiv

<details open>
<summary><strong>View Daily arXiv Feature</strong></summary>

**Implementation Method**:

Daily arXiv feature automatically crawls latest arXiv papers and uses AI for intelligent analysis and filtering:

1. **Paper Crawling**:
   - Use `arxiv` Python library to crawl papers from specified categories
   - Supports scheduled automatic checking (configurable check interval)
   - Organize papers by date and category

2. **AI Feature Application**:

   **a. Institution Information Extraction**:
   - Use `openai` library to call LLM API
   - Extract institution names (affiliations) from PDF first page text
   - Extract institution countries
   - Extract project homepage and GitHub repository URL
   - Supports institution name standardization and abbreviation recognition

   **b. Abstract Summary and Keyword Extraction**:
   - Use `openai` library to call LLM API
   - Generate Chinese summary (100-200 words) from paper English abstract
   - Select keywords (1-3) that best represent paper type from preset keyword list
   - Keywords used for subsequent intelligent filtering and classification

3. **Intelligent Filtering**:
   - Filter papers based on configured keyword list
   - Filter papers based on institution information
   - Supports custom institution mapping and standardization

4. **Background Tasks**:
   - Scheduled automatic checking for new papers (configurable interval)
   - Background PDF file download
   - Asynchronous AI analysis task execution
   - Automatic cleanup of expired papers (configurable retention days)

**Usage**:
1. Configure arXiv categories (e.g., cs.CV, cs.AI) in settings
2. Set keyword list and filtering conditions
3. Click "Daily arXiv" button to get today's papers
4. System automatically crawls, downloads, and analyzes papers
5. Browse matching paper list, batch import to reading list

</details>

----

## 3. 💻 Vibe Coding

PaperPilot adopts the **Vibe Coding** development philosophy, which means you can easily customize and extend features through natural language conversations with AI Coding Agent. No need to deeply understand complex code structures, just describe your needs, and AI will help you implement them.

[![Video Name](https://github.com/user-attachments/assets/bced2c0f-0d4c-4c5d-a264-47bfc533ca31)](https://github.com/user-attachments/assets/a7c218eb-f045-4b59-9076-fff93e5e4861)

<div align="center">
  <div style="margin-top:8px; color: #555; font-size: 14px;">
    Click to watch Vibe Coding demo video
  </div>
</div>

### 🚀 Getting Started with Vibe Coding

Using Vibe Coding to customize features is very simple, just two steps:

#### Step 1: Let AI Understand the Codebase

When conversing with Coding Agent, first enter the following prompt:

```
Please understand the functionality of this paper reading platform
```

This prompt will make AI automatically analyze the entire codebase structure, features, and implementation methods, establishing comprehensive understanding of the project. AI will:
- Analyze project architecture (frontend HTML/JS + backend Flask)
- Understand core feature modules (paper management, AI translation, AI interpretation, Daily arXiv, etc.)
- Familiarize with code organization (routes, utility functions, data models, etc.)
- Master existing code style and design patterns

#### Step 2: Describe Your Needs

After AI understands the codebase, you can directly describe the features you want to implement. For example:

**Example 1: Add Dark Mode**
```
Please add a dark mode for me, add a button in the top right corner, click to switch to dark mode, convenient for reading papers in dim light
```

**Example 2: Add Paper Tag Feature**
```
I want to add a paper tag feature, can add multiple tags to each paper, and can filter papers by tags
```

**Example 3: Export as BibTeX**
```
Please add a feature to export selected papers as BibTeX format file
```

**Example 4: Custom Shortcuts**
```
I want to add keyboard shortcuts, like pressing 'j' and 'k' keys to navigate up and down in the paper list
```

### 📁 Project Structure

Understanding the project structure helps you better describe your needs. PaperPilot adopts a clear layered architecture:

```
PaperPilot/
├── app.py                    # Flask application entry, route registration
├── paperpilot/
│   ├── core/                 # Core data models
│   │   ├── base_paper.py     # Paper data model
│   │   ├── paper_store.py    # Paper storage management
│   │   └── search_index.py   # Full-text search index
│   ├── routes/               # Route handlers
│   │   ├── basic_routes/     # Basic feature routes (paper operations, categories, search, etc.)
│   │   └── agent_routes/     # AI feature routes (translation, interpretation)
│   └── tools/                 # Utility functions
│       ├── basic_tools/      # Basic tools (arXiv, PDF processing, category management, etc.)
│       └── agent_tools/      # AI tools (translation, interpretation)
├── templates/                 # HTML templates
│   ├── index.html           # Main interface
│   ├── pdf_viewer.html      # PDF reader
│   └── analysis_viewer.html # AI interpretation viewer
├── static/
│   ├── css/
│   │   └── style.css        # Style file
│   └── js/
│       └── app.js           # Frontend JavaScript
└── papers/                   # Paper storage directory (user data)
```

**Key Concepts**:
- **Routes**: Handle HTTP requests, define API endpoints
- **Utility Functions (Tools)**: Encapsulate business logic, can be called by routes
- **Data Models (Core)**: Define data structures (such as `Paper` class)
- **Frontend (Templates + Static)**: User interface and interaction logic

### 💡 Tips for Writing Prompts

To help AI better understand your needs, it's recommended to include in the prompt:

1. **Feature Description**: Clearly explain what feature to implement
2. **Interaction Method**: Describe how users operate (click button, shortcuts, menu, etc.)
3. **Interface Location**: Specify where the feature is in the interface (top right corner, sidebar, paper card, etc.)
4. **Data Storage**: Whether user preferences need to be saved (such as dark mode toggle)
5. **Special Requirements**: If there are special styles, animation effects, etc., explain them together

**Good Prompt Example**:
```
Please add a dark mode feature for me:
1. Add a moon icon button in the top right navigation bar (next to avatar button)
2. Click to switch to dark theme, icon changes to sun
3. Click again to switch back to light theme
4. User preference settings need to be saved, automatically restore after page refresh
5. Dark theme needs to adapt to all interface elements (navigation bar, sidebar, paper cards, settings page, etc.)
```

### 🎨 Customization Examples

The following are some common customization need examples, you can refer to these ideas:

| Feature | Prompt Example |
|------|-----------|
| **Theme Customization** | "Please add a theme selector, support multiple color themes (blue, green, purple), users can select in settings" |
| **Export Function** | "Add a feature to export paper list as CSV file, including title, author, year, and other information" |
| **Batch Operations** | "Implement batch marking feature, can simultaneously add favorite marks or tags to multiple papers" |
| **Search Enhancement** | "Enhance search function, support combined search by year range, author, keywords" |
| **Reading Statistics** | "Add reading statistics panel, display total reading time, number of papers read, most frequently read categories, etc." |
| **Quick Actions** | "Add right-click menu, right-click on paper card to quickly execute translation, interpretation, delete, and other operations" |

### ⚠️ Notes

1. **Code Style**: AI will automatically follow the project's existing code style, maintaining consistency
2. **Testing Recommendations**: After adding new features, it's recommended to manually test to ensure functionality is normal
3. **Compatibility**: If core features are modified, pay attention to check if existing features are affected
4. **Data Backup**: Before adding features that may affect data, it's recommended to backup the `papers/` directory first

----

## 4. LICENSE
PaperPilot uses the [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en) open source license, please refer to the [LICENSE](LICENSE) file.
