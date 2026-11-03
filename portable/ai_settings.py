"""Opt-in, per-Windows-user/per-extraction settings outside all share/backup roots."""
import ctypes
from ctypes import wintypes
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re


def default_pricing():
    # Frozen conservative peak snapshot, verified by controller 2026-11-03.
    return {'version': 'deepseek-official-2026-11-03-peak-cny', 'model': 'deepseek-flash',
            'currency': 'CNY', 'input_cache_hit_per_million': '0.04',
            'input_cache_miss_per_million': '2', 'output_per_million': '8'}


def user_storage():
    if os.name != 'nt':
        raise ValueError('便携 AI 凭据仅支持 Windows 当前用户保护存储。')
    buffer = ctypes.create_unicode_buffer(32768)
    if ctypes.windll.shell32.SHGetFolderPathW(None, 0x001c, None, 0, buffer) != 0:
        raise ValueError('无法取得当前用户的本机配置目录。')
    return Path(buffer.value) / 'ResearchPreview'


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(raw, entropy, decrypt=False):
    """DPAPI CurrentUser, UI forbidden; deliberately no plaintext fallback."""
    if os.name != 'nt':
        raise ValueError('Windows 用户保护存储不可用。')
    source_buffer = ctypes.create_string_buffer(raw)
    entropy_buffer = ctypes.create_string_buffer(entropy)
    source = Blob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    extra = Blob(len(entropy), ctypes.cast(entropy_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypto = ctypes.windll.crypt32
    function = crypto.CryptUnprotectData if decrypt else crypto.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, ctypes.byref(extra), None, None, 1, ctypes.byref(output)):
        raise ValueError('无法读取或保存本机受保护的 AI 设置；请在当前用户下重新配置。')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(output.data)


def validate(value):
    try:
        if set(value) != {'key', 'model', 'model_version', 'pricing', 'cap', 'enabled', 'version'} or value['version'] != 1:
            raise ValueError()
        key = value['key']
        if not isinstance(key, str) or not re.fullmatch(r'[!-~]{12,512}', key):
            raise ValueError()
        model = value['model']
        if not isinstance(model, str) or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,100}', model):
            raise ValueError()
        version = value['model_version']
        if not isinstance(version, str) or not 1 <= len(version) <= 100 or any(ord(c) < 32 for c in version):
            raise ValueError()
        pricing = value['pricing']
        fields = {'version', 'model', 'currency', 'input_cache_hit_per_million', 'input_cache_miss_per_million', 'output_per_million'}
        if (not isinstance(pricing, dict) or set(pricing) != fields or pricing['currency'] != 'CNY'
                or pricing['model'] != model or not all(isinstance(v, str) and 1 <= len(v) <= 100 for v in pricing.values())):
            raise ValueError()
        rates = [Decimal(pricing[k]) for k in fields - {'version', 'model', 'currency'}]
        if any(not r.is_finite() or r < 0 for r in rates) or max(rates) <= 0:
            raise ValueError()
        if not isinstance(value['cap'], str):
            raise ValueError()
        cap = Decimal(value['cap'])
        if not cap.is_finite() or not 0 <= cap <= Decimal('1000000000') or cap.as_tuple().exponent < -6:
            raise ValueError()
        if type(value['enabled']) is not bool or (value['enabled'] and cap <= 0):
            raise ValueError()
        if key in json.dumps({k: v for k, v in value.items() if k != 'key'}, ensure_ascii=False):
            raise ValueError()
    except (KeyError, TypeError, ValueError, InvalidOperation, AttributeError):
        raise ValueError('AI 设置无效：核对密钥格式、模型及版本、CNY价格版本和非负预算（最多六位小数）。') from None
    return value


class LocalAISettings:
    def __init__(self, root, *, storage_root=None):
        self.identity = hashlib.sha256(str(Path(root).resolve()).casefold().encode('utf-8')).hexdigest()
        self.path = (Path(storage_root) if storage_root is not None else user_storage()) / self.identity / 'ai-settings.dpapi'

    def load(self):
        try:
            return validate(json.loads(protect(self.path.read_bytes(), self.identity.encode(), decrypt=True)))
        except (OSError, ValueError, TypeError, UnicodeError):
            return None

    def save(self, value):
        validate(value)
        encrypted = protect(json.dumps(value, ensure_ascii=False).encode('utf-8'), self.identity.encode())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(encrypted)
        temporary.replace(self.path)

    def configure(self, key, *, cap, model, model_version, pricing):
        self.save({'version': 1, 'key': key, 'model': model, 'model_version': model_version,
                   'pricing': pricing, 'cap': cap, 'enabled': False})

    def set_enabled(self, enabled):
        value = self.load()
        if value is None:
            raise ValueError('尚未配置有效本机 AI 设置，请先运行 ai-configure.bat。')
        if enabled and Decimal(value['cap']) <= 0:
            raise ValueError('预算为0，AI保持暂停；请先配置正数CNY月预算。')
        value['enabled'] = bool(enabled)
        self.save(value)

    def runtime_environment(self):
        value = self.load()
        if not value or not value['enabled']:
            return {}
        return {'DEEPSEEK_API_KEY': value['key'], 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com',
                'DEEPSEEK_MODEL': value['model'], 'DEEPSEEK_MODEL_VERSION': value['model_version'],
                'DEEPSEEK_CONFIG_VERSION': 'portable-opt-in-v1',
                'DEEPSEEK_PRICING_JSON': json.dumps(value['pricing'])}

    def status(self):
        value = self.load()
        if not value:
            return {'configured': False, 'enabled': False, 'reason': '未配置或本机设置不可读取，请运行 ai-configure.bat。'}
        return {k: value[k] for k in ('model', 'model_version', 'pricing', 'cap', 'enabled')} | {
            'configured': True, 'currency': 'CNY',
            'reason': '已明确启用本包后台。' if value['enabled'] else '本机 AI 已暂停；运行 ai-enable.bat 后再启动。'}
