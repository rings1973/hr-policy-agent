from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

APP_NAME = os.getenv("APP_NAME", "hr-policy-agent")
APP_ENV = os.getenv("APP_ENV", "development")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
VECTOR_TOP_K = int(os.getenv("VECTOR_TOP_K", "4"))
DATA_DIR = BASE_DIR / "app" / "data"
POLICY_DIR = DATA_DIR / "policies"
EMPLOYEE_FILE = DATA_DIR / "employee_data.json"
