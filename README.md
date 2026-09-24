# Victor AI Assistant

An intelligent, local-first, multimodal AI desktop assistant powered by Google Gemini Live API. Victor combines real-time bidirectional voice streaming, computer & OS automation, Android phone companion features, long-term memory, multi-agent project orchestration, and proactive reminders into an interactive desktop companion.

Whether you want to keep the name **Victor** or customize it to your own personal assistant (e.g. *Jarvis*, *Friday*, *Aria*), this repository is structured to make cloning, configuring, and personalizing straightforward.

---

## Table of Contents

- [Overview & Architecture](#overview--architecture)
- [Available Features & Tools](#available-features--tools)
- [Prerequisites](#prerequisites)
- [Quick Start & Setup](#quick-start--setup)
- [Security & Credential Protection](#security--credential-protection)
- [Personalizing Your Assistant](#personalizing-your-assistant)
- [Android Phone Companion](#android-phone-companion)
- [Running Victor](#running-victor)
- [Project Structure](#project-structure)

---

## Overview & Architecture

Victor operates as a local web service (FastAPI + WebSockets) connected to a sleek browser-based UI featuring an interactive 3D/animated orb. 

- **Brain & Voice**: Powered by Google Gemini Live API (`gemini-3.8-live`) with bidirectional audio streaming and low-latency interruptions.
- **Security & Authorization**: Two-layer authentication (Layer 1: Security PIN + Windows Hello biometric verification; Layer 2: Tool permission engine and risk-based confirmation gates).
- **Decision Engine**: TypeSafe Jev / OpenRouter integration for evaluating memory-worthiness and intent routing.
- **Permanent Memory & Reminders**: Local SQLite database storing user facts, preferences, conversation turns, and a scheduled background reminder daemon.

---

## Available Features & Tools

Victor comes packed with built-in tools organized across dedicated domains:

| Category | Tools & Capabilities |
| :--- | :--- |
| **System & OS Control** | Battery, Wi-Fi network, Bluetooth status, screen brightness adjustment, master volume & mute, CPU/RAM performance telemetry, Windows settings launcher, system & app notifications, and Windows / assistant locking. |
| **Computer Automation** | Launch and close applications (Notepad, Calculator, VS Code, Task Manager, etc.), type text, press keyboard shortcuts, click, scroll, and submit forms. |
| **Screen Understanding** | Real-time screen capture analysis to summarize active windows, explain errors, or inspect UI forms before taking actions. |
| **Web & Browser** | Playwright browser automation (search the web, open URLs, click elements, open/close tabs), plus dedicated quick-launchers for Claude AI, ChatGPT, Gemini, YouTube, and Wikipedia. |
| **Coding & Workspace** | Automatic workspace resolution, code execution, command execution in terminal, workspace status monitoring, file deletion/creation, and VS Code control. Powered by Groq inference (`openai/gpt-oss-20b`). |
| **Multi-Agent Orchestration** | Start research and software project planning pipelines across Gemini, ChatGPT, and Claude. Review generated project specifications, monitor pipeline stages, and download generated artifacts to your Downloads directory. |
| **Permanent Memory** | Remember personal preferences (`memory_remember`), recall historical context (`memory_recall`), and remove stored memories (`memory_forget`) backed by SQLite. |
| **Real-Time Reminders** | Persistent date and time task scheduler: create reminders (`reminder_create`), list tasks (`reminder_list`), mark done (`reminder_complete`), postpone/reschedule (`reminder_postpone`), and remove reminders (`reminder_delete`) with automated background checking. |
| **Google Services** | Create notes and search in Google Keep, schedule events in Google Calendar, and generate or join Google Meet calls. |
| **Android Companion** | Connect with the companion Android app via WebSocket: check phone battery and status, search and resolve contacts, make phone calls with voice confirmation, answer/reject incoming calls, and search YouTube on your mobile device. |
| **Free Public APIs** | Real-time weather forecasts, stock prices, forex currency rates, crypto prices, news headlines, public IP lookup, and public holidays. |

---

## Prerequisites

1. **Operating System**: Windows 10/11 (required for Windows Hello, pywin32, and Windows OS automation).
2. **Python**: Python 3.10 to 3.12 installed and added to your `PATH`.
3. **Google Gemini API Key**: Access to Google Gemini Live API.
4. **Optional API Keys**:
   - **Groq API Key**: For coding computer control and fast local coding execution.
   - **OpenRouter API Key**: For the secondary Decision Layer / Jev memory evaluation.
   - **Finnhub / NewsAPI / ExchangeRate APIs**: For live market, stock, and news API tools (optional fallbacks exist).

---

## Quick Start & Setup

### 1. Clone the Repository
```bash
git clone https://github.com/AnubhavDataSci25/Victor-AI-Agent.git
cd "Victor-AI-Agent"
```

### 2. Create and Activate a Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

### 3. Install Dependencies
```powershell
pip install -r requirements.txt
playwright install chromium
```

### 4. Configure Environment Variables
Copy or create a `.env` file in the project root:

```ini
# Core AI Provider
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-3.8-live

# Server Host & Port
VICTOR_HOST=0.0.0.0
VICTOR_PORT=8000

# Security & Authentication
VICTOR_AUTH_MODE=pin
VICTOR_DEFAULT_PIN=1234
BIOMETRIC_TIMEOUT_SECONDS=60

# Coding Assistant (Optional - Groq)
GROQ_API_KEY=your_groq_api_key_here
GROQ_CODING_MODEL=openai/gpt-oss-20b

# Decision Layer (Optional - OpenRouter)
OPENROUTER_API_KEY=your_openrouter_api_key_here
JEV_MODEL=~typesafe/jev-latest
```

---

## Security & Credential Protection

> [!IMPORTANT]
> **Zero-Leak Policy**: Keep your credentials secure at all times.

1. **Never commit `.env` or `config/secrets.yaml`**: These files are git-ignored by default. Never push real keys, PINs, or private tokens to public repositories.
2. **Local PIN / Password Hash**: Security PINs and passphrases are never stored in plaintext. They are hashed using `argon2id` and stored inside `config/secrets.yaml`.
3. **Execution Choke-point**: All tool executions are validated through `ToolGateway`, which enforces session status and explicit user approval before executing any destructive action (e.g. deleting files, initiating calls, moving directories).
4. **Untrusted Data Hygiene**: Model prompts instruct the assistant to treat web pages and tool outputs as untrusted data to mitigate prompt injection.

---

## Personalizing Your Assistant

Want to rename the assistant (e.g. from **Victor** to **Jarvis** or **Aria**) and customize who it serves? Here are the few places you need to adjust:

### 1. System Prompt & Personality (`app/live/session.py`)
Search for `system_instruction` in [app/live/session.py](file:///app/live/session.py) around lines 115–125:
- Change the assistant's name: Replace `"You are Victor..."` with `"You are <YourAssistantName>..."`.
- Change the user's name / title: Replace `"dedicated exclusively to Anubhav Sir. Address the user as 'Sir'."` with your preferred name and title (e.g., `"dedicated exclusively to Alex. Address the user as 'Alex'."`).
- Customize personal greetings and custom quirks to match your preferences.

### 2. UI Title & Header (`app/ui/static/index.html` & `app/main.py`)
- In `app/ui/static/index.html`, update the `<title>` tag and any header text with your assistant's name.
- In `app/main.py`, update `FastAPI(title="Victor 2.0 API")` if desired.

### 3. Voice & Persona (`app/live/session.py`)
Victor uses Gemini Live's prebuilt voice:
```python
speech_config=types.SpeechConfig(
    voice_config=types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(
            voice_name="Dipper"  # Options: Aoede, Charon, Fenrir, Kore, Puck, Dipper
        )
    )
)
```
Switch to any supported Gemini voice that fits your assistant's vibe.

### 4. Allowed Workspace Roots (`app/config.py` & `config/default.yaml`)
In `app/config.py`, customize `approved_workspace_roots` to point to the local project directories and drives on your machine (e.g. `C:\Projects`, `D:\Dev`).

---

## Android Phone Companion

The `android/` directory contains an Android companion application that pairs with your desktop assistant:

1. Connect your Android phone and desktop to the same local Wi-Fi network.
2. Build and install the Android app onto your phone.
3. Open the companion app, scan the pairing QR code displayed on the Victor web UI (or enter the desktop's local IP address).
4. Once paired, you can ask your assistant to make phone calls, answer/reject incoming calls, check battery level, and launch YouTube on your mobile device.

---

## Running Victor

### Method 1: Using the Batch Launcher (Windows)
Double-click `Victor.bat` or run:
```cmd
Victor.bat
```
*(Note: If you have moved the repository from `E:\Victor AI Agent`, update the project directory path in `Victor.bat` accordingly).*

### Method 2: Command Line (PowerShell / Terminal)
```powershell
.\.venv\Scripts\activate
python -m app.main
```

Then open your browser at **http://localhost:8000** to interact with your assistant!

---

## Project Structure

```
Victor AI Agent/
├── app/
│   ├── agent/            # State and session management
│   ├── api_tools/        # Weather, stock, forex, news, crypto public APIs
│   ├── auth/             # PIN/Argon2id authentication & Windows Hello verification
│   ├── coding/           # Terminal execution, workspace inspection & Groq coding agent
│   ├── decision/         # Decision Engine (OpenRouter / Jev)
│   ├── gateway/          # Tool Gateway, risk classification & tracing
│   ├── google_services/  # Keep, Calendar, and Meet integrations
│   ├── live/             # Gemini Live API bidirectional WebSocket session & dispatcher
│   ├── memory/           # Persistent SQLite long-term memory & user facts
│   ├── multi_agent/      # Multi-agent collaboration with Claude, ChatGPT, and Gemini
│   ├── news/             # Current affairs and news story reader
│   ├── phone/            # WebSocket bridge for Android phone companion
│   ├── reminders/        # Real-time task reminder store & background scheduler
│   ├── tools/            # Base tool registry and tool implementations
│   ├── ui/static/        # Web UI (3D orb, transcripts, controls)
│   ├── config.py         # Pydantic configuration loader
│   └── main.py           # FastAPI entry point & WebSocket endpoints
├── config/
│   └── default.yaml      # Default configuration settings
├── android/              # Android Companion App source code
├── tests/                # Automated pytest suite
├── Victor.bat            # One-click Windows launch script
├── requirements.txt      # Python dependencies
└── README.md             # Project documentation
```

---

## License

This project is intended for personal and educational use. Feel free to fork, adapt, and build your own custom AI assistant!
