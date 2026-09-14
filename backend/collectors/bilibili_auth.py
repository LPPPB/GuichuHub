import requests
import json
import os
import time
import io
import base64
import hashlib
import urllib.parse
import qrcode
from runtime_paths import RuntimePaths

RUNTIME_PATHS = RuntimePaths.from_environment(os.environ)
COOKIE_FILE = str(RUNTIME_PATHS.cookie_file)
COOKIE_WRITES_ENABLED = os.environ.get('KICHU_COOKIE_WRITES_ENABLED', '1').strip().lower() not in {
    '0', 'false', 'no', 'off'
}

def get_headers(cookie_str=None):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com/',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Origin': 'https://www.bilibili.com',
    }
    if cookie_str:
        headers['Cookie'] = cookie_str
    return headers

def cookie_dict_to_str(cookie_dict):
    if not cookie_dict:
        return ''
    parts = []
    for k, v in cookie_dict.items():
        parts.append(f'{k}={v}')
    return '; '.join(parts)

def cookie_str_to_dict(cookie_str):
    result = {}
    if not cookie_str:
        return result
    for part in cookie_str.split(';'):
        part = part.strip()
        if '=' in part:
            k, v = part.split('=', 1)
            result[k.strip()] = v.strip()
    return result

def extract_cookies_from_response(resp):
    cookies = {}
    for cookie in resp.cookies:
        cookies[cookie.name] = cookie.value
    return cookies

def generate_qrcode():
    url = 'https://passport.bilibili.com/x/passport-login/web/qrcode/generate'
    resp = requests.get(url, headers=get_headers(), timeout=10)
    data = resp.json()
    if data.get('code') == 0:
        qr_url = data['data']['url']
        qr_key = data['data']['qrcode_key']

        qr_img = qrcode.make(qr_url)
        buf = io.BytesIO()
        try:
            # Pillow 后端：save 接受 format 参数
            qr_img.save(buf, format='PNG')
        except TypeError:
            # pypng 后端：save 不接受 format 参数，默认输出 PNG
            qr_img.save(buf)
        qr_base64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        qr_data_url = f'data:image/png;base64,{qr_base64}'

        return {
            'success': True,
            'url': qr_url,
            'qrcode_key': qr_key,
            'qrcode_image': qr_data_url,
        }
    return {'success': False, 'message': data.get('message', '生成二维码失败')}

def check_login_status(qrcode_key, save=True):
    """扫码结果轮询。

    save=True  → 凭证写入 bilibili_cookie.json（采集账号登录）
    save=False → 不落盘，凭证只随返回值交给调用方（访客身份登录，
                 由 app 层存入会话表，绝不写采集 Cookie）
    """
    url = 'https://passport.bilibili.com/x/passport-login/web/qrcode/poll'
    params = {'qrcode_key': qrcode_key}
    resp = requests.get(url, params=params, headers=get_headers(), timeout=10)
    data = resp.json()

    if data.get('code') != 0:
        return {
            'success': False,
            'status': 'error',
            'message': data.get('message', '请求失败')
        }

    inner_data = data.get('data', {})
    inner_code = inner_data.get('code', -1)

    if inner_code == 0:
        resp_cookies = extract_cookies_from_response(resp)
        all_cookies = dict(resp_cookies)

        raw_set_cookie = resp.headers.get('set-cookie', '')
        if raw_set_cookie:
            import http.cookies
            cookie_jar = http.cookies.SimpleCookie()
            try:
                cookie_jar.load(raw_set_cookie)
                for key, morsel in cookie_jar.items():
                    all_cookies[key] = morsel.value
            except:
                pass

        if not all_cookies.get('SESSDATA'):
            url_field = inner_data.get('url', '') or ''
            if url_field:
                import urllib.parse
                parsed = urllib.parse.urlparse(url_field)

                if parsed.query:
                    query_params = urllib.parse.parse_qs(parsed.query)
                    for k, v_list in query_params.items():
                        if k.upper() in ['SESSDATA', 'BILI_JCT', 'DEDEUSERID', 'DEDEUSERID__CKMD5', 'SID']:
                            all_cookies[k] = v_list[0]

                if parsed.fragment:
                    hash_params = urllib.parse.parse_qs(parsed.fragment)
                    for k, v_list in hash_params.items():
                        if k.upper() in ['SESSDATA', 'BILI_JCT', 'DEDEUSERID', 'DEDEUSERID__CKMD5', 'SID']:
                            all_cookies[k] = v_list[0]

        key_mapping = {
            'SESSDATA': 'SESSDATA', 'sessdata': 'SESSDATA', 'SessData': 'SESSDATA',
            'bili_jct': 'bili_jct', 'BILI_JCT': 'bili_jct', 'BiliJct': 'bili_jct', 'csrf': 'bili_jct',
            'DedeUserID': 'DedeUserID', 'DEDEUSERID': 'DedeUserID', 'dedeuserid': 'DedeUserID',
            'DedeUserID__ckMd5': 'DedeUserID__ckMd5',
            'sid': 'sid', 'SID': 'sid',
        }
        normalized = {}
        for k, v in all_cookies.items():
            if k in key_mapping:
                normalized[key_mapping[k]] = v
            else:
                normalized[k] = v

        if not normalized.get('SESSDATA'):
            return {
                'success': False,
                'status': 'error',
                'message': '登录失败，未能获取到有效凭证'
            }

        if save:
            save_cookie(normalized)
        mid = normalized.get('DedeUserID', '')
        return {
            'success': True,
            'status': 'success',
            'message': '登录成功',
            'user_mid': mid,
            'cookies': {k: v for k, v in normalized.items() if k in ['SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5']},
        }
    elif inner_code == 86090:
        return {'success': False, 'status': 'scanned', 'message': '已扫码，请在手机上确认登录'}
    elif inner_code == 86101:
        return {'success': False, 'status': 'waiting', 'message': '等待扫码'}
    elif inner_code == 86038:
        return {'success': False, 'status': 'expired', 'message': '二维码已过期，请刷新'}
    else:
        return {'success': False, 'status': 'unknown', 'message': inner_data.get('message', f'未知状态: {inner_code}')}

def parse_set_cookie(set_cookie_header):
    cookies = {}
    if not set_cookie_header:
        return cookies
    parts = set_cookie_header.split(',')
    for part in parts:
        part = part.strip()
        if '=' in part and not any(x in part.lower() for x in ['expires', 'path', 'domain', 'httponly', 'secure', 'samesite']):
            kv = part.split(';')[0].strip()
            if '=' in kv:
                k, v = kv.split('=', 1)
                k = k.strip()
                if k in ['SESSDATA', 'bili_jct', 'DedeUserID', 'DedeUserID__ckMd5', 'sid']:
                    cookies[k] = v.strip()
    return cookies

def save_cookie(cookie_dict):
    os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
    data = {
        'cookies': cookie_dict,
        'saved_at': int(time.time()),
    }
    with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _ensure_buvid3(cookies):
    """确保 Cookie 含 buvid3（搜索API文档明确要求）。

    buvid3 由 B站首页首次访问时下发，登录接口不下发。
    缺失时主动访问首页获取并缓存。

    安全设计：
    1. 防并发覆盖：save_cookie 前重新 load_cookie 合并，不丢失期间写入的登录态
       （抓取线程读旧Cookie → 用户登录写新Cookie → 抓取线程覆盖旧Cookie+buvid3 会导致登录态丢失）
    2. 防异常冒泡：save_cookie 失败时仅内存补充，不阻断主流程
    """
    if cookies.get('buvid3') or not COOKIE_WRITES_ENABLED:
        return cookies

    try:
        resp = requests.get('https://www.bilibili.com/', headers=get_headers(), timeout=10)
        buvid3 = next((c.value for c in resp.cookies if c.name == 'buvid3'), None)
        if not buvid3:
            return cookies  # 没拿到，不修改

        # 防并发覆盖：重新读最新Cookie，合并 buvid3 后再保存
        latest = load_cookie() or cookies
        latest['buvid3'] = buvid3
        try:
            save_cookie(latest)
        except Exception as e:
            print(f'[bili-auth] 持久化 buvid3 失败（仅内存补充）: {e}')

        # 返回给当前调用方（内存补充立即生效）
        cookies['buvid3'] = buvid3
        print(f'[bili-auth] 已补充 buvid3 指纹: {buvid3[:20]}...')
    except Exception as e:
        print(f'[bili-auth] 获取 buvid3 失败: {e}')
    return cookies

def load_cookie():
    if not os.path.exists(COOKIE_FILE):
        return None
    try:
        with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cookies = data.get('cookies', {})
        if not cookies or not cookies.get('SESSDATA'):
            return None
        return cookies
    except:
        return None

def get_cookie_str():
    cookies = load_cookie()
    if not cookies:
        return None
    cookies = _ensure_buvid3(cookies)  # 补充 buvid3（搜索API文档要求，缺失时自动获取）
    return cookie_dict_to_str(cookies)

def is_logged_in():
    cookies = load_cookie()
    if not cookies or not cookies.get('SESSDATA'):
        return False
    user_info = get_user_info()
    return user_info is not None

def get_user_info_with_cookie(cookie_str):
    """用给定凭证查B站账号信息（身份登录成功后的资料补充，不依赖采集 Cookie）"""
    if not cookie_str:
        return None
    try:
        url = 'https://api.bilibili.com/x/web-interface/nav'
        resp = requests.get(url, headers=get_headers(cookie_str), timeout=10)
        data = resp.json()
        if data.get('code') == 0:
            nav = data['data']
            return {
                'mid': nav.get('mid'),
                'name': nav.get('uname'),
                'face': nav.get('face'),
                'level': nav.get('level_info', {}).get('current_level', 0),
                'vip_status': nav.get('vipStatus', 0),
                'vip_type': nav.get('vipType', 0),
                'is_login': nav.get('isLogin', False),
            }
        return None
    except Exception as e:
        print(f'获取用户信息失败: {e}')
        return None

def get_user_info():
    """采集 Cookie 对应的B站账号信息（原语义保留）"""
    return get_user_info_with_cookie(get_cookie_str())

def logout():
    if os.path.exists(COOKIE_FILE):
        os.remove(COOKIE_FILE)
    return True

# ==================== WBI 签名 ====================
# B站 WBI 签名反爬机制：部分 /wbi/ 接口要求请求参数带 wts(时间戳) + w_rid(签名)
# 算法：从 /x/web-interface/nav 获取 img_key + sub_key → 混排表生成 mixin_key
#       → 参数按字母序拼接 + mixin_key → md5 得 w_rid
# 参考：SocialSisterYang/bilibili-WBI-signature、biliscope/biliapi.js

# WBI 签名混排表（固定不变，B站约定）
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# WBI 密钥缓存（1 小时有效期，避免每次请求都打 nav 接口）
_wbi_keys_cache = {'img_key': None, 'sub_key': None, 'updated_at': 0}


def _fetch_wbi_keys():
    """从 B站 nav 接口获取 WBI 密钥（img_key + sub_key）"""
    cookie_str = get_cookie_str()
    if not cookie_str:
        return None, None
    try:
        url = 'https://api.bilibili.com/x/web-interface/nav'
        resp = requests.get(url, headers=get_headers(cookie_str), timeout=10)
        data = resp.json()
        if data.get('code') == 0:
            wbi_img = data['data'].get('wbi_img', {})
            img_url = wbi_img.get('img_url', '')
            sub_url = wbi_img.get('sub_url', '')
            img_key = img_url.rsplit('/', 1)[-1].split('.')[0] if img_url else ''
            sub_key = sub_url.rsplit('/', 1)[-1].split('.')[0] if sub_url else ''
            if img_key and sub_key:
                return img_key, sub_key
    except Exception as e:
        print(f'获取WBI密钥失败: {e}')
    return None, None


def _get_wbi_keys():
    """获取 WBI 密钥（带1小时缓存）"""
    global _wbi_keys_cache
    now = int(time.time())
    if _wbi_keys_cache['img_key'] and (now - _wbi_keys_cache['updated_at']) < 3600:
        return _wbi_keys_cache['img_key'], _wbi_keys_cache['sub_key']

    img_key, sub_key = _fetch_wbi_keys()
    if img_key and sub_key:
        _wbi_keys_cache = {'img_key': img_key, 'sub_key': sub_key, 'updated_at': now}
    return img_key, sub_key


def _get_mixin_key(img_key, sub_key):
    """根据 img_key + sub_key 生成 mixin key（按混排表取前32位）"""
    raw = img_key + sub_key
    return ''.join(raw[i] for i in _MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def _sign_wbi_params(params):
    """对请求参数进行 WBI 签名，添加 w_rid 和 wts

    流程：加 wts → 按字母序拼接 query → 末尾接 mixin_key → md5 得 w_rid
    密钥不可用时返回原 params（跳过签名，调用方自行承担风控风险）
    """
    img_key, sub_key = _get_wbi_keys()
    if not img_key or not sub_key:
        print('⚠ WBI密钥不可用，跳过签名')
        return params

    mixin_key = _get_mixin_key(img_key, sub_key)
    params = dict(params)
    params['wts'] = int(time.time())

    # 按 key 字母序排列
    sorted_params = sorted(params.items(), key=lambda x: x[0])
    query_string = urllib.parse.urlencode(sorted_params)

    params['w_rid'] = hashlib.md5((query_string + mixin_key).encode('utf-8')).hexdigest()
    return params


def safe_get_with_wbi(url, params=None, max_retries=2):
    """带 WBI 签名的安全 GET 请求（用于 /wbi/ 等需签名的 B站接口）

    - 无 Cookie → 返回 None
    - code=-101 → Cookie 过期，返回 error dict
    - 其他非0 code → 重试（最多 max_retries 次）
    - 网络异常 → 重试，末次失败返回 None
    """
    cookie_str = get_cookie_str()
    if not cookie_str:
        print('⚠ safe_get_with_wbi: 无Cookie')
        return None

    params = params or {}
    signed_params = _sign_wbi_params(params)

    for i in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=get_headers(cookie_str), params=signed_params, timeout=15)
            data = resp.json()
            if data.get('code') == 0:
                return data
            elif data.get('code') == -101:
                return {'error': 'cookie_expired', 'message': 'Cookie已过期，请重新登录'}
            else:
                print(f'  API返回错误 code={data.get("code")}: {data.get("message", "")}')
            time.sleep(0.5)
        except Exception as e:
            if i < max_retries:
                time.sleep(1)
            else:
                print(f'  WBI请求失败 {url}: {e}')
    return None

# ==================== 以上为 WBI 签名 ====================
