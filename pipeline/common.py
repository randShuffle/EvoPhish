"""Infrastructure configuration constants: single source of truth for the pipeline."""

import re

# ---------- Redis ----------
# Priority queues (risk:/rand: ZSET + domain_metadata HASH)
REDIS_PORT = 6380
# Dedup / cache Redis, semantics split by db:
#   db0: global certstream domain dedup (written by typo_consumer, negative sampling in model_update)
#   db2: phishintel historical blacklist (written by init_local_blacklist, queried by phishintel_model_consumer)
REDIS_DEDUP_PORT = 6381

# ---------- Screenshot service ----------
# Base port of the screenshot service (per-experiment ports are in the ALL_EXPERIMENTS registry below)
SCREENSHOT_BASIC_PORT = 6000

# ---------- Kafka ----------
KAFKA_PORT = 9092
KAFKA_BROKER = f"localhost:{KAFKA_PORT}"

# ---------- Certstream ----------
WS_URL = "ws://localhost:8080/full-stream"

# ---------- MongoDB ----------
MONGO_USERNAME = "yourusername"
MONGO_PASSWORD = "yourpassword"
MONGO_PORT = 27021
MONGO_URI = f"mongodb://{MONGO_USERNAME}:{MONGO_PASSWORD}@localhost:{MONGO_PORT}/"
MONGO_DB_NAME = "certstream_demo"

# ---------- Model / data paths ----------
TYPO_MODEL_DIR = "../models/typo_model_10m_canine_no_subdomains"
DOMAIN_MAP_DIR = "../datasets/domain_map/domain_map.pkl"
WARMUP_DIR = "../datasets/warmup/warmup.pkl"
TRANCO_DIR = "../datasets/tranco/tranco_1m_subdomains.csv"

BAGGING_MODEL_NUM = 50


# ---------- Domain utils: strip hosting-platform suffixes ----------
# model_consumer.py and model_update.py each used to carry their own
# HOSTING_PLATFORMS + transform_domain, with slightly different semantics
# (model_consumer preserves order and alignment, model_update dedups).
# Both variants are provided here.

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
    """Strip the hosting-platform suffix from a single domain, e.g. xxx.github.io -> xxx"""
    for platform in HOSTING_PLATFORMS:
        if domain.endswith("." + platform):
            domain = domain[: -(len(platform) + 1)]
            if domain.endswith("."):
                domain = domain[:-1]
            break
    return domain


def transform_domains(domains):
    """Order-preserving variant (former model_consumer.py): output aligns one-to-one with input, no dedup."""
    return [_strip_hosting_platform(d) for d in domains]


def transform_domains_unique(domains):
    """Dedup variant (former model_update.py): returns a list, order not guaranteed."""
    return list({_strip_hosting_platform(d) for d in domains})


# ---------- Experiment registry: single source of truth for all experiments ----------
# Historically the screenshot port was computed as SCREENSHOT_BASIC_PORT + EXP_NAMES.index(exp_name),
# so adding/removing experiments caused port drift. Now each experiment gets an explicit
# fixed port, matching the values currently used in production.
#
# Port allocation:
#   6000-6004 currently enabled experiments
#   6010+    ablation/baseline experiments not currently enabled (only need to avoid conflicts)
#   8000     kept consistent with phishintel's legacy SCREENSHOT_BASIC_PORT=8000
ALL_EXPERIMENTS = {
    "ablation_charcnn_phishintention_vlm_r90": {"screenshot_port": 6002},  # default r90
}

# Currently enabled experiments (used as argparse choices; toggle experiments by editing only this list)
EXP_NAMES = [
    "ablation_charcnn_phishintention_vlm_r90",
]


def screenshot_port(exp_name):
    """Return the screenshot service port for an experiment from the registry."""
    return ALL_EXPERIMENTS[exp_name]["screenshot_port"]


def parse_risk_ratio(exp_name, default=1.0):
    """Parse the risk-priority ratio from the _r<n> suffix of the experiment name; return default if absent.

    The suffix is an integer percentage, e.g. _r90 -> 0.9.
    """
    m = re.search(r"_r(\d+)$", exp_name)
    return int(m.group(1)) / 100.0 if m else default


def base_exp_name(exp_name):
    """Strip the ratio suffix; used to locate shared resources such as model directories"""
    return re.sub(r"_r\d+$", "", exp_name)
