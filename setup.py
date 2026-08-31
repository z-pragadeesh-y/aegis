import os
import shutil
import subprocess
import sys

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    venv_dir = os.path.join(root_dir, "venv")
    
    if not os.path.exists(venv_dir):
        print("Creating virtual environment 'venv'...")
        subprocess.run([sys.executable, "-m", "venv", "venv"], check=True)
    else:
        print("Virtual environment 'venv' already exists.")
        
    if os.name == "nt":
        pip_path = os.path.join(venv_dir, "Scripts", "pip.exe")
    else:
        pip_path = os.path.join(venv_dir, "bin", "pip")
        
    req_file = os.path.join(root_dir, "requirements.txt")
    if os.path.exists(req_file):
        print("Installing packages from requirements.txt...")
        subprocess.run([pip_path, "install", "-r", req_file], check=True)
        
    env_example = os.path.join(root_dir, ".env.example")
    env_file = os.path.join(root_dir, ".env")
    if not os.path.exists(env_file) and os.path.exists(env_example):
        print("Copying .env.example to .env...")
        shutil.copyfile(env_example, env_file)
        
    print("\nSetup completed successfully!")
    print("Next steps:")
    print("1. Fill in your GROQ_API_KEY or GEMINI_API_KEY in .env")
    print("2. Run 'docker-compose up -d' to start Qdrant")
    print("3. Run the LLM test script: python demo_scripts/test_llm_call.py")

if __name__ == "__main__":
    main()
