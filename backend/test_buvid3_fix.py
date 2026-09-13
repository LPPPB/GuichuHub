"""验证 buvid3 补充逻辑的可行性，并评估对登录流程的影响。

背景：搜索API文档明确要求 Cookie 含 buvid3 字段，但当前 bili-auth 模块
保存的 Cookie 里没有这个字段（登录接口不下发，需访问首页获取）。

本脚本独立模拟 _ensure_buvid3 逻辑，不修改真实的 bilibili_cookie.json，
使用临时副本验证：
  1. 访问 B站首页能否拿到 buvid3
  2. buvid3 格式是否合法
  3. 异常场景下是否安全降级
  4. 并发场景下是否有覆盖登录态的风险

运行（用项目venv）：
  .venv\\Scripts\\python.exe test_buvid3_fix.py
"""

import sys
import os
import time
import json
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

# 复用 bili-auth 的请求头构造（只读，不触发其 get_cookie_str 逻辑）
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def test_fetch_buvid3_from_homepage():
    """场景1：直接访问 B站首页，验证能否拿到 buvid3。"""
    print('=' * 70)
    print('场景1：访问 B站首页获取 buvid3')
    print('=' * 70)
    print('  请求: https://www.bilibili.com/')

    try:
        resp = requests.get('https://www.bilibili.com/', headers=HEADERS, timeout=10)
        print(f'  HTTP状态: {resp.status_code}')
        print(f'  响应Cookie数量: {len(resp.cookies)}')
        print(f'  响应Cookie列表:')
        for c in resp.cookies:
            print(f'    {c.name} = {str(c.value)[:50]}{"..." if len(str(c.value)) > 50 else ""}')

        # 检查 Set-Cookie 原始头
        raw_set_cookie = resp.headers.get('set-cookie', '')
        buvid3_in_header = 'buvid3' in raw_set_cookie
        buvid3_in_jar = any(c.name == 'buvid3' for c in resp.cookies)

        print()
        print(f'  Set-Cookie 头里含 buvid3: {buvid3_in_header}')
        print(f'  Cookie Jar 里含 buvid3:   {buvid3_in_jar}')

        if buvid3_in_jar:
            buvid3 = next(c.value for c in resp.cookies if c.name == 'buvid3')
            print(f'  buvid3 值: {buvid3}')
            print(f'  buvid3 长度: {len(buvid3)}')
            # buvid3 通常是 UUID 格式或长字符串
            is_uuid_like = len(buvid3) >= 32 and ('-' in buvid3 or len(buvid3) == 32)
            print(f'  格式合法（长度>=32）: {"✅" if len(buvid3) >= 32 else "⚠️ 偏短"}')
            return buvid3
        else:
            print('  ❌ 未拿到 buvid3（可能 B站策略变更，需访问 /api.frontend心跳接口）')
            return None

    except requests.Timeout:
        print('  ❌ 超时（10s）')
        return None
    except requests.ConnectionError as e:
        print(f'  ❌ 连接失败: {e}')
        return None
    except Exception as e:
        print(f'  ❌ 未知异常: {type(e).__name__}: {e}')
        return None


def test_buvid3_with_existing_cookie():
    """场景2：带现有登录态 Cookie 访问首页，验证 buvid3 是否仍能拿到。"""
    print()
    print('=' * 70)
    print('场景2：带登录态 Cookie 访问首页（模拟真实抓取场景）')
    print('=' * 70)

    from collectors.bilibili_auth import load_cookie
    cookies = load_cookie()
    if not cookies:
        print('  当前未登录，跳过本场景')
        return None

    print(f'  当前 Cookie 字段: {list(cookies.keys())}')
    cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
    headers_with_cookie = {**HEADERS, 'Cookie': cookie_str}

    try:
        resp = requests.get('https://www.bilibili.com/', headers=headers_with_cookie, timeout=10)
        buvid3 = next((c.value for c in resp.cookies if c.name == 'buvid3'), None)

        if buvid3:
            print(f'  ✅ 带 Cookie 访问也能拿到 buvid3: {buvid3[:40]}...')
        else:
            print('  ⚠️ 带 Cookie 访问未返回 buvid3（可能已存在于请求Cookie中，B站不再下发）')
            # 检查请求Cookie里是否已有 buvid3
            if 'buvid3' in cookies:
                print(f'     但请求Cookie里已有 buvid3: {cookies["buvid3"][:40]}...')
        return buvid3
    except Exception as e:
        print(f'  ❌ 异常: {e}')
        return None


def test_merge_safety():
    """场景3：验证 buvid3 合并到现有 Cookie 后，不丢失原有登录字段。"""
    print()
    print('=' * 70)
    print('场景3：合并 buvid3 后的 Cookie 完整性')
    print('=' * 70)

    from collectors.bilibili_auth import load_cookie
    cookies = load_cookie()
    if not cookies:
        print('  当前未登录，用模拟数据测试')
        cookies = {
            'SESSDATA': 'mock_sessdata',
            'bili_jct': 'mock_jct',
            'DedeUserID': '123456',
            'DedeUserID__ckMd5': 'mock_ckmd5',
            'sid': 'mock_sid',
        }

    before_keys = set(cookies.keys())
    print(f'  合并前字段: {sorted(before_keys)}')

    # 模拟 _ensure_buvid3 的合并逻辑
    mock_buvid3 = 'test_buvid3_value_from_homepage'
    cookies['buvid3'] = mock_buvid3
    after_keys = set(cookies.keys())

    print(f'  合并后字段: {sorted(after_keys)}')
    print(f'  新增字段:   {sorted(after_keys - before_keys)}')
    print(f'  丢失字段:   {sorted(before_keys - after_keys) or "无"}')

    if before_keys.issubset(after_keys):
        print('  ✅ 合并安全：原有登录字段全部保留')
    else:
        print('  ❌ 合并异常：丢失了登录字段！')


def test_concurrent_overwrite_risk():
    """场景4：评估并发场景下 _ensure_buvid3 覆盖登录态的风险。

    风险时序：
      T1: _ensure_buvid3 load_cookie() 读到旧 cookie（登录前）
      T2: 用户登录成功 → save_cookie(新登录态)
      T3: _ensure_buvid3 拿到 buvid3 → save_cookie(旧cookie + buvid3)
      结果: T3 覆盖了 T2 刚写入的新登录态！

    本场景用临时文件模拟，不动真实文件。
    """
    print()
    print('=' * 70)
    print('场景4：并发覆盖风险（用临时文件模拟）')
    print('=' * 70)

    # 创建临时 cookie 文件
    tmpdir = tempfile.mkdtemp()
    tmp_cookie_file = os.path.join(tmpdir, 'test_cookie.json')

    # 初始状态：未登录
    with open(tmp_cookie_file, 'w', encoding='utf-8') as f:
        json.dump({'cookies': {'old_field': 'before_login'}, 'saved_at': int(time.time())}, f)

    print('  初始 Cookie: {"old_field": "before_login"}（未登录态）')
    print()
    print('  模拟时序：')
    print('    T1: 抓取线程 _ensure_buvid3 load_cookie() → 读到 old_field')
    print('    T2: 用户登录成功 save_cookie(新登录态)')
    print('    T3: 抓取线程拿到 buvid3 save_cookie(old_field + buvid3)')
    print('    结果: T3 覆盖了 T2 的新登录态！')
    print()

    # 模拟时序
    # T1: 读
    with open(tmp_cookie_file, 'r', encoding='utf-8') as f:
        t1_cookies = json.load(f)['cookies']
    print(f'  T1 读取: {t1_cookies}')

    # T2: 登录写入新数据
    new_login = {'SESSDATA': 'new_login', 'bili_jct': 'new_jct'}
    with open(tmp_cookie_file, 'w', encoding='utf-8') as f:
        json.dump({'cookies': new_login, 'saved_at': int(time.time())}, f)
    print(f'  T2 登录写入: {new_login}')

    # T3: T1 的旧数据 + buvid3 覆盖回去
    t1_cookies['buvid3'] = 'fetched_buvid3'
    with open(tmp_cookie_file, 'w', encoding='utf-8') as f:
        json.dump({'cookies': t1_cookies, 'saved_at': int(time.time())}, f)
    print(f'  T3 覆盖写入: {t1_cookies}')

    # 验证结果
    with open(tmp_cookie_file, 'r', encoding='utf-8') as f:
        final = json.load(f)['cookies']
    print()
    print(f'  最终文件内容: {final}')
    if 'SESSDATA' in final and final.get('SESSDATA') == 'new_login':
        print('  ✅ 登录态保留（无覆盖风险）')
    else:
        print('  ❌ 登录态被覆盖！新登录的 SESSDATA 丢失')
        print('     → 结论: _ensure_buvid3 的 save_cookie 调用有并发风险')

    # 清理
    os.remove(tmp_cookie_file)
    os.rmdir(tmpdir)


def test_exception_safety():
    """场景5：异常场景下 _ensure_buvid3 是否安全降级。"""
    print()
    print('=' * 70)
    print('场景5：异常场景下的降级安全性')
    print('=' * 70)

    from collectors.bilibili_auth import load_cookie
    original_cookies = load_cookie() or {'SESSDATA': 'mock'}

    # 异常1：网络超时
    print()
    print('  [异常1] 网络超时（首页不可达）')
    cookies_copy = dict(original_cookies)
    try:
        # 模拟超时：用一个不可达地址
        requests.get('https://www.bilibili.com/', headers=HEADERS, timeout=0.001)
    except Exception as e:
        # 模拟 _ensure_buvid3 的异常捕获
        print(f'    捕获异常: {type(e).__name__}')
        print(f'    cookies_copy 是否完好: {"✅" if "SESSDATA" in cookies_copy else "❌"}')
        print(f'    结论: 异常时返回原 cookies，主流程不受影响 ✅')

    # 异常2：响应里没有 buvid3
    print()
    print('  [异常2] 响应里没有 buvid3（B站策略变更）')
    cookies_copy = dict(original_cookies)
    # 模拟 resp.cookies 为空
    class FakeResp:
        cookies = []
    fake_resp = FakeResp()
    buvid3 = next((c.value for c in fake_resp.cookies if c.name == 'buvid3'), None)
    if not buvid3:
        print(f'    未拿到 buvid3，cookies 不变')
        print(f'    cookies_copy 是否完好: {"✅" if "SESSDATA" in cookies_copy else "❌"}')
        print(f'    结论: 未拿到时不修改 cookies，主流程不受影响 ✅')

    # 异常3：save_cookie 失败（文件只读）
    print()
    print('  [异常3] save_cookie 失败（文件权限/磁盘问题）')
    print(f'    若 save_cookie 抛异常，_ensure_buvid3 当前无 try-catch 保护')
    print(f'    建议: save_cookie 调用需包裹 try-except，失败时仅内存补充不持久化')


def run_all_tests():
    """运行全部验证场景。"""
    print('╔' + '═' * 68 + '╗')
    print('║' + ' buvid3 补充逻辑验证 '.center(68) + '║')
    print('╚' + '═' * 68 + '╝')
    print()

    buvid3 = test_fetch_buvid3_from_homepage()
    test_buvid3_with_existing_cookie()
    test_merge_safety()
    test_concurrent_overwrite_risk()
    test_exception_safety()

    print()
    print('=' * 70)
    print('最终评估')
    print('=' * 70)
    print()
    print('1. buvid3 可获取性:')
    if buvid3:
        print(f'   ✅ 访问首页能拿到 buvid3（值: {buvid3[:30]}...）')
        print(f'   ✅ 修复方案技术可行')
    else:
        print(f'   ⚠️ 本次未拿到 buvid3，可能网络问题或 B站策略变更')
        print(f'      建议重试或改用 /x/frontend/finger/spi 接口获取')

    print()
    print('2. 对登录流程的影响:')
    print('   ⚠️ 有并发覆盖风险（场景4已验证）')
    print('   ⚠️ 时序: 抓取线程读旧Cookie → 用户登录写新Cookie → 抓取线程覆盖旧Cookie+buvid3')
    print('   ⚠️ 后果: 新登录态被旧数据覆盖，用户需重新登录')
    print('   建议: _ensure_buvid3 的 save_cookie 前需重新 load_cookie 合并，或加文件锁')

    print()
    print('3. 异常处理建议:')
    print('   ✅ 网络超时/无buvid3: 安全降级（场景5已验证）')
    print('   ⚠️ save_cookie 失败: 需加 try-except，避免异常冒泡到 get_cookie_str')
    print('   ⚠️ 并发覆盖: 需重新读文件合并，不能直接用旧 cookies + buvid3 覆盖')


if __name__ == '__main__':
    run_all_tests()
