#!/usr/bin/env python3
"""
Cordys CRM 公共库 — API 调用、表单配置、产品解析等基础设施
"""
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib import request
from urllib.error import HTTPError, URLError

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

# 从 scripts/ 往上查找 .env，兼容不同安装目录结构
ENV_FILE = None
_dir = SCRIPT_DIR
for _ in range(3):
    if (_dir / ".env").exists():
        ENV_FILE = _dir / ".env"
        break
    _dir = _dir.parent

if ENV_FILE:
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

CORDYS_CRM_DOMAIN = os.environ.get("CORDYS_CRM_DOMAIN", "https://www.cordys.cn")
CORDYS_ACCESS_KEY = os.environ.get("CORDYS_ACCESS_KEY", "")
CORDYS_SECRET_KEY = os.environ.get("CORDYS_SECRET_KEY", "")


def die(msg):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(1)


def api(method, path, data=None):
    """调用 Cordys CRM 接口"""
    if not CORDYS_ACCESS_KEY or not CORDYS_SECRET_KEY:
        die("未设置 CORDYS_ACCESS_KEY 或 CORDYS_SECRET_KEY")

    url = f"{CORDYS_CRM_DOMAIN}{path}"
    headers = {
        "X-Access-Key": CORDYS_ACCESS_KEY,
        "X-Secret-Key": CORDYS_SECRET_KEY,
        "Content-Type": "application/json;charset=UTF-8",
    }

    body = None
    if data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")

    req = request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with request.urlopen(req) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return json.loads(resp.read().decode(charset, errors="replace"))
    except HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        die(f"请求失败: HTTP {e.code} {detail}")
    except URLError as e:
        die(f"请求失败: {e}")
