# 🎧 MusicAre Audio Source Plugin - Template (Python)

Welcome to the official starter template for creating hot-swappable audio source plugins for the **MusicAre** app ecosystem.

This repository provides a clean, pure-Python development environment to build, test, and package audio streaming providers. Plugins are packaged into compressed `.zip` archives containing pure-Python code and dependencies, and loaded dynamically at runtime by the MusicAre host application without requiring host app recompilation.

---

## ⚠️ Pure-Python Compatibility Rule

To ensure 100% dynamic, Over-The-Air (OTA) execution without triggering mobile OS security violations:

> 📜 **Mandatory Rule:** All plugin code and dependencies in `requirements.txt` **MUST be 100% Pure-Python packages** (packages containing only `.py` code without compiled C, C++, or Rust binary extensions).

*Note: The build tool automatically audits dependencies and rejects any package containing `.so`, `.pyd`, `.dylib`, or `.dll` binaries.*

---

## 📂 Project Structure

```text
musicare_audiosource_template/
├── plugin.json               # Manifest metadata and SDK version constraint
├── requirements.txt          # Runtime dependencies (must be pure-Python)
├── src/
│   ├── __init__.py           # Package exports
│   ├── extractor.py          # Provider-specific search and stream URL extraction
│   ├── plugin.py             # Implementation of BaseAudioSourcePlugin
│   └── main.py               # Standard entry-point factory: get_plugin()
├── test/
│   ├── __init__.py
│   ├── unit_test.py          # Fast offline unit and heuristic ranking tests
│   └── real_api_test.py      # Live E2E tests validating provider APIs and CDN streams
├── .gitignore
└── README.md
```

---

## ⚙️ Prerequisites

* **Python**: `3.10` or higher (`3.11+` recommended)
* **pip**: latest version
* *(Optional for listening test)*: `mpv`, `ffplay`, or `vlc` (e.g. `sudo pacman -S mpv` on Arch Linux, or `brew install mpv` on macOS)

---

## 🚀 Getting Started

### 1. Set Up Virtual Environment
Always work inside an isolated virtual environment:

```bash
# Create virtual environment
python -m venv .venv

# Activate on Linux / macOS
source .venv/bin/activate

# (Optional) On Windows: .venv\Scripts\activate

# Install dependencies and SDK tooling
pip install -r requirements.txt
```

---

## 🛠️ Building a Plugin from the SDK

To build a new audio source provider from this template, follow these three steps:

### 1. Configure Manifest (`plugin.json`)
Open `plugin.json` and customize your plugin identity:

```json
{
  "id": "org.musicare.audiosource.myprovider",
  "packageId": "musicare_audiosource_myprovider_plugin",
  "type": "audioSource",
  "name": "My Provider Audio Source",
  "version": "1.0.0",
  "pluginSdkVersion": "1.0.0",
  "author": "Your Name / Team",
  "description": "MusicAre audio source plugin for My Provider.",
  "repository": "https://github.com/your_org/musicare_audiosource_myprovider_plugin"
}
```

### 2. Implement Plugin Contract (`src/plugin.py` & `src/main.py`)
Implement the `BaseAudioSourcePlugin` interface defined by `musicare_audiosource_sdk`:

```python
# src/plugin.py
from typing import List
from musicare_sdk import BaseAudioSourcePlugin, Track, AudioQuality, AudioStreamResponse
from .extractor import MyExtractor

class MyAudioSourcePlugin(BaseAudioSourcePlugin):
    @property
    def id(self) -> str:
        return "org.musicare.audiosource.myprovider"

    @property
    def name(self) -> str:
        return "My Provider Audio Source"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_stream(self, track: Track, quality: AudioQuality) -> List[AudioStreamResponse]:
        return MyExtractor.resolve_stream(track, quality)
```

Export the standard entry-point factory function:

```python
# src/main.py
from musicare_sdk import BaseAudioSourcePlugin
from .plugin import MyAudioSourcePlugin

def get_plugin() -> BaseAudioSourcePlugin:
    """Standard entry-point factory called dynamically by the host engine."""
    return MyAudioSourcePlugin()
```

### 3. Implement Resolution Logic (`src/extractor.py`)
Search the upstream service, rank candidates with the SDK's built-in `TrackMatcher`, and return an ordered list of `AudioStreamResponse` instances.

---

## 🧪 Testing & Verification

### 1. Offline Unit Tests
Verify metadata compliance and candidate ranking heuristics:
```bash
python -m unittest test/unit_test.py
```

### 2. Real API Tests
Verify actual stream extraction and HTTP Range CDN connectivity against upstream servers:
```bash
python -m unittest test/real_api_test.py
```

### 3. Interactive CLI Playback
Resolve and listen to a real audio stream directly through your local player (`mpv`, `ffplay`, or `vlc`) using the SDK CLI:
```bash
# Test default track (The Beatles - Come Together)
musicare-play

# Test custom artist and title
musicare-play "Queen" "Bohemian Rhapsody"
musicare-play "Pink Floyd" "Comfortably Numb"
```

---

## 📦 Building Distribution Package

Compile, audit, and package your plugin into a clean distribution archive:

```bash
musicare-build
```

The tool will:
1. Validate `plugin.json` syntax and mandatory fields.
2. Install dependencies into a staging directory.
3. **Audit compatibility**: fail immediately if native binary extensions (`.so`, `.pyd`, `.dylib`) are detected.
4. Clean cache and bytecode files.
5. Generate a portable **`plugin.zip`** in the project root.

---

## 🚢 Publishing & Distribution

* **GitHub Releases**: Attach `plugin.zip` as a release asset matching the version in `plugin.json` (e.g. `v1.0.0`). The MusicAre host application automatically discovers, downloads, and updates plugins via the GitHub REST API.
* **Local Import**: Transfer `plugin.zip` to your device and import it directly into MusicAre via the in-app file picker.