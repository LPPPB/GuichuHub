"""统一日志配置 — stdout 输出，Docker 友好

V1 完全无 logging，异常全靠 try/except 返 JSON。
V2 引入标准 logging + 字典配置，输出到 stdout（容器友好）。
"""

import logging
import logging.config

LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'default': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'default',
            'stream': 'ext://sys.stdout',
        },
    },
    'root': {
        'level': 'INFO',
        'handlers': ['console'],
    },
}


def setup_logging():
    """进程启动时调用一次，配置全局日志。"""
    logging.config.dictConfig(LOGGING_CONFIG)


def get_logger(name):
    """各模块获取 logger 的统一入口。"""
    return logging.getLogger(name)
