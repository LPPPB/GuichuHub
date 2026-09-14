"""pytest 共享 fixture

替代 V1 每个测试文件的 sys.path.insert 自注入。
"""

import os
import sys
import tempfile

import pytest

# 把 backend/ 与仓库根目录加入 sys.path（替代 V1 每个测试文件的 sys.path.insert）。
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPOSITORY_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, REPOSITORY_ROOT)
sys.path.insert(0, BACKEND_DIR)


@pytest.fixture
def tmp_db(monkeypatch):
    """每测试独立临时 DB"""
    tmpdir = tempfile.mkdtemp()
    db_path = os.path.join(tmpdir, 'test.db')
    monkeypatch.setenv('DB_PATH', db_path)
    yield db_path


@pytest.fixture
def client(tmp_db):
    """Flask test client"""
    from app import app
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c
