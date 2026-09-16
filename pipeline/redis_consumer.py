import time
import requests
import redis
import json
import random
import argparse
from common import EXP_NAMES,REDIS_PORT,parse_risk_ratio,screenshot_port
from datetime import datetime

class PriorityQueueWorker:
    def __init__(self, exp_name, redis_host='localhost', redis_port=REDIS_PORT):
        self.exp_name = exp_name
        self.redis = redis.Redis(host=redis_host, port=redis_port, db=0)
        self.screenshot_url = f"http://localhost:{screenshot_port(self.exp_name)}/screenshot"
        # Risk-priority ratio, parsed from the _r<n> suffix of the experiment name
        self.risk_ratio = parse_risk_ratio(exp_name)
        self.use_rand = self.risk_ratio < 1.0


    def get_top_element(self,queue_key):
        result = self.redis.zrevrange(queue_key, 0, 0)
        if result:
            return result[0].decode('utf-8')
        return None

    def remove_element(self, element,queue_key,metadata_key):
        self.redis.zrem(queue_key, element)
        self.redis.hdel(metadata_key, element)

    def get_metadata(self, element,metadata_key):
        raw = self.redis.hget(metadata_key, element)
        if raw:
            try:
                return json.loads(raw)
            except Exception:
                return {}
        return {}

    def process_element(self, element, queue_type):
        metadata_key = f'domain_metadata:{self.exp_name}:{queue_type}'
        queue_key = f'{queue_type}:{self.exp_name}'

        metadata = self.get_metadata(element,metadata_key)
        probability = metadata.get("probability", "N/A")
        is_typo = metadata.get("is_typo", "N/A")
        sample_type = metadata.get("sample_type", "risk")


        try:

            resp = requests.post(self.screenshot_url, timeout=2,json={"ori_domain": element,
                    "domain_classifier":int(probability>=0.5),
                    "domain_classifier_prob":probability,
                    "is_typo":is_typo,
                    "exp_name":self.exp_name,
                    "model_version":-1,
                    "timestamp":datetime.now().isoformat(),
                    "sample_type":sample_type
                    })
            if resp.status_code == 200:
                print(f"[✓] {self.exp_name}***Success: {element} (typo={is_typo}, prob={probability}, sample_type={sample_type}), removing from queue.")
                self.remove_element(element,queue_key,metadata_key)
                return True
            else:
                return False
        except Exception as e:
            print(f"[!] Error processing {element}: {e}")
            return False

    def run(self):
        print(f"🌀 Priority Queue Worker started for exp_num: {self.exp_name} (risk_ratio={self.risk_ratio})")

        while True:
            try:

                # Risk/random mixed sampling: pick between the risk/rand queues with probability x:(1-x)
                if self.use_rand:
                    queue_type = "risk" if random.random() < self.risk_ratio else "rand"
                else:
                    queue_type = "risk"

                queue_key = f'{queue_type}:{self.exp_name}'
                element = self.get_top_element(queue_key)

                if element:
                    self.process_element(element, queue_type)
                else:
                    time.sleep(0.1)
            except:
                pass

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--exp_name', required=True, choices=EXP_NAMES)
    args = parser.parse_args()
    worker = PriorityQueueWorker(args.exp_name)
    worker.run()
