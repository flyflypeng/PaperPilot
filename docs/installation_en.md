## Installation


<div align=center>
  <img src="https://github.com/user-attachments/assets/73d25cfa-5791-4b54-a131-d816f51afebb" >
  <div style="margin-top:8px; color: #555; font-size: 16px;">
    PaperPilot adopts a frontend-backend separated architecture
  </div>
</div>


- [Installation](#installation)
    - [1. PaperPilot Architecture Overview](#1-paperpilot-architecture-overview)
    - [1.1. Local End (PaperPilot Core - Main Service)](#11-local-end-paperpilot-core---main-service)
    - [1.2. AI End (Optional - AI Server)](#12-ai-end-optional---ai-server)
  - [2. Install PaperPilot Local End](#2-install-paperpilot-local-end)
  - [3. Install PaperPilot AI End (Optional)](#3-install-paperpilot-ai-end-optional)
    - [3.1 Deploy MinerU](#31-deploy-mineru)
    - [3.2 Configure LLM Server](#32-configure-llm-server)


#### 1. PaperPilot Architecture Overview

PaperPilot adopts a **dual-end separated architecture**, consisting of two independent deployment ends:

#### 1.1. Local End (PaperPilot Core - Main Service)

- **Tech Stack**: HTML + CSS + JavaScript + Python Flask
- **Features**: Contains all core functionalities of PaperPilot
  - Paper management (upload, classification, search)
  - Literature management (tree classification, full-text search, metadata management)
  - Import/Export (Zotero import, JSON export)
  - Reading history tracking
  - User interface and interactions
- **Deployment Requirements**: Can be deployed on any machine (no GPU required)
- **Dependencies**: Lightweight, does not include AI feature dependencies
- **Startup Command**: `python app.py --host 0.0.0.0 --port 7890`

#### 1.2. AI End (Optional - AI Server)

- **Features**: Provides AI-enhanced functionalities
  - AI Translation (PDF bilingual translation)
  - AI Interpretation (Deep paper analysis)
  - Daily arXiv (Intelligent paper filtering)
- **Components**:
  - **LLM Server**: Deployed using lmdeploy or vllm (recommended: Qwen3-4B-Instruct)
  - **MinerU Server**: For PDF to Markdown parsing (MinerU2.5-2509-1.2B model)
- **Deployment Requirements**:
  - Requires GPU support (CUDA)
  - Can be deployed on a different machine from the Local end
  - Communicates with Local end through API
- **Communication Method**: Local end calls AI end services through HTTP API


### 2. Install PaperPilot Local End

PaperPilot uses `uv` for dependency management.

On the machine where you need to run the PaperPilot main service, install the local end version (does not include AI server dependencies):


<details open>
<summary><strong>Linux Installation</strong></summary>

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Clone repository
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# Create virtual environment (recommended)
uv venv
source .venv/bin/activate
# Install local end version (does not include AI server dependencies)
uv pip install -e ".[local]"
```

</details>

<details close>
<summary><strong>Mac Installation</strong></summary>

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc
# Clone repository
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# Create virtual environment (recommended)
uv venv
source .venv/bin/activate
# Install local end version (does not include AI server dependencies)
uv pip install -e ".[local]"
```

</details>

</details>

<details close>
<summary><strong>Windows Installation</strong></summary>
Using PowerShell as an example


```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Please replace USERNAME below with your username
[System.Environment]::SetEnvironmentVariable("Path", "$env:Path;C:\Users\USERNAME\.local\bin", [System.EnvironmentVariableTarget]::User)
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', [System.EnvironmentVariableTarget]::User)
uv --version
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.venv\Scripts\activate.ps1
uv pip install -e ".[local]"
```

</details>

**Start PaperPilot Main Service**

```bash
python app.py --papers-dir ./papers --host 0.0.0.0 --port 7890
```

Parameter description:
- `--papers-dir`: Paper storage directory path (default: `./papers`)
- `--host`: Server listening address (default: `0.0.0.0`)
- `--port`: Server listening port (default: `7890`)

After the service starts, you can access the PaperPilot interface by visiting `http://0.0.0.0:7890` in your browser.

> **Note**: The local end installation does not include dependencies required for AI features. If you need to use AI translation, AI interpretation, and other features, you need to:
> - Deploy an AI server on another machine (see section 1.2), or
> - Use remote AI API services (such as OpenAI, DeepSeek, etc.), and configure the API address and key in PaperPilot settings

### 3. Install PaperPilot AI End (Optional)

> **Important Note**: AI servers can be deployed on different machines from the PaperPilot main service. The PaperPilot main service only needs the API addresses of these AI servers to use AI features. You can deploy AI servers on machines with GPUs according to your resources, while the PaperPilot main service can be deployed on any machine.


On the machine where you need to deploy MinerU and LLM servers (recommended: machines with GPU), install the server end version:

<details open>
<summary><strong>Linux Installation</strong></summary>

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
# Clone repository
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# Create virtual environment (recommended)
uv venv
source .venv/bin/activate
# Install server end version (includes AI server dependencies)
uv pip install -e ".[server]"
```

</details>

<details close>
<summary><strong>Mac Installation</strong></summary>

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.zshrc
# Clone repository
git clone https://github.com/Mountchicken/PaperPilot.git
cd PaperPilot
# Create virtual environment (recommended)
uv venv
source .venv/bin/activate
# Install server end version (includes AI server dependencies)
uv pip install -e ".[server]"
```

</details>

</details>

<details close>
<summary><strong>Windows Installation</strong></summary>
Using PowerShell as an example


```bash
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# Please replace USERNAME below with your username
[System.Environment]::SetEnvironmentVariable("Path", "$env:Path;C:\Users\USERNAME\.local\bin", [System.EnvironmentVariableTarget]::User)
$env:Path = [System.Environment]::GetEnvironmentVariable('Path', [System.EnvironmentVariableTarget]::User)
uv --version
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
.venv\Scripts\activate.ps1
uv pip install -e ".[server]"
```

</details>

PaperPilot's AI features (**AI Translation**, **AI Interpretation**, **Daily arXiv**) depend on the following services:

- **LLM API Access**: For paper translation, interpretation generation, and arXiv paper intelligent analysis
- **MinerU Service**: For parsing PDFs into Markdown format, supporting high-quality document structure recognition

The following are detailed deployment steps:

#### 3.1 Deploy MinerU

MinerU is used to parse PDF documents into structured Markdown format and is the foundation of the AI interpretation feature.

You have two options for using MinerU:

**Option 1: Use MinerU Official Cloud API (Recommended for Quick Start)**

This is the easiest way to get started without GPU requirements:

1. **Get API Token**: Visit [https://mineru.net/](https://mineru.net/) to register and get your API token
2. **Configure in PaperPilot**: 
   - Go to Settings → Agentic tab
   - Under "MinerU Mode", select "Cloud API"
   - Enter your API token
   - Click "Test" to verify the connection
   - Save settings

That's it! You can now use MinerU's cloud service for PDF parsing without any local deployment.

**Option 2: Deploy MinerU Locally (Requires GPU)**

If you prefer to deploy MinerU on your own server:

**Step1: Download MinerU2.5 Model**

MinerU requires downloading the corresponding model files. Model files should be placed in the `ai_server/` directory:

```bash
mkdir ai_server
# download from huggingface
huggingface-cli download opendatalab/MinerU2.5-2509-1.2B --local-dir ai_server/MinerU2.5-2509-1.2B

# or download from modelscope (for chinese users)
uv add modelscope
modelscope download opendatalab/MinerU2.5-2509-1.2B --local_dir ai_server/MinerU2.5-2509-1.2B
```

**Step2. Start MinerU vLLM Server**

```bash
mineru-vllm-server \
  --model ai_server/MinerU2.5-2509-1.2B \
  --host 0.0.0.0 \
  --port 6001
```

MinerU will start an API server at `http://0.0.0.0:6001` for parsing PDFs into Markdown format.

**Step3. Configure in PaperPilot**:
- Go to Settings → Agentic tab
- Under "MinerU Mode", select "Local Deployment"
- Enter your MinerU server URL (e.g., `http://0.0.0.0:6001`)
- Click "Test" to verify the connection
- Save settings

> **Note**: MinerU server requires GPU support. If using CPU inference, please refer to the [MinerU official documentation](https://github.com/opendatalab/MinerU?tab=readme-ov-file#local-deployment) for configuration.

#### 3.2 Configure LLM Server

PaperPilot's AI features require access to LLM API. You can use one of the following two methods:

**Method 1: Use Locally Deployed LLM (Recommended)**

Deploy a local LLM model using `lmdeploy` or `vllm`. In our actual testing, using `Qwen3-4B-Instruct` as the base model can achieve good results


**Step1: Download Model Weights**

```bash
# download from huggingface
mkdir ai_server
huggingface-cli download Qwen/Qwen3-4B-Instruct-2507 --local-dir ai_server/Qwen3-4B-Instruct-2507

# or download from modelscope (for chinese users)
# If you installed paperpilot[server], modelscope is already included
modelscope download Qwen/Qwen3-4B-Instruct-2507 --local_dir ai_server/Qwen3-4B-Instruct-2507
```

**Step2: Start LLM Server**

```bash
# Single GPU deployment example (4B model)
vllm serve ai_server/Qwen3-4B-Instruct-2507 \
  --api-key token-abc123 \
  --host 0.0.0.0 \
  --port 6002 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.6 \
```

**Method 2: Use Remote LLM API**

If you use remote API services such as OpenAI, DeepSeek, OpenRouter, etc., you can directly configure the API address and key in PaperPilot settings without local deployment
