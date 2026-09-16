# EvoPhish

EvoPhish is a real-time phishing detection system. It consumes newly registered domains
from the Certificate Transparency log stream (via CertStream), filters them with a fast
domain-level classifier (CharCNN typo/similarity models), takes screenshots of suspicious
sites, and runs visual brand-intention analysis (PhishIntention + a VLM reranker) to
confirm phishing pages.

## Architecture

```
CertStream ──> Kafka ──> typo_consumer ──> Kafka ──> model_consumer ──> Redis queues
 (domains)      (raw)     (embeddings +    (enriched)   (CharCNN          (risk / rand
                          typo flag)                    scoring)           priority)
                                                                       │
                          PhishIntention service <──── screenshot <────┘
                          (visual analysis, :5001)     (playwright, :6000+)
                                │
                                v
                          VLM rerank service (:7077) ──> vLLM backend (Qwen3-VL, :7000)
                                │
                                v
                            MongoDB (results, :27021)
```

Components:

1. **Core pipeline** (`pipeline/`) — data stream ingestion, domain classification,
   scheduling, periodic retraining ("fast thinker").
2. **RBPD** (`rbpd/`) — PhishIntention visual analysis service plus the VLM patch
   service ("slow thinker").

## Directory layout

```
├── pipeline/                       # Core detection pipeline (conda env: Reptile)
│   ├── alphabet.json               # Character set for CharCNN domain encoding
│   ├── certstream_producer.py      # CertStream -> Kafka producer
│   ├── common.py                   # Shared constants (ports, URIs, experiment registry)
│   ├── typo_consumer.py            # Domain typo detection + embedding extraction
│   ├── model_consumer.py           # Fast thinker, domain classifier consumer (CharCNN / FastText / TF-IDF)
│   ├── model_inference.py          # Model inference implementations
│   ├── model_update.py             # Periodic model retraining
│   ├── redis_consumer.py           # Priority-queue consumer, dispatches screenshot jobs
│   ├── redis.lua                   # Redis Lua script for queue ops
│   ├── screenshot.py               # Screenshot service (Playwright, FastAPI)
│   ├── view_results.py             # Query/summarize results from MongoDB
│   ├── openphish.sh                # Fetch OpenPhish public feed snapshots
│   └── ablation_charcnn_phishintention_vlm_r90.sh   # Retrain/restart loop (every 2 h)
├── start_all.sh                    # One-click startup: downloads, envs, infra, all services in tmux
├── rbpd/
│   ├── PhishIntention/             # PhishIntention service (conda env: phishintention)
│   │   ├── app.py                  # HTTP API entry point (:5001)
│   │   ├── phishintention.py       # Core PhishIntention logic
│   │   ├── configs.py              # Model/config loader
│   │   ├── configs/                # YAML configs and model configs
│   │   ├── modules/                # Layout detector, CRP classifier/locator, logo matching
│   │   ├── ocr_lib/                # OCR library
│   │   └── utils/                  # Utilities
│   └── vlm/                        # VLM services (conda env: video)
│       ├── start_vllm.sh           # Start the vLLM backend (Qwen3-VL-32B, :7000)
│       └── stage3_rerank_service.py  # Logo rerank HTTP service (:7077)
├── data_mongo/                     # MongoDB data/config/logs volumes
├── models/                         # Downloaded models (see step 1)
└── datasets/                       # Downloaded datasets, incl. conda env archives under env/ (see step 1)
```

## Prerequisites

- Linux x86_64, NVIDIA driver >= 535 (the reference machine has 8x RTX 5880 Ada, 49 GB each), and `nvidia-smi` reports CUDA Version 12.4
- Anaconda/Miniconda
- Docker
- ~120 GB free disk (models + datasets + conda env archives and unpacked envs + MongoDB data)
- >= 128 GB system RAM (256 GB recommended)

## Setup

All components below are long-running services; run them inside tmux (one window
per service) so they survive SSH disconnects and stay easy to inspect and restart.
`start_all.sh` at the repo root runs the entire flow below in one go — downloads,
environment setup, Docker infra, and every service in a tmux session named
`evophish` (re-running it is safe: finished steps are skipped, running services
are restarted):

```bash
./start_all.sh
tmux attach -t evophish   # one window per service: vllm, vlm_rerank, phishintention, ...
```

The steps below describe the same process manually.

### 1. Download models, datasets, and environments

```bash
mkdir -p models datasets
huggingface-cli download code-philia/EvoPhish --repo-type model --local-dir ./models
huggingface-cli download code-philia/EvoPhish --repo-type dataset --local-dir ./datasets
unzip ./datasets/logos/logos.zip -d ./datasets/logos/
mv ./models/embedding/*.npy ./rbpd/PhishIntention/
huggingface-cli download Qwen/Qwen3-VL-32B-Instruct --repo-type model --local-dir ./models/Qwen3-VL-32B-Instruct
```

The dataset download includes the conda environment archives under `datasets/env/`.

### 2. Create the conda environments

Each environment ships in two forms:

| File | Purpose | Fidelity |
|---|---|---|
| `datasets/env/<env>.tar.gz` | conda-pack full archive (all binaries, including the locally compiled detectron2) | Bit-for-bit, recommended |
| `env_exports/<env>.yml` | Full `conda env export` spec (including pip packages) | Requires network reinstall; locally built packages will not install |

The recommended way is to unpack the conda-pack archives (bit-for-bit identical,
no network needed; the target machine only needs a reasonably recent glibc):

```bash
for env in phishintention Reptile video; do
  mkdir -p $(conda info --base)/envs/$env
  tar -xzf datasets/env/$env.tar.gz -C $(conda info --base)/envs/$env
done
conda activate phishintention && conda-unpack && conda deactivate
conda activate Reptile && conda-unpack && conda deactivate
conda activate video && conda-unpack && conda deactivate
```

Alternatively, rebuild from the yml specs (for portability / minimal setups):

```bash
conda env create -f datasets/env/phishintention.yml
```

Caveats (using phishintention as the example):

- `torch==2.4.0+cu124`, `torchvision==0.19.0+cu124` etc. are not on the default PyPI
  index. Use `-i https://download.pytorch.org/whl/cu124`, or strip the `+cu124`
  suffix from the spec and install PyTorch manually afterwards.
- `detectron2==0.6+fd27788pt2.4.0cu124` was compiled from source and is not on PyPI.
  Rebuild it on the target machine:
  `pip install 'git+https://github.com/facebookresearch/detectron2.git'`
- The yml lists both `nvidia-cudnn-cu12` and `nvidia-cudnn-cu13`. The cu13 package
  overwrites the cu12 cudnn libraries and causes `CUDNN_STATUS_NOT_INITIALIZED`
  at runtime — see Troubleshooting below for the fix.

Environment roles:

| Environment | Used for |
|---|---|
| `Reptile` | everything under `pipeline/` |
| `phishintention` | `rbpd/PhishIntention` service |
| `video` | vLLM backend + VLM rerank service under `rbpd/vlm` |

The screenshot service needs a browser:

```bash
conda activate Reptile
playwright install chromium
playwright install
```

### 3. Start the infrastructure (Docker)

CertStream:

```bash
docker run -d --name certstream -p 8080:8080 0rickyy0/certstream-server-go
```

Kafka:

```bash
docker run -d \
  --name zookeeper \
  -e ZOOKEEPER_CLIENT_PORT=2181 \
  -e ZOOKEEPER_TICK_TIME=2000 \
  confluentinc/cp-zookeeper:7.5.0
```

```bash
docker run -d \
  --name kafka \
  --link zookeeper \
  -p 9092:9092 \
  -e KAFKA_BROKER_ID=1 \
  -e KAFKA_ZOOKEEPER_CONNECT=zookeeper:2181 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_LOG_RETENTION_MS=600000 \
  -e KAFKA_LOG_ROLL_MS=300000 \
  -e KAFKA_LOG_RETENTION_CHECK_INTERVAL_MS=300000 \
  confluentinc/cp-kafka:7.5.0
```

MongoDB — first create the config file (if it is missing, Docker silently creates a
*directory* at that path and the mount is wrong):

```bash
mkdir -p ./data_mongo/config ./data_mongo/data ./data_mongo/logs
touch ./data_mongo/config/mongod.conf
```

```bash
docker run -dit --name mongo_certstream_demo \
  -p 27021:27017 \
  -v ./data_mongo/config/mongod.conf:/etc/mongod.conf \
  -v ./data_mongo/data/:/data/db \
  -v ./data_mongo/logs/:/var/log/mongodb \
  -e MONGO_INITDB_ROOT_USERNAME=yourusername \
  -e MONGO_INITDB_ROOT_PASSWORD=yourpassword \
  --restart=always \
  mongo
```

Then sync the credentials in `pipeline/common.py`
(`MONGO_USERNAME` / `MONGO_PASSWORD` must match the values above).
Note: the credentials only take effect on the *first* container initialization;
recreating the container resets them.

Redis (two instances: priority queues on 6380, dedup on 6381):

```bash
docker run -d --name certstream_redis -p 6380:6379 redis
docker run -d --name certstream_deduplicate_redis -p 6381:6379 redis
```

### 4. Start the RBPD services

vLLM backend (Qwen3-VL-32B, port 7000, uses GPUs 0-3 by default):

```bash
conda activate video
cd rbpd/vlm
./start_vllm.sh
```

VLM rerank service (port 7077):

```bash
conda activate video
cd rbpd/vlm
python stage3_rerank_service.py
```

PhishIntention service (port 5001):

```bash
conda activate phishintention
cd rbpd/PhishIntention
export PYTHON_MULTIPROCESSING_START_METHOD=spawn
gunicorn -w 2 --worker-class=gthread --threads 2 -t 120 -b 0.0.0.0:5001 app:app
```

### 5. Start the pipeline

All pipeline components run in the `Reptile` environment from `pipeline/`:

```bash
conda activate Reptile
cd pipeline
```

```bash
# Collect domains from CertStream into Kafka
nohup python certstream_producer.py > certstream.log 2>&1 &

# Extract domain embeddings and typo flags
nohup python typo_consumer.py > typo.log 2>&1 &

# Pop from the priority queues and dispatch screenshot jobs
nohup python redis_consumer.py --exp_name ablation_charcnn_phishintention_vlm_r90 > redis_consumer.log 2>&1 &

# Screenshot service (listens on the experiment's port, 6002 by default)
nohup python ./screenshot.py --exp_name ablation_charcnn_phishintention_vlm_r90 > screenshot.log 2>&1 &

# Retrain every 2 hours and restart model_consumer with fresh weights
./ablation_charcnn_phishintention_vlm_r90.sh
```

Experiment names are registered in `pipeline/common.py` (`EXP_NAMES` /
`ALL_EXPERIMENTS`); `--exp_name` choices come from there.

### 6. Inspect results

```bash
conda activate Reptile
cd pipeline
python view_results.py --exp_name ablation_charcnn_phishintention_vlm_r90 \
  --start 2026-08-06 --end 2026-09-07
```

Confirmed phishing screenshots are saved to `phish_pictures/<exp_name>/`.

## Ports

| Port | Service |
|---|---|
| 8080 | CertStream websocket |
| 9092 | Kafka |
| 27021 | MongoDB |
| 6380 | Redis (priority queues) |
| 6381 | Redis (dedup) |
| 5001 | PhishIntention service |
| 6000-6004 | Screenshot services (per experiment) |
| 7000 | vLLM backend |
| 7077 | VLM rerank service |

## GPU allocation (reference machine)

Some device indices are hardcoded; adjust them if your GPU layout differs:

| GPU | Occupant |
|---|---|
| 0-3 | vLLM backend (`rbpd/vlm/start_vllm.sh`) |
| 4 | `typo_consumer.py` (`CUDA_VISIBLE_DEVICES`) + `model_consumer.py` |
| 5 |  PhishIntention service (`_DEVICE = 'cuda:5'` in `rbpd/PhishIntention/phishintention.py`) |

## Troubleshooting

- **`CUDNN_STATUS_NOT_INITIALIZED` in the phishintention env**: a stray
  `nvidia-cudnn-cu13` package has overwritten the cu12 cudnn libraries. Check
  `python -c "import torch; print(torch.backends.cudnn.version())"` — it must print
  `90100`. If it prints `92000`, run
  `pip install --force-reinstall --no-deps nvidia-cudnn-cu12==9.1.0.70`.
  Avoid installing packages that pull in `cuda-bindings` / `cuda-toolkit` /
  `nvidia-*-cu13` into this environment.
- **MongoDB `Authentication failed`**: the credentials in `pipeline/common.py` do not
  match the container's `MONGO_INITDB_ROOT_*` values, or the container was recreated
  (which resets the users).
- **MongoDB config mount**: make sure `./data_mongo/config/mongod.conf` exists as a
  *file* before `docker run`, otherwise Docker creates a directory there.
- **All CharCNN models "skip" at startup**: almost always CUDA OOM because the
  hardcoded GPU is occupied — check `nvidia-smi` and move the process to a free GPU.
