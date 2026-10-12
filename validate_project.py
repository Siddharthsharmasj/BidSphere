from pathlib import Path
import ast
import sys

ROOT = Path(__file__).resolve().parent
required = [
    "manage.py", "requirements.txt", "vercel.json",
    "bidsphere/settings.py", "bidsphere/wsgi.py", "bidsphere/asgi.py",
    "auction/models.py", "auction/services.py", "auction/views.py",
    "auction/migrations/0001_initial.py", "auction/migrations/0002_seed_categories.py",
    "auction/migrations/0003_alter_proxybid_priority_at.py",
    "DEPLOY_TO_VERCEL.md", "README_FIRST.md",
]
missing = [path for path in required if not (ROOT / path).exists()]
if missing:
    print("Missing required project files:", *missing, sep="\n- ")
    sys.exit(1)

python_files = 0
for path in ROOT.rglob("*.py"):
    if any(part in {"venv", ".venv", "__pycache__", "staticfiles"} for part in path.parts):
        continue
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        python_files += 1
    except (SyntaxError, UnicodeDecodeError) as exc:
        print(f"Source validation failed in {path}: {exc}")
        sys.exit(1)

print(f"BidSphere source validation passed: {python_files} Python files parsed.")
print("Django runtime checks and tests must be run after dependencies install successfully.")
