"""基础设施配置常量：流水线的唯一来源。"""

import re

# ---------- Redis ----------
# 优先级队列（risk:/rand: ZSET + domain_metadata HASH）
REDIS_PORT = 6380
# 去重 / 缓存 Redis，按 db 划分语义：
#   db0: certstream 域名全局去重（typo_consumer 写入，model_update 采样负样本）
#   db2: phishintel 历史黑名单（init_local_blacklist 写入，phishintel_model_consumer 查询）
REDIS_DEDUP_PORT = 6381

# ---------- 截图服务 ----------
# 截图服务的基准端口（各实验端口见下方 ALL_EXPERIMENTS 注册表）
SCREENSHOT_BASIC_PORT = 6000

# ---------- Kafka ----------
KAFKA_PORT = 9092
KAFKA_BROKER = f"localhost:{KAFKA_PORT}"

# ---------- Certstream ----------
WS_URL = "ws://localhost:8080/full-stream"

# ---------- MongoDB ----------
MONGO_USERNAME = "admin"
MONGO_PASSWORD = "Woshiszc666"
MONGO_PORT = 27021
MONGO_URI = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@localhost:{MONGO_PORT}/"
MONGO_DB_NAME = "certstream_demo"

# ---------- 模型 / 数据路径 ----------
TYPO_MODEL_DIR = "../models/typo_model_10m_canine_no_subdomains"
DOMAIN_MAP_DIR = "../datasets/domain_map/domain_map.pkl"
WARMUP_DIR = "../datasets/warmup/warmup.pkl"
TRANCO_DIR = "../datasets/tranco/tranco_1m_subdomains.csv"

BAGGING_MODEL_NUM = 50


# ---------- 域名工具：托管平台后缀剥离 ----------
# 原 model_consumer.py 与 model_update.py 各有一份 HOSTING_PLATFORMS + transform_domain，
# 语义略有差别（model_consumer 保序保对齐、model_update 去重），这里同时提供两个版本。

HOSTING_PLATFORMS = {
    "4everland.app",
    "amazonaws.com",
    "amplifyapp.com",
    "azurewebsites.net",
    "backblazeb2.com",
    "biz.id",
    "cloudaccess.host",
    "cloudfront.net",
    "cloudwaysapps.com",
    "contabostorage.com",
    "daftpage.com",
    "digitaloceanspaces.com",
    "firebaseapp.com",
    "format.com",
    "framer.app",
    "framer.website",
    "github.io",
    "godaddysites.com",
    "hostingersite.com",
    "kinsta.cloud",
    "linodeobjects.com",
    "mmm.page",
    "my.id",
    "mystrikingly.com",
    "netlify.app",
    "on-fleek.app",
    "ondigitalocean.app",
    "pages.dev",
    "plesk.page",
    "r2.dev",
    "replit.app",
    "replit.dev",
    "rollout.site",
    "squarespace.com",
    "surge.sh",
    "trycloudflare.com",
    "typedream.app",
    "univer.se",
    "vercel.app",
    "web.app",
    "webflow.io",
    "weebly.com",
    "weeblysite.com",
    "wixsite.com",
    "wixstudio.com",
    "wixstudio.io",
    "workers.dev",
    "wpenginepowered.com",
    "zeabur.app",
}


def _strip_hosting_platform(domain):
    """单个域名剥离托管平台后缀，如 xxx.github.io -> xxx"""
    for platform in HOSTING_PLATFORMS:
        if domain.endswith("." + platform):
            domain = domain[: -(len(platform) + 1)]
            if domain.endswith("."):
                domain = domain[:-1]
            break
    return domain


def transform_domains(domains):
    """保序版本（原 model_consumer.py）：输出与输入一一对齐，不去重。"""
    return [_strip_hosting_platform(d) for d in domains]


def transform_domains_unique(domains):
    """去重版本（原 model_update.py）：返回 list，顺序不保证。"""
    return list({_strip_hosting_platform(d) for d in domains})


# ---------- 实验名注册表：所有实验的唯一来源 ----------
# 历史上截图端口按 SCREENSHOT_BASIC_PORT + EXP_NAMES.index(exp_name) 计算，
# 增删实验会导致端口漂移。这里改为每个实验显式固定端口，与当前线上取值保持一致。
#
# 端口分配说明：
#   6000-6004 当前启用实验
#   6010 起分配给当前未启用的 ablation/baseline 实验（仅需不与启用实验冲突）
#   8000 保持与 phishintel 旧 SCREENSHOT_BASIC_PORT=8000 一致
ALL_EXPERIMENTS = {
    "ablation_charcnn_phishintention_vlm_r90": {"screenshot_port": 6002},  # 默认 r90
}

# 当前启用的实验（argparse choices 用这个；开关实验只改这里）
EXP_NAMES = [
    "ablation_charcnn_phishintention_vlm_r90",
]


def screenshot_port(exp_name):
    """按注册表返回实验对应的截图服务端口。"""
    return ALL_EXPERIMENTS[exp_name]["screenshot_port"]


def parse_risk_ratio(exp_name, default=1.0):
    """从实验名后缀 _r<n> 解析风险优先比例，无后缀返回 default。

    后缀为百分数整数，如 _r90 -> 0.9。
    """
    m = re.search(r"_r(\d+)$", exp_name)
    return int(m.group(1)) / 100.0 if m else default


def base_exp_name(exp_name):
    """剥离比例后缀，用于定位模型目录等共享资源"""
    return re.sub(r"_r\d+$", "", exp_name)
