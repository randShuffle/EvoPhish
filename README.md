# EvoPhish

## 📂 Structure

This repository contains three components:
1. The EvoPhish **core** module (`/pipeline`).
2. The **rbpd** module (`/rbpd`), which implements PhishIntention with patch and the vlm patch service.(slow thinker)

```
├── pipeline/                      # Core detection pipeline
│   ├── alphabet.json              # Character set mapping (for CharCNN text encoding)
│   ├── certstream_producer.py     # CertStream producer
│   ├── common.py                  # Common variables
│   ├── ablation_charcnn_phishintention_vlm.sh    # Start script
│   ├── model_consumer.py          # Fast thinker Model task consumer
│   ├── model_inference.py         # Core fast thinker model inference
│   ├── model_update.py            # Model update
│   ├── redis_consumer.py          # General Redis consumer
│   ├── redis_consumer.sh          # Redis consumer startup script (simplify deployment)
│   ├── redis.lua                  # Redis batch task processing
│   ├── screenshot.py              # Webpage screenshot 
│   ├── typo_consumer.py           # Domain typo detection 
│   ├── rbpd/                      # Submodule root: PhishIntention core ability
│   │   └── PhishIntention/        # PhishIntention core
│   │       ├── configs/                    # Submodule config files
│   │       ├── modules/                    # Core function modules
│   │       ├── ocr_lib/                    # OCR library
│   │       ├── utils/                      # Submodule utilities
│   │       ├── __init__.py                 # Python package initialization file
│   │       ├── .env                        # Environment variables
│   │       ├── app.py                      # Submodule service entry (provide HTTP API)
│   │       ├── blacklist.py                # Blacklist management
│   │       ├── configs.py                 # Submodule config loader
│   │       ├── phishintention.py          # Core PhishIntention logic
│   │       ├── phishpedia_models.py        # PhishPedia model wrapper 
│   │       ├── presets.py                 # Presets & constants
│   │       ├── setup.sh                   # Env initialization 
│   │       └── transforms.py              # Data preprocessing
│   │   └── vlm                            # vlm 
│   │       ├── start_vllm.sh			   # start vllm backend
│   │       ├── stage3_rerank_service.py   # vlm patch service
```



## ⚙️ Setup
Clone the repository and follow the steps below:

1. Create a conda environment for evophish.
    ```bash
    conda env create -f environment_evophish.yml
    conda env create -f environment_phishintention.yml
    ```
    
2. Download models and datasets.
    ```bash
    mkdir -p models
    mkdir -p datasets
    huggingface-cli download code-philia/EvoPhish --repo-type model --local-dir ./models
    huggingface-cli download code-philia/EvoPhish --repo-type dataset --local-dir ./datasets
    unzip ./datasets/logos/logos.zip -d ./datasets/logos/
    mv ./models/embedding/*.npy ./rbpd/PhishIntention/
    huggingface-cli download Qwen/Qwen3-VL-32B-Instruct --repo-type model --local-dir ./models/Qwen3-VL-32B-Instruct

    ```

2. Create a conda environment for phishintention.
   
    ```bash
    cd rbpd/PhishIntention
    export KMP_DUPLICATE_LIB_OK=TRUE
    
    # Install pixi (restart your terminal after installation)
    curl -fsSL https://pixi.sh/install.sh | sh
    
    # Install Chrome (Ubuntu/Debian)
    wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    sudo dpkg -i google-chrome-stable_current_amd64.deb
    sudo apt-get install -f
    
    # Install dependencies (auto-detects GPU and installs appropriate PyTorch/Detectron2)
    pixi install
    ```
    
2. Start RBPD service(PhishIntention).
   
    ```bash
    pixi shell
    python app.py
    ```
    
5. Start vlm service

   ```bash
   cd rbpd/vlm
   ./start_vllm.sh
   python stage3_rerank_service.py
   ```

3. Start Certstream

   ```bash
   docker run -d --name certstream -p 8080:8080 0rickyy0/certstream-server-go
   ```

4. Start Kafka

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

5. Start MongoDB

   ```
   docker run -dit --name mongo_certstream_demo \
   -p 27021:27017 \
   -v ./data_mongo/config/mongod.conf:/etc/mongod.conf \
   -v ./data_mongo/data/:/data/db \
   -v ./data_mongo/logs/:/var/log/mongodb \
   -e MONGO_INITDB_ROOT_USERNAME=yourusername \
   -e MONGO_INITDB_ROOT_PASSWORD=yourpassword \
   --restart=always  \
   mongo
   ```

6. Start Redis

   ```bash
   docker run -d --name certstream_redis -p 6380:6379 redis
   ```

   ```bash
   docker run -d --name certstream_deduplicate_redis -p 6381:6379 redis
   ```

7. Start the whole pipeline

   ```bash
   # Start collecting data from Certstream.
   nohup python certstream_producer.py > certstream.log 2>&1 &
   ```

   ```bash
   # Extract domain embeddings as features for typo detection.
   nohup python typo_consumer.py > typo.log 2>&1 &
   ```

   ```bash
   # Start the screenshot script.
   nohup python ./screenshot.py --exp_name ablation_charcnn_phishintention_vlm_r90 > screenshot.log 2>&1 &
   ```

   ```bash
   # Initialize Redis-based deduplication and a Redis priority queue.
   nohup python ./redis_consumer.py --exp_name ablation_charcnn_phishintention_vlm_r90
   ```

   ```bash
   # Start the experiment script.
   ./ablation_charcnn_phishintention_vlm_r90.sh
   ```
   







