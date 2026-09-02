import os

dir_path = os.path.join(os.path.dirname(__file__), "phase5_screenshots")
if not os.path.exists(dir_path):
    print("Directory phase5_screenshots does not exist.")
else:
    files = sorted(os.listdir(dir_path))
    print(f"Found {len(files)} files in phase5_screenshots:")
    for f in files:
        full_p = os.path.join(dir_path, f)
        size = os.path.getsize(full_p)
        print(f"  {f}: {size} bytes ({'VALID PNG' if size > 10000 else 'INVALID/EMPTY'})")
