# EvoPhish

## 📂 Structure

This repository contains three components:
1. The EvoPhish **core** module (`/pipeline`).
2. The **rbpd** module (`/rbpd`), which implements PhishIntention.

```
├── pipeline/                      # Core detection pipeline
│   ├── alphabet.json              # Character set mapping (for CharCNN text encoding)
│   ├── browser.sh                 # Launch browser screenshot
│   ├── certstream_producer.py     # CertStream producer
│   ├── common.py                  # Common variables
│   ├── field_charcnn_phishintention.sh    # Start script
│   ├── field_no_priority_charcnn_phishintention.sh   # Start script
│   ├── field_no_priority_no_retrain_charcnn_phishintention.sh  # Start script
│   ├── model_consumer.py          # Fast thinker Model task consumer
│   ├── model_inference.py         # Core model inference
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
|   │       ├── pixi.toml                  # Pixi environment config
│   │       ├── poll.py                    # Scheduled task (pull threat intel)
│   │       ├── presets.py                 # Presets & constants
│   │       ├── setup.sh                   # Env initialization 
│   │       └── transforms.py              # Data preprocessing
```



## ⚙️ Setup
Clone the repository and follow the steps below:

1. Create a conda environment for evophish.
    ```bash
    conda env create -f environment.yml
    conda activate evophish
    pip install .
    ```
    
2. Download checkpoints for typo model.
    ```bash
    mkdir -p models
    cd models
    mkdir -p trained
    cd trained
    gdown --id "1tGrYo7169IQ8TZUvEtk5eZ4o9pp2PMmO" -O "typo_model.zip"
    unzip typo_model.zip
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
   docker run -dit --name mongo_certstream \
   -p 27019:27017 \
   -v ./config/mongod.conf:/etc/mongod.conf \
   -v ./data/:/data/db \
   -v ./logs/:/var/log/mongodb \
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
   ./browser.sh
   ```

   ```bash
   # Initialize Redis-based deduplication and a Redis priority queue.
   ./redis_consumer.sh
   ```

   ```bash
   # Start the experiment script.
   ./field_charcnn_phishintention.sh
   ./field_no_priority_charcnn_phishintention.sh
   ./field_no_priority_no_retrain_charcnn_phishintention.sh
   ```
   







