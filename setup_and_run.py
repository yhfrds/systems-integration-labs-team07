import os
import sys
import subprocess
import platform
from pathlib import Path

def run(cmd, shell=False):
    """Run a command and stream output in real-time."""
    print(f"\n>>> Running: {cmd}")
    subprocess.run(cmd, shell=shell, check=True)

def main():
    # Determine platform
    is_windows = platform.system() == "Windows"
    venv_dir = Path("venv")

    # Step 1: Create virtual environment
    if not venv_dir.exists():
        run([sys.executable, "-m", "venv", str(venv_dir)])

    # Step 2: Activate virtual environment (platform-specific)
    if is_windows:
        activate_path = venv_dir / "Scripts" / "activate"
        pip_exec = venv_dir / "Scripts" / "pip"
        python_exec = venv_dir / "Scripts" / "python"
    else:
        activate_path = venv_dir / "bin" / "activate"
        pip_exec = venv_dir / "bin" / "pip"
        python_exec = venv_dir / "bin" / "python"

    # Step 3: Upgrade pip
    run([str(python_exec), "-m", "pip", "install", "--upgrade", "pip"])

    # Step 4: Install dependencies
    if Path("requirements.txt").exists():
        run([str(pip_exec), "install", "-r", "requirements.txt"])
    else:
        print("⚠️  No requirements.txt found — skipping dependency installation.")

    # Step 5: Run your app
    if Path("run.py").exists():
        run([str(python_exec), "run.py"])
    else:
        print("⚠️  No run.py found — skipping execution.")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"❌ Command failed: {e}")
        sys.exit(1)
