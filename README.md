# 🎧 MusicAre Audio Source Plugin - Template (Python)

Welcome to the official starter template for creating hot-swappable audio source plugins for the **MusicAre** app ecosystem.

This repository provides a clean, pure-Python development environment to build, test, and package audio streaming providers. Plugins are packaged into compressed `.zip` archives containing pure-Python code and dependencies, and loaded dynamically at runtime by the MusicAre host application without requiring host app recompilation.

---

## ⚡ Two-Tier Just-In-Time (JIT) Resolution Architecture

MusicAre audio source plugins follow a decoupled, two-phase resolution lifecycle:
1. **Phase 1: Candidate Search (`search_candidates`)**: Fast text-based search returning lightweight metadata (`CandidateTrack`: id, title, artist, duration) in **< 0.4s** without extracting or parsing heavy audio formats.
2. **Phase 2: JIT Stream Resolution (`resolve_stream`)**: Direct on-demand extraction of the playable CDN stream URL (`AudioStreamResponse`) in **~0.7s** executed exclusively for the single selected `candidate_id`.

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
│   ├── unit_test.py          # Fast offline unit and candidate parsing tests
│   └── real_api_test.py      # Live E2E tests validating provider search and CDN Range handshake
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
Implement the `BaseAudioSourcePlugin` interface defined by `musicare_plugin_sdk`, using standard absolute imports (`from src...`):

```python
# src/plugin.py
from typing import List
from musicare_plugin_sdk import (
    AudioQuality,
    AudioStreamResponse,
    BaseAudioSourcePlugin,
    CandidateTrack,
    Track,
)
from src.extractor import MyExtractor

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

    def search_candidates(self, track: Track) -> List[CandidateTrack]:
        return MyExtractor.search_candidates(track)

    def resolve_stream(
        self, candidate_id: str, quality: AudioQuality = AudioQuality.HIGH
    ) -> AudioStreamResponse:
        return MyExtractor.resolve_stream(candidate_id, quality)
```

Export the standard entry-point factory function in `src/main.py`:

```python
# src/main.py
from musicare_plugin_sdk import BaseAudioSourcePlugin
from src.plugin import MyAudioSourcePlugin

def get_plugin() -> BaseAudioSourcePlugin:
    """Standard entry-point factory called dynamically by the host engine."""
    return MyAudioSourcePlugin()
```

### 3. Implement Resolution Logic (`src/extractor.py`)
Implement the two distinct phases in your extractor:
* **`search_candidates(track: Track)`**: Search the platform using lightweight queries (e.g. `extract_flat=True` in `yt-dlp`), returning an ordered list of `CandidateTrack` instances with IDs, titles, uploaders, and durations.
* **`resolve_stream(candidate_id: str, quality: AudioQuality)`**: Extract the direct, playable HTTPS stream URL, HTTP headers, codec, bitrate, and expiration timestamp for the given candidate ID.

---

## 🧪 Testing & Verification

### 1. Offline Unit Tests
Verify metadata compliance, parsing, and mocked extraction without network dependencies:
```bash
python -m unittest test/unit_test.py
```

### 2. Real API Tests
Verify actual upstream candidate search, stream resolution, and HTTP Range (`Range: bytes=0-1024`) CDN connectivity:
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
3. **Stage plugin sources**: Preserves the `src/` directory package structure inside `plugin.zip`, ensuring standard `from src...` absolute imports execute identically during local development and in the mobile runtime.
4. **Audit compatibility**: Fails immediately if native binary extensions (`.so`, `.pyd`, `.dylib`, `.dll`) are detected.
5. Clean cache and bytecode files (`__pycache__`, `.pyc`).
6. Generate a portable **`plugin.zip`** in the project root.

---

## 🚢 Publishing & Distribution

* **GitHub Releases**: Attach `plugin.zip` as a release asset matching the version in `plugin.json` (e.g. `v1.0.0`). The MusicAre host application automatically discovers, downloads, and updates plugins via the GitHub REST API.
* **Local Import**: Transfer `plugin.zip` to your device and import it directly into MusicAre via the in-app file picker.
