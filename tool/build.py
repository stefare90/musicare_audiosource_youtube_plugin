import os
import shutil
import subprocess
import sys
import zipfile

BUILD_DIR = "build_temp"
ZIP_OUTPUT = "plugin.zip"

def build():
    print("🧹 Cleaning previous build artifacts...")
    if os.path.exists(BUILD_DIR):
        shutil.rmtree(BUILD_DIR)
    os.makedirs(BUILD_DIR, exist_ok=True)

    print("📥 Installing pure-Python dependencies (Flask & yt-dlp)...")
    subprocess.run([
        sys.executable, "-m", "pip", "install",
        "-r", "requirements.txt",
        "--target", BUILD_DIR,
        "--no-compile"
    ], check=True)

    print("📄 Copying source files...")
    shutil.copytree("src", os.path.join(BUILD_DIR, "src"))
    shutil.copy("plugin.json", BUILD_DIR)

    # Create root __main__.py inside the archive
    with open(os.path.join(BUILD_DIR, "__main__.py"), "w") as f:
        f.write("from src.main import start_server\nif __name__ == '__main__':\n    start_server()\n")

    print("⚡ Pre-compiling Python bytecode (.pyc)...")
    subprocess.run([sys.executable, "-m", "compileall", BUILD_DIR], check=True)

    print(f"📦 Generating {ZIP_OUTPUT} archive...")
    with zipfile.ZipFile(ZIP_OUTPUT, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(BUILD_DIR):
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, BUILD_DIR)
                zipf.write(full_path, rel_path)

    shutil.rmtree(BUILD_DIR)
    print(f"✅ Success! Created {ZIP_OUTPUT} ready for MusicAre.")

if __name__ == '__main__':
    build()