#!/usr/bin/env bash
# One-click startup for EvoPhish: downloads, conda envs, Docker infra,
# and all services inside a single tmux session (default: evophish).
# Re-running is safe: finished steps are skipped, running services are restarted.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

EXP_NAME="${EXP_NAME:-ablation_charcnn_phishintention_vlm_r90}"
SESSION="${SESSION:-evophish}"
CONDA_BASE="$(conda info --base)"
CONDA_SH="$CONDA_BASE/etc/profile.d/conda.sh"

log() { echo "[start_all $(date '+%H:%M:%S')] $*"; }

wait_port() { # port timeout_seconds
  local port="$1" timeout="${2:-120}"
  for ((i = 0; i < timeout; i += 2)); do
    (echo > "/dev/tcp/127.0.0.1/$port") 2>/dev/null && return 0
    sleep 2
  done
  return 1
}

# ---------- 1. Download models, datasets, and environments ----------
if [ ! -d models/typo_model_10m_canine_no_subdomains ] || [ ! -f datasets/env/phishintention.tar.gz ]; then
  log "Downloading models and datasets from HuggingFace (this is large, one-time)..."
  mkdir -p models datasets
  huggingface-cli download code-philia/EvoPhish --repo-type model --local-dir ./models
  huggingface-cli download code-philia/EvoPhish --repo-type dataset --local-dir ./datasets
fi

if [ -f datasets/logos/logos.zip ]; then
  unzip -n -q datasets/logos/logos.zip -d datasets/logos/
fi
if compgen -G "models/embedding/*.npy" > /dev/null; then
  mv models/embedding/*.npy rbpd/PhishIntention/
fi
if [ ! -d models/Qwen3-VL-32B-Instruct ]; then
  log "Downloading Qwen3-VL-32B-Instruct (one-time)..."
  huggingface-cli download Qwen/Qwen3-VL-32B-Instruct --repo-type model --local-dir ./models/Qwen3-VL-32B-Instruct
fi

# ---------- 2. Conda environments ----------
for env in phishintention Reptile video; do
  if conda env list | awk '{print $1}' | grep -qx "$env"; then
    log "conda env '$env' already exists, skipping."
  else
    log "Unpacking conda env '$env' from datasets/env/$env.tar.gz ..."
    mkdir -p "$CONDA_BASE/envs/$env"
    tar -xzf "datasets/env/$env.tar.gz" -C "$CONDA_BASE/envs/$env"
    source "$CONDA_SH"
    conda activate "$env"
    conda-unpack
    conda deactivate
  fi
done

log "Ensuring Playwright chromium is installed..."
conda run -n Reptile playwright install chromium

# ---------- 3. Docker infrastructure ----------
ensure_container() { # name docker-run-args...
  local name="$1"; shift
  if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
    docker start "$name" > /dev/null
  else
    docker run "$@" > /dev/null
  fi
}

log "Starting Docker infrastructure..."
ensure_container certstream -d --name certstream -p 8080:8080 0rickyy0/certstream-server-go
ensure_container zookeeper -d --name zookeeper \
  -e ZOOKEEPER_CLIENT_PORT=2181 -e ZOOKEEPER_TICK_TIME=2000 \
  confluentinc/cp-zookeeper:7.5.0
ensure_container kafka -d --name kafka --link zookeeper -p 9092:9092 \
  -e KAFKA_BROKER_ID=1 \
  -e KAFKA_ZOOKEEPER_CONNECT=zookeeper:2181 \
  -e KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092 \
  -e KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1 \
  -e KAFKA_LOG_RETENTION_MS=600000 \
  -e KAFKA_LOG_ROLL_MS=300000 \
  -e KAFKA_LOG_RETENTION_CHECK_INTERVAL_MS=300000 \
  confluentinc/cp-kafka:7.5.0

mkdir -p data_mongo/config data_mongo/data data_mongo/logs
touch data_mongo/config/mongod.conf
MONGO_USER="$(grep -oP '^MONGO_USERNAME = "\K[^"]+' pipeline/common.py)"
MONGO_PASS="$(grep -oP '^MONGO_PASSWORD = "\K[^"]+' pipeline/common.py)"
ensure_container mongo_certstream_demo -dit --name mongo_certstream_demo \
  -p 27021:27017 \
  -v "$ROOT/data_mongo/config/mongod.conf:/etc/mongod.conf" \
  -v "$ROOT/data_mongo/data/:/data/db" \
  -v "$ROOT/data_mongo/logs/:/var/log/mongodb" \
  -e MONGO_INITDB_ROOT_USERNAME="$MONGO_USER" \
  -e MONGO_INITDB_ROOT_PASSWORD="$MONGO_PASS" \
  --restart=always \
  mongo

ensure_container certstream_redis -d --name certstream_redis -p 6380:6379 redis
ensure_container certstream_deduplicate_redis -d --name certstream_deduplicate_redis -p 6381:6379 redis

log "Waiting for Kafka/Mongo/Redis to accept connections..."
wait_port 9092 180 || { log "ERROR: Kafka did not come up in time"; exit 1; }
wait_port 27021 60 || { log "ERROR: MongoDB did not come up in time"; exit 1; }
wait_port 6380 30
wait_port 6381 30

# ---------- 4. All services in tmux ----------
tmux_window() { # window-name command
  tmux new-window -t "$SESSION" -n "$1" \
    "source '$CONDA_SH' && $2; echo '[window] process exited, shell kept open'; exec bash"
}

log "Starting all services in tmux session '$SESSION'..."
tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -n vllm \
  "source '$CONDA_SH' && conda activate video && cd '$ROOT/rbpd/vlm' && bash ./start_vllm.sh; echo '[window] process exited, shell kept open'; exec bash"

tmux_window vlm_rerank "conda activate video && cd '$ROOT/rbpd/vlm' && until curl -sf http://localhost:7000/health > /dev/null 2>&1; do echo 'waiting for vLLM (:7000)...'; sleep 15; done && python stage3_rerank_service.py"
tmux_window phishintention "conda activate phishintention && cd '$ROOT/rbpd/PhishIntention' && gunicorn -w 2 --worker-class=gthread --threads 2 -t 120 -b 0.0.0.0:5001 app:app"
tmux_window certstream "conda activate Reptile && cd '$ROOT/pipeline' && python certstream_producer.py"
tmux_window typo "conda activate Reptile && cd '$ROOT/pipeline' && python typo_consumer.py"
tmux_window model_consumer "conda activate Reptile && cd '$ROOT/pipeline' && chmod u+x ./ablation_charcnn_phishintention_vlm_r90.sh && ./ablation_charcnn_phishintention_vlm_r90.sh"
tmux_window redis_consumer "conda activate Reptile && cd '$ROOT/pipeline' && python redis_consumer.py --exp_name $EXP_NAME"
tmux_window screenshot "conda activate Reptile && cd '$ROOT/pipeline' && python screenshot.py --exp_name $EXP_NAME"

if [ -f "pipeline/$EXP_NAME.sh" ]; then
  tmux_window retrain "conda activate Reptile && cd '$ROOT/pipeline' && bash './$EXP_NAME.sh'"
else
  log "No retrain script pipeline/$EXP_NAME.sh, skipping the retrain loop."
fi

log "Done. Attach with: tmux attach -t $SESSION   (one window per service)"
