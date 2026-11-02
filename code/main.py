"""Main entry point for Ghost Data Still Exists (AGENTS.md section 1, 6).

Can be executed as:
    python code/main.py --help
    python code/main.py --sample
    python code/main.py --input dataset/deletion_requests.csv --output output.csv
"""

import sys
from pathlib import Path

# Ensure code/ is in sys.path
CODE_DIR = Path(__file__).resolve().parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from src.core.pipeline import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
