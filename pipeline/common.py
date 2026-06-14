EXP_NAMES = [
    "ablation_charcnn_phishintention_vlm"
]


REDIS_PORT = 6380
SCREENSHOT_BASIC_PORT = 8000
KAFKA_PORT = 9092
KAFKA_BROKER = f'localhost:{KAFKA_PORT}'
# Certstream WebSocket URL
WS_URL = 'ws://localhost:8080/full-stream'
TYPO_MODEL_DIR = '../models/trained/typo_model'
DOMAIN_MAP_DIR = '../datasets/phishpedia/domain_map.pkl'
BAGGING_MODEL_NUM = 50