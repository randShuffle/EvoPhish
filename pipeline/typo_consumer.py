import json
from datetime import datetime
from confluent_kafka import Consumer, KafkaException, Producer
from model_inference import IsTypo
from common import KAFKA_BROKER, KAFKA_PORT,TYPO_MODEL_DIR
import redis
import time
from pymongo import MongoClient
import msgpack
import os
os.environ["CUDA_VISIBLE_DEVICES"] = "1"

BATCH_SIZE = 5000
MEMORY_CACHE_TTL = 60*5    
REDIS_TTL = 24 * 3600    

class TypoInferenceConsumer:
    def __init__(self):
        self.consumer = self._create_consumer()
        self.producer = Producer({'bootstrap.servers': KAFKA_BROKER})
        self.batch = []
        self.typo_model = IsTypo(TYPO_MODEL_DIR)
        self.redis = redis.Redis(host='localhost', port=6381, db=0)
        self.memory_cache = {}
        
        username = "yourusername"
        password = "yourpassword"
        MONGO_URI = f'mongodb://{username}:{password}@localhost:27019/'
        DB_NAME = 'certstream'
        self.client = MongoClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        self.collection = self.db["throughput"]
        
        
        

    def _create_consumer(self):
        conf = {
            'bootstrap.servers': f'localhost:{KAFKA_PORT}',
            'group.id': 'inference-group',
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 5000
        }
        return Consumer(conf)

    def delivery_report(self, err, msg):
        if err:
            print(f"[Kafka Error] Delivery failed: {err}")

    def send_with_predictions(self, domain, domain_embedding,is_typo):
        payload = {
            "domain": domain,
            "is_typo": is_typo,
            "embedding":domain_embedding.tolist()
        }
        
        payload_bytes = msgpack.packb(payload)
        
        self.producer.produce(
            "certstream-with-typo",
            value = payload_bytes,
            callback=self.delivery_report
        )
        self.producer.poll(0)
        
    def handle_batch(self, batch):
        now = time.time()
        unique_batch = []
        for domain in batch:
            if domain in self.memory_cache and now - self.memory_cache[domain] < MEMORY_CACHE_TTL:
                continue
            self.memory_cache[domain] = now
            unique_batch.append(domain)

        if not unique_batch:
            return []

        pipe = self.redis.pipeline()
        redis_keys = [f"domain:{d}" for d in unique_batch]
        for key in redis_keys:
            pipe.setnx(key, 1)
            pipe.expire(key, REDIS_TTL)
        results = pipe.execute()

        new_domains = []
        for domain, setnx_result in zip(unique_batch, results[::2]): 
            if setnx_result == 1:
                new_domains.append(domain)

        return new_domains

 
    def process_batch(self):
        new_domains = self.handle_batch(self.batch)
        if new_domains:
            domain_embeddings,typos = self.typo_model.inference(new_domains)
            for i in range(len(typos)):
                self.send_with_predictions(new_domains[i],domain_embeddings[i], typos[i])
                
        self.batch.clear()
        return datetime.now()

    def start(self):
        self.consumer.subscribe(["certstream-raw-domains"])
        try:
            start = datetime.now()
            while True:
                msg = self.consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    raise KafkaException(msg.error())

                domain = msg.value().decode('utf-8')
                self.batch.append(domain)

                if len(self.batch) >= BATCH_SIZE:
                    record = {
                        "timestamp": datetime.now(),  
                        "nums": len(self.batch)  
                    }
                    self.collection.insert_one(record)  
                    cur = self.process_batch()
                    print(cur-start)
                    start = cur

        except KeyboardInterrupt:
            print("InferenceConsumer stopped.")
        finally:
            if self.batch:
                self.process_batch()
            self.consumer.close()
            self.producer.flush()

if __name__ == "__main__":
    TypoInferenceConsumer().start()
