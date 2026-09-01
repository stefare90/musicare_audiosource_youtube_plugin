# 🎧 MusicAre Audio Source Plugin - Template (Python)

Welcome to the official starter template for creating hot-swappable audio source plugins for the **MusicAre** app ecosystem using **Python** and **Flask**.

This repository provides a complete, modern development environment to build, test, and package audio streaming providers. Plugins are packaged into compressed `.zip` archives containing pure-Python code and dependencies (such as `yt-dlp` and `flask`), and executed dynamically by the host application via **`serious_python`** as a persistent local REST daemon [1].

---

## ⚠️ Pure-Python Compatibility Rule

To ensure 100% dynamic, hot-swappable Over-The-Air (OTA) execution across all platforms (**Android, iOS, Linux, macOS, and Windows**) without requiring host app recompilation or triggering mobile App Store security violations:

> 📜 **Mandatory Rule:** All plugin code and dependencies in `requirements.txt` **MUST be 100% Pure-Python packages** (packages containing only `.py` code without compiled C, C++, or Rust binary extensions).

### ✅ Supported (Pure-Python)
* `yt-dlp`, `flask`, `requests`, `spotipy`, `musicbrainzngs`, `mutagen`, `pylast`, `urllib3`

### ❌ Prohibited (C/C++ Native Extensions)
* `numpy`, `pandas`, `scipy`, `pillow`, `cryptography` (with C extensions)

---

## 🏗️ Architecture & Communication

MusicAre uses a high-performance **Local REST Daemon Pattern**:
1. The host application starts `plugin.zip` in background memory with a dynamic ephemeral port assigned by the OS.
2. The plugin boots a lightweight Flask micro-server listening on `127.0.0.1:$PORT`.
3. The plugin resolves tracks into an **ordered list of candidate streams** (sorted descending by match adherence score) to allow instant playback fallback if the primary stream fails.
4. Communication occurs over localhost HTTP REST (`POST /get_stream`) in under 2ms.

```text
┌─────────────────────────────────────────────────────────────┐
│                     MUSICARE HOST APP                       │
│                                                             │
│  1. Injects dynamic port: PORT=54321                        │
│  2. Calls: POST http://127.0.0.1:54321/get_stream           │
│     Body: { track: { name: "Come Together", ... } }         │
└──────────────────────────────┬──────────────────────────────┘
                               │ (Localhost REST / JSON)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             FLASK RPC DAEMON (plugin.zip)                   │
│                                                             │
│  3. Search YouTube Music using pure-Python yt-dlp           │
│  4. Rank candidates by duration & title adherence score     │
│  5. Return ordered list of direct stream URLs               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│             ORDERED STREAM CANDIDATES (JSON ARRAY)          │
│                                                             │
│  6. HTTP 200 Response:                                      │
│     [                                                       │
│       { "url": "https://... (Primary #1 Match)", ... },     │
│       { "url": "https://... (Fallback #2 Match)", ... }     │
│     ]                                                       │
└─────────────────────────────────────────────────────────────┘
```

---

## 📂 Project Structure

```text
musicare_audiosource_youtube_plugin/
├── src/                      # 100% Python source code
│   ├── sdk/                  # Embedded SDK contracts & types
│   │   ├── __init__.py
│   │   ├── types.py          # Track, AudioQuality, AudioStreamResponse dataclasses
│   │   └── base_plugin.py    # BaseAudioSourcePlugin abstract class
│   │
│   ├── __init__.py
│   ├── matcher.py            # Scoring & matching heuristics engine
│   ├── extractor.py          # yt-dlp search and stream URL extraction
│   └── main.py               # Flask REST server (/ping, /get_stream)
│
├── test/                     # [PYTHON] Fast unit tests
│   ├── __init__.py
│   └── test_plugin.py
│
├── integration_test/         # [FLUTTER] Native E2E integration test
│   └── plugin_test.dart
│
├── tool/
│   ├── build.py              # Packaging script (bundles dependencies & builds plugin.zip)
│   └── play_test.py          # Interactive CLI playback testing utility
│
├── plugin.json               # MusicAre plugin manifest
├── pubspec.yaml              # Flutter integration test harness
├── requirements.txt          # Production dependencies (yt-dlp, flask)
└── README.md
```

---

## ⚙️ Prerequisites

* **Python**: `3.10` or higher (`3.11+` recommended)
* **pip**: latest version
* **Flutter SDK**: `v3.10.0` or higher
* *(Optional for listening test)*: `mpv`, `ffplay`, or `vlc` (e.g. `sudo pacman -S mpv` on Arch/EndeavourOS)

---

## 🚀 Getting Started & Development

### 1. Set Up Python Virtual Environment
Always work inside an isolated virtual environment (`.venv`):

```bash
# Create virtual environment
python -m venv .venv

# Activate on Linux / macOS
source .venv/bin/activate

# (Optional) On Windows: .venv\Scripts\activate

# Install production dependencies
pip install -r requirements.txt

# Download Flutter test harness dependencies
flutter pub get
```

---

### 2. Configure Manifest (`plugin.json`)
```json
{
  "id": "org.musicare.audiosource.mysource",
  "packageId": "musicare_audiosource_mysource_plugin",
  "type": "audioSource",
  "name": "My Source Audio Provider",
  "version": "1.0.0",
  "author": "Your Name / Organization",
  "description": "Audio streaming provider for MusicAre powered by Python.",
  "repository": "https://github.com/your_org/music_are_mysource_audiosource_plugin"
}
```

---

## 🧪 Testing & Verification

### 1. Built-in Python Unit Tests (unittest)
Make sure `.venv` is activated:
```bash
python -m unittest discover -s ./test -t . -p "test_*.py"
```

### 2. Interactive Audio Playback Testing (`tool/play_test.py`)
Verify real-time playback through your speakers/headphones:
```bash
# Test default track (The Beatles - Come Together)
python tool/play_test.py

# Test any custom artist and song
python tool/play_test.py "Queen" "Bohemian Rhapsody"
python tool/play_test.py "Pink Floyd" "Comfortably Numb"
```

### 3. Live Native Integration Tests (Flutter / serious_python)
Build `plugin.zip` and run Flutter integration tests on Linux desktop:
```bash
python tool/build.py
flutter test -d linux integration_test/plugin_test.dart
```

---

## 📦 Building & Packaging for Distribution

Generate the distribution archive:
```bash
python tool/build.py
```

The resulting **`plugin.zip`** contains [1]:
* `plugin.json` (Manifest)
* `__main__.py` & `src/` (Compiled `.pyc` bytecode)
* Pre-bundled pure-Python wheels (`yt-dlp`, `flask`, `werkzeug`, etc.)

---

## 🚢 Publishing & Distribution

* **GitHub Releases**: Attach `plugin.zip` as a release asset matching the version in `plugin.json` (e.g. `v1.0.0`). The MusicAre host application will automatically discover, download, and update it via the GitHub REST API.
* **Local Import**: Transfer `plugin.zip` to your device and import it directly into MusicAre via the in-app file picker.
