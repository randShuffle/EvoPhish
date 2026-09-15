import argparse
import json
import time
from confluent_kafka import Consumer, KafkaException
import redis
from model_inference import FastTextSingle,TfIdfLogisticRegression,FastTextBagging,CharCNNInference,IsOod,CanineInference
from datetime import datetime
from common import (
    EXP_NAMES,
    REDIS_PORT,
    KAFKA_PORT,
    MONGO_URI,
    MONGO_DB_NAME,
    parse_risk_ratio,
    transform_domains,
)
import random
from pymongo import MongoClient
import msgpack
import os
import torch
import requests
os.environ["CUDA_VISIBLE_DEVICES"] = "0"


class CertstreamConsumer:
    def __init__(self, exp_name, batch_size=5000,queue_max_size=5000):
        self.exp_name = exp_name
        self.batch_size = batch_size
        self.group_id = f"{exp_name}-group"
        self.queue_max_size = queue_max_size
        self.batch = []
        self.is_typo_list = []
        self.embedding_list = []
        self.consumer = self._create_consumer()
        self.redis_client = redis.Redis(host='localhost', port=REDIS_PORT, db=0)
        self.risk_queue_key = f'risk:{self.exp_name}'
        self.rand_queue_key = f'rand:{self.exp_name}'  # 随机采样臂队列
        self.risk_ratio = parse_risk_ratio(exp_name)  # 风险优先比例，由实验名 _r<n> 后缀解析，默认 1.0
        with open("./redis.lua", "r", encoding="utf-8") as f:
            self.lua_script = f.read()
        sha = self.redis_client.script_load(self.lua_script)
        self.lua_sha = sha


        self.mongo_client = MongoClient(MONGO_URI)
        self.db = self.mongo_client[MONGO_DB_NAME]
        self.collections = {}

        for exp_name in EXP_NAMES:
            if "baseline" not in exp_name:
                self.collections["all_data_"+exp_name] = self.db["all_data_"+exp_name]



        if "fasttext" in self.exp_name:
            self.classifier = FastTextBagging(model_dir=f"../models/ablation/{self.exp_name}/models")
        elif "charcnn" in self.exp_name:
            self.classifier = CharCNNInference(model_dir=f"../models/ablation/{self.exp_name}/models")
        elif "tfidf" in self.exp_name:
            self.classifier = TfIdfLogisticRegression(model_dir=f'../models/ablation/{self.exp_name}/models')


    def _create_consumer(self):
        conf = {
            'bootstrap.servers': f'localhost:{KAFKA_PORT}',
            'group.id': self.group_id,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
            'auto.commit.interval.ms': 5000
        }
        return Consumer(conf)




    def add_to_priority_queue_pipe(self,pipe, domain: str, probability: float, is_typo: int):

        metadata_key = f'domain_metadata:{self.exp_name}:risk'

        if self.exp_name=="field_no_priority_no_retrain_no_negative_charcnn_phishintention":
            if probability>=0.5:
                priority_score = probability
            else:
                return
        elif self.exp_name in ["field_no_priority_no_retrain_charcnn_phishintention","field_no_priority_charcnn_phishintention"]:
            if probability>=0.5:
                priority_score = probability
            else:
                priority_score = random.uniform(0, 0.5)
        elif "baseline" in self.exp_name:
            priority_score = random.uniform(0, 1)
        else:
            priority_score = probability+10*is_typo

        # 风险臂：按风险分高低保留
        pipe.evalsha(self.lua_sha, 2, self.risk_queue_key, metadata_key,
                    domain, str(priority_score),
                    json.dumps({
                        "probability": probability,
                        "is_typo": is_typo,
                        "sample_type": "risk",
                    }), str(self.queue_max_size))

        # 随机臂：随机分数 + 定容淘汰 = 对数据流的均匀随机采样
        pipe.evalsha(self.lua_sha, 2, self.rand_queue_key, f'domain_metadata:{self.exp_name}:rand',
                    domain, str(random.uniform(0, 1)),
                    json.dumps({
                        "probability": probability,
                        "is_typo": is_typo,
                        "sample_type": "rand",
                    }), str(self.queue_max_size))



    def process_message(self, msg):
        try:

            payload_bytes = msg.value()
            payload = msgpack.unpackb(payload_bytes, raw=False)
            domain = payload.get("domain")
            is_typo = payload.get("is_typo")
            embedding = payload['embedding']  # Type:List

            self.batch.append(domain)
            self.embedding_list.append(embedding)

            if self.exp_name not in ["baseline_phishpedia","baseline_phishintention"]:
                self.is_typo_list.append(is_typo)
            else:
                self.is_typo_list.append(0)


            if len(self.batch) >= self.batch_size:

                start = datetime.now()
                if self.exp_name not in ["baseline_phishpedia","baseline_phishintention","baseline_phishvlm"]:
                    transform_domains_result = transform_domains(self.batch)
                    probability_list = self.classifier.inference(transform_domains_result)
                    embedding_tensors = torch.tensor(self.embedding_list).to("cuda:0")
                else:

                    probability_list = [0.0 for _ in range(len(self.batch))]

                if "baseline" not in self.exp_name:
                    documents = []
                    for i, domain in enumerate(self.batch):
                        prob = probability_list[i]
                        doc = {
                            "timestamp": datetime.now(),
                            "ori_domain": domain,
                            "is_typo": self.is_typo_list[i],
                            "domain_classifier_prob": prob,
                            "domain_classifier": int(prob >= 0.5)
                        }
                        documents.append(doc)

                    if documents:
                        self.collections["all_data_"+self.exp_name].insert_many(documents)


                start = datetime.now()


                pipe = self.redis_client.pipeline()
                for i in range(self.batch_size):
                    self.add_to_priority_queue_pipe(pipe, self.batch[i], probability_list[i], self.is_typo_list[i])
                pipe.execute()


                self.batch.clear()
                self.is_typo_list.clear()
                self.embedding_list.clear()
                print(f'redis over:{datetime.now()-start}')


        except Exception as e:
            print(f"{self.exp_name} decode error: {e}")


    def start_consuming(self, topic='certstream-with-typo'):

        self.consumer.subscribe([topic])

        try:
            while True:
                msg = self.consumer.poll(1.0)

                if msg is None:
                    continue
                if msg.error():
                    raise KafkaException(msg.error())

                self.process_message(msg)

        except KeyboardInterrupt:
            print(f"{self.exp_name} stopped.")
        finally:

            if self.batch:
                print(f"{self.exp_name} processing remaining {len(self.batch)} messages...")
            self.consumer.close()
            self.mongo_client.close()
            print(f"{self.exp_name} consumer closed.")



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exp_name', required=True, choices=EXP_NAMES)
    parser.add_argument('--queue_max_size', type=int, default=5000, help='Batch size for processing')
    parser.add_argument('--batch-size', type=int, default=5000, help='Batch size for processing')
    args = parser.parse_args()

    consumer = CertstreamConsumer(args.exp_name, args.batch_size,args.queue_max_size)
    consumer.start_consuming()

if __name__ == "__main__":
    main()
