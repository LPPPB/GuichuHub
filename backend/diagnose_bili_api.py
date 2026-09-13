"""B站接口异常诊断工具

用途：当抓取异常（412频发/返回空/Cookie失效）时，一键定位根因。
按顺序检查 5 层：登录态 → buvid3 → WBI签名 → 搜索API → 详情API

运行（用项目venv）：
  .venv\\Scripts\\python.exe diagnose_bili_api.py
"""

import sys
import os
import time
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
}


def run_diagnosis():
    """运行完整诊断流程。"""
    print('╔' + '═' * 68 + '╗')
    print('║' + ' B站接口异常诊断 '.center(68) + '║')
    print('╚' + '═' * 68 + '╝')
    print()

    # ── 第1层：登录态检查 ──
    print('【第1层】登录态检查')
    print('-' * 70)
    from collectors.bilibili_auth import load_cookie, get_user_info
    cookies = load_cookie()
    if not cookies:
        print('  ❌ 未登录（无 Cookie 文件或无 SESSDATA）')
        print('     → 影响：所有需要登录的接口都会失败')
        print('     → 解决：前端扫码重新登录')
        return
    print(f'  Cookie 字段: {sorted(cookies.keys())}')
    print(f'  SESSDATA: {"存在" if cookies.get("SESSDATA") else "缺失 ❌"}')

    user = get_user_info()
    if user:
        print(f'  登录用户: {user.get("name")} (mid={user.get("mid")})')
        print(f'  登录态: ✅ 有效')
    else:
        print(f'  登录态: ❌ 失效（SESSDATA 过期）')
        print('     → 影响：登录接口全部失败')
        print('     → 解决：前端扫码重新登录')
        return
    print()

    # ── 第2层：buvid3 检查 ──
    print('【第2层】buvid3 检查（搜索API文档要求）')
    print('-' * 70)
    if 'buvid3' in cookies:
        buvid3 = cookies['buvid3']
        print(f'  buvid3: {buvid3[:40]}...')
        print(f'  长度: {len(buvid3)} {"✅" if len(buvid3) >= 32 else "⚠️ 偏短"}')
    else:
        print(f'  buvid3: ❌ 缺失')
        print('     → 影响：搜索API 触发 412 限流概率升高')
        print('     → 解决：调用 get_cookie_str() 会自动补充，或手动跑：')
        print('            from collectors.bilibili_auth import get_cookie_str; get_cookie_str()')
        print('     → 若补充失败：B站首页策略变更，改用 /x/frontend/finger/spi 接口')
    print()

    # ── 第3层：WBI签名检查 ──
    print('【第3层】WBI签名检查（新搜索API要求）')
    print('-' * 70)
    try:
        from collectors.bilibili_auth import _fetch_wbi_keys
        img_key, sub_key = _fetch_wbi_keys()
        if img_key and sub_key:
            print(f'  WBI img_key: {img_key[:20]}...')
            print(f'  WBI sub_key: {sub_key[:20]}...')
            print(f'  WBI签名: ✅ 可获取')
        else:
            print(f'  WBI签名: ⚠️ 密钥获取失败（可能接口变更）')
    except Exception as e:
        print(f'  WBI签名: ❌ 异常: {e}')
    print()

    # ── 第4层：搜索API 实测 ──
    print('【第4层】搜索API 实测（连续3次）')
    print('-' * 70)
    from collectors.bilibili import safe_get
    success_count = 0
    code_412_count = 0
    for i in range(3):
        url = 'https://api.bilibili.com/x/web-interface/search/type'
        params = {'search_type': 'video', 'keyword': '鬼畜', 'order': 'pubdate', 'tid': 22}
        try:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=10)
            # 手动注入 Cookie，绕过 safe_get 的重试，看原始响应
            cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
            resp = requests.get(url, headers={**HEADERS, 'Cookie': cookie_str}, params=params, timeout=10)
            status_code = resp.status_code
            try:
                data = resp.json()
                api_code = data.get('code')
                result_count = len(data.get('data', {}).get('result', [])) if data.get('data') else 0
            except Exception:
                api_code = 'parse_error'
                result_count = 0

            if status_code == 412:
                code_412_count += 1
                print(f'  第{i+1}次: HTTP 412 ❌（被限流）')
            elif status_code == 200 and api_code == 0:
                success_count += 1
                print(f'  第{i+1}次: HTTP 200, code=0, 结果数={result_count} ✅')
            else:
                print(f'  第{i+1}次: HTTP {status_code}, code={api_code} ⚠️')
            time.sleep(1)
        except Exception as e:
            print(f'  第{i+1}次: 异常 {e} ❌')

    print()
    print(f'  搜索API 成功率: {success_count}/3')
    print(f'  412 限流次数:  {code_412_count}/3')
    if code_412_count >= 2:
        print('     → 诊断: buvid3 失效 或 需迁移到 /wbi/search/type（WBI签名版）')
        if 'buvid3' not in cookies:
            print('     → 根因: buvid3 缺失')
        else:
            print('     → 根因: buvid3 存在但仍被限流，需迁移 WBI 签名版搜索API')
    print()

    # ── 第5层：视频详情API 实测 ──
    print('【第5层】视频详情API 实测')
    print('-' * 70)
    test_bvid = 'BV1GJ411x7h7'  # 任意公开视频
    try:
        cookie_str = '; '.join(f'{k}={v}' for k, v in cookies.items())
        url = 'https://api.bilibili.com/x/web-interface/view'
        resp = requests.get(url, headers={**HEADERS, 'Cookie': cookie_str}, params={'bvid': test_bvid}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data.get('code') == 0:
                view = data['data'].get('stat', {}).get('view', 0)
                title = data['data'].get('title', '')[:30]
                print(f'  详情API: HTTP 200, code=0 ✅')
                print(f'  测试视频: {title}...')
                print(f'  播放量: {view}')
            else:
                print(f'  详情API: code={data.get("code")} ⚠️')
        elif resp.status_code == 412:
            print(f'  详情API: HTTP 412 ❌（详情接口也被限流，风控全面升级）')
        else:
            print(f'  详情API: HTTP {resp.status_code} ⚠️')
    except Exception as e:
        print(f'  详情API: 异常 {e} ❌')
    print()

    # ── 总结 ──
    print('=' * 70)
    print('诊断总结')
    print('=' * 70)
    print(f'  登录态:    {"✅" if user else "❌"}')
    print(f'  buvid3:    {"✅" if "buvid3" in cookies else "❌"}')
    print(f'  搜索API:   {"✅" if success_count >= 2 else "⚠️ 限流"} ({success_count}/3 成功)')
    print()
    if user and 'buvid3' in cookies and success_count >= 2:
        print('  整体状态: ✅ 正常')
    elif not user:
        print('  整体状态: ❌ 登录失效（最优先解决）')
    elif 'buvid3' not in cookies:
        print('  整体状态: ⚠️ 缺 buvid3（补上后搜索API 应恢复）')
    elif success_count < 2:
        print('  整体状态: ⚠️ 搜索API 被限流')
        print('  可能原因: buvid3 失效 / IP被风控 / 需迁移 WBI 签名版搜索API')
    print('=' * 70)


if __name__ == '__main__':
    run_diagnosis()
