"""Terminal wizard for opt-in paid maintenance. Never calls a provider."""
import json
from decimal import Decimal

from .ai_settings import default_pricing, validate
from .worker import set_policy
from .terminal import hidden_input


def prompt_configuration(settings, data, *, read=input, secret_reader=None):
    secret_reader = secret_reader or hidden_input
    print('本机 AI 设置（DeepSeek）：默认暂停。配置不会发送模型请求。', flush=True)
    print('密钥隐藏输入，不显示字符或星号；按回车继续，Ctrl+C取消。', flush=True)
    print('启用后自动维护新旧公共外部资料与档案，有据结果直接保存；采集仍限已启用来源。', flush=True)
    try:
        key = secret_reader('DeepSeek API密钥：')
        model = read('模型 [deepseek-flash]：').strip() or 'deepseek-flash'
        model_version = read('模型版本/核对日期（必填，例如2026-11-03）：').strip()
        price = default_pricing()
        print('价格为每百万 tokens 的人民币；默认取2026-11-03已核查峰值（命中0.04／未命中2／输出8）。', flush=True)
        print('核对 https://api-docs.deepseek.com/zh-cn/quick_start/pricing/ ；模型及价格会变动。', flush=True)
        if model != 'deepseek-flash':
            price = dict.fromkeys(price, '')
            price['currency'] = 'CNY'
        price['model'] = model
        for field, label in [('version', '价格版本'), ('input_cache_hit_per_million', '输入命中价'),
                             ('input_cache_miss_per_million', '输入未命中价'), ('output_per_million', '输出价')]:
            answer = read(f"{label} [{price[field]}]：").strip()
            price[field] = answer or price[field]
        cap = read('CNY月预算（UTC自然月，0表示暂停；最多六位小数）：').strip()
        validate({'version': 1, 'key': key, 'model': model, 'model_version': model_version,
                  'pricing': price, 'cap': cap, 'enabled': False})
        print(f'确认：模型 {model}；版本 {model_version}；月预算 CNY {cap}；保存后仍暂停。', flush=True)
        print('本月费用与未结算预留继续累计，未知费用保持阻塞；设置不会充值。', flush=True)
        if read('输入 SAVE 保存；其他输入取消：').strip() != 'SAVE':
            print('已取消，原设置保留。', flush=True)
            return False
        settings.configure(key, cap=cap, model=model, model_version=model_version, pricing=price)
        set_policy(data, settings, paused=True, configure=True)
        print('本机受保护设置保存成功，AI仍暂停。运行 ai-enable.bat 明确启用，再用 start.bat 或 lan-start.bat。', flush=True)
        return True
    except (KeyboardInterrupt, EOFError):
        print('\n已取消，原设置保留。', flush=True)
        return False


def enable(settings, data, *, read=input):
    value = settings.status()
    if not value['configured']:
        raise ValueError(value['reason'])
    from contextlib import closing
    from pathlib import Path
    from platform_app import store
    with closing(store.connect(Path(data) / 'platform.sqlite3')) as db:
        policy_row = db.execute("SELECT value FROM settings WHERE key='ai_policy'").fetchone()
    policy = json.loads(policy_row[0]) if policy_row else {}
    if policy.get('currency') != 'CNY' or Decimal(policy.get('cap', '0')) <= 0:
        raise ValueError('数据库当前预算无效或为0；请先设置正数CNY月预算。本机保存预算也为0时，须重新运行 ai-configure.bat。')
    print(f"将启用本包采集、自动中文与AI自主维护，模型 {value['model']}，当前CNY月预算 {policy['cap']}。", flush=True)
    print('采集仅限已启用来源；AI自动维护新旧公共外部资料与档案，所有AI调用使用统一预算网关。', flush=True)
    try:
        if read('输入 ENABLE 明确允许联网及按预算付费；其他输入取消：').strip() != 'ENABLE':
            print('已取消启用。', flush=True)
            return False
    except (KeyboardInterrupt, EOFError):
        print('\n已取消启用。', flush=True)
        return False
    settings.set_enabled(True)
    set_policy(data, settings, paused=False)
    print('已启用。请用 start.bat 或 lan-start.bat 启动；stop.bat 会等待在途任务结算后停止。', flush=True)
    return True


def disable(settings, data):
    # Pause DB first, so new gateway reservations are blocked immediately.
    set_policy(data, settings, paused=True)
    if settings.load():
        settings.set_enabled(False)
    print('AI已暂停；后台完成当前有界任务与费用结算后停止，不再派发后续任务。', flush=True)
