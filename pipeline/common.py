# EXP_NAMES = [
#     "baseline_phishpedia",
#     "baseline_phishintention",
#     "ablation_charcnn_phishintention",
#     "ablation_fasttext_phishintention",
#     "ablation_tfidf_phishintention",
#     "ablation_charcnn_phishpedia",
#     "ablation_fasttext_phishpedia",
#     "ablation_tfidf_phishpedia",
# ]


EXP_NAMES = [
    "baseline_phishintention",
    "field_charcnn_phishintention",
    "field_no_priority_charcnn_phishintention",
    "field_no_priority_no_retrain_charcnn_phishintention",
]


REDIS_PORT = 6380
SCREENSHOT_BASIC_PORT = 8000
KAFKA_PORT = 9092
KAFKA_BROKER = f'localhost:{KAFKA_PORT}'
# Certstream WebSocket URL
WS_URL = 'ws://localhost:8080/full-stream'
TYPO_MODEL_DIR = '../models/trained/typo_model_10m_canine_no_subdomains'
DOMAIN_MAP_DIR = '../datasets/phishpedia/domain_map.pkl'
BAGGING_MODEL_NUM = 50