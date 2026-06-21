"""Print a small local startup diagnostic for MedRisk Intelligence v5."""
from __future__ import annotations
import importlib
import sys
from pathlib import Path

print("Python:", sys.version)
print("Working folder:", Path.cwd())
for filename in ["app.py", "requirements.txt", "run_app.sh"]:
    print(f"{filename} present:", Path(filename).exists())
for module in ["streamlit", "pandas", "openpyxl", "pypdf", "docx", "sklearn", "plotly", "rapidfuzz"]:
    try:
        imported = importlib.import_module(module)
        print("OK ", module, getattr(imported, "__version__", "installed"))
    except Exception as exc:
        print("FAIL", module, exc)
print("\nIf every required module is OK, start with:")
print("python -m streamlit run app.py")
