import time
import requests
import redis
import json
import argparse
from common import EXP_NAMES,REDIS_PORT,SCREENSHOT_BASIC_PORT
from datetime import datetime

class PriorityQueueWorker:
    def __init__(self, exp_name, redis_host='localhost', redis_port=REDIS_PORT):
        self.exp_name = exp_name
        self.redis = redis.Redis(host=redis_host, port=redis_port, db=0)
        self.screenshot_url = f"http://localhost:{SCREENSHOT_BASIC_PORT + EXP_NAMES.index(args.exp_name)}/screenshot"

        
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

    def process_element(self, element,is_ood):      
        if is_ood:
            metadata_key = f'domain_metadata:{self.exp_name}:ood'
            queue_key = f'ood:{self.exp_name}'
        else:
            metadata_key = f'domain_metadata:{self.exp_name}:risk'
            queue_key = f'risk:{self.exp_name}'
        
        metadata = self.get_metadata(element,metadata_key)
        probability = metadata.get("probability", "N/A")
        is_typo = metadata.get("is_typo", "N/A")
        ood_score = metadata.get("ood_score", "N/A")
    

        try:
            
            resp = requests.post(self.screenshot_url, timeout=2,json={"ori_domain": element,     
                    "domain_classifier":int(probability>=0.5),
                    "domain_classifier_prob":probability,
                    "is_typo":is_typo,
                    "exp_name":self.exp_name,
                    "model_version":-1,
                    "timestamp":datetime.now().isoformat(),
                    "ood_score":ood_score,
                    "is_ood":is_ood
                    })
            if resp.status_code == 200:
                print(f"[✓] {self.exp_name}***Success: {element} (typo={is_typo}, prob={probability},ood:{is_ood}), removing from queue.")
                self.remove_element(element,queue_key,metadata_key)
                return True
            else:
                return False
        except Exception as e:
            print(f"[!] Error processing {element}: {e}")
            return False

    def run(self):
        start = datetime.now()
        i = 0

        if "baseline" in self.exp_name:
            queue_cycle = ["risk"]
        else:
            queue_cycle = ["risk"]
            
        cycle_len = len(queue_cycle)
        index = 0

        while True:
            try:
                queue_type = queue_cycle[index % cycle_len]
                index += 1

                queue_key = f'risk:{self.exp_name}' if queue_type == "risk" else f'ood:{self.exp_name}'
                element = self.get_top_element(queue_key)

                if element:
                    self.process_element(element, is_ood=int(queue_type=="ood"))
                    i += 1
                    if i % 10 == 0:
                        pass
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
