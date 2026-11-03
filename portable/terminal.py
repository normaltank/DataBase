"""Unicode hidden terminal input with no echoing fallback."""
import getpass
import warnings


def hidden_input(prompt):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            return getpass.getpass(prompt)
    except getpass.GetPassWarning:
        raise ValueError('当前窗口无法安全隐藏输入，请双击本包BAT在独立命令窗口重试；未读取口令或密钥。') from None
