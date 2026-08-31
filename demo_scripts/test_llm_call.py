import os
import sys
from dotenv import load_dotenv

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(root_dir, ".env")
    load_dotenv(dotenv_path=env_path)
    
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    
    if not groq_key and not gemini_key:
        print("FAIL: Neither GROQ_API_KEY nor GEMINI_API_KEY is present in .env")
        sys.exit(1)
        
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            completion = client.chat.completions.create(
                model="groq/compound-mini",
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            response = completion.choices[0].message.content
            if response:
                print(f"Provider: Groq")
                print(f"Response: {response.strip()}")
                print("PASS")
                sys.exit(0)
            else:
                print("FAIL: Groq returned empty response")
                sys.exit(1)
        except Exception as e:
            print(f"Groq API call failed: {e}. Trying Gemini...")
            
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.5-flash")
            res = model.generate_content("Hello")
            if res and res.text:
                print(f"Provider: Gemini")
                print(f"Response: {res.text.strip()}")
                print("PASS")
                sys.exit(0)
            else:
                print("FAIL: Gemini returned empty response")
                sys.exit(1)
        except Exception as e:
            print(f"FAIL: Gemini API call failed: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
