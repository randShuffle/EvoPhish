from flask import Flask, request, jsonify
from flask_cors import CORS
import base64
from io import BytesIO
from PIL import Image
from datetime import datetime
import os
from phishintention import PhishIntentionWrapper
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from io import BytesIO
import cv2
import numpy as np
import logging
from PIL import Image
import cv2
import os
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from Crypto.Cipher import AES
import base64
import redis
from dotenv import load_dotenv
load_dotenv()
BLACKLIST_URL = f"http://127.0.0.1:{os.getenv('SERVICE_PORT')}/blacklist"

key = b'ThisIsA16ByteKey'

def encrypt_filename(name):
    cipher = AES.new(key, AES.MODE_ECB)
    data = name.encode('utf-8')
    padding_len = 16 - len(data) % 16
    data += bytes([padding_len]) * padding_len
    encrypted = cipher.encrypt(data)
    return base64.urlsafe_b64encode(encrypted).decode()

def decrypt_filename(enc_name):
    cipher = AES.new(key, AES.MODE_ECB)
    decoded = base64.urlsafe_b64decode(enc_name)
    decrypted = cipher.decrypt(decoded)
    padding_len = decrypted[-1]
    return decrypted[:-padding_len].decode()


log = logging.getLogger('werkzeug')
log.disabled = True


import requests
from urllib.parse import urlparse
import socket


def get_ip(url):
    parsed_url = urlparse(url)
    host = parsed_url.hostname
    ip = socket.gethostbyname(host)
    return ip

def get_ip_and_geolocation(ori_url):
    try:
        ip = get_ip(ori_url)
        access_token = 'xxxxx'
        url = f"https://ipinfo.io/{ip}/json?token={access_token}"
        response = requests.get(url)
        data = response.json()
        return ip,float(data['loc'].split(',')[0]),float(data['loc'].split(',')[1]),data['country'], data['org']
    except:
        print("error")
        return None,0,0,None,None
        
    
  


app = Flask(__name__)
CORS(app)


username = "yourusername"
password = "yourpassword"
MONGO_URI = f'mongodb://{username}:{password}@localhost:27019/'
DB_NAME = 'certstream'

EXP_NAMES = ["baseline_phishintention",
             "baseline_phishpedia",
             "ablation_fasttext_phishintention","ablation_charcnn_phishintention","ablation_tfidf_phishintention",
             "baseline_phishintel","field_charcnn_phishintention","field_no_priority_charcnn_phishintention",
             "field_no_priority_no_retrain_charcnn_phishintention","field_no_priority_no_retrain_no_negative_charcnn_phishintention",]




with app.app_context():
    phishpedia_cls = PhishIntentionWrapper()
    

    try:
        mongo_client = MongoClient(MONGO_URI)

        mongo_client.admin.command('ping')
        db = mongo_client[DB_NAME]
        results_collection_dict = {}
        for exp_name in EXP_NAMES:
            results_collection_dict[exp_name] = db[exp_name]
            
       
    except ConnectionFailure as e:

        mongo_client = None
    except Exception as e:
 
        mongo_client = None
        

    phishintel_redis = redis.Redis(host='localhost', port=6381, db=2)

def save_result_to_mongodb(result_data,exp_name):

    if mongo_client is None:

        return False
    try:
        result = results_collection_dict[exp_name].insert_one(result_data)
        return result.acknowledged
    except OperationFailure as e:
 
        return False
    except Exception as e:

        import traceback
        traceback.print_exc()
        return False


@app.route('/analyze', methods=['POST'])
def analyze():
    try:
        data = request.get_json()
        url = data.get('url')
        screenshot_path = data.get('screenshot_path')
        html_path = screenshot_path.replace(".png",".txt")
        ori_domain = data.get("ori_domain")
        exp_name = data.get("exp_name")
        timestamp = data.get("timestamp")
        timestamp = datetime.fromisoformat(timestamp)
        model_version = data.get("model_version")
        is_typo = data.get("is_typo")
        domain_classifier_result = data.get("domain_classifier")
        domain_classifier_prob = data.get("domain_classifier_prob")
        ood_score = data.get("ood_score")
        is_ood = data.get("is_ood")
        
        

        phish_category,pred_target, matched_domain,siamese_conf,sim_file_name,plotvis= phishpedia_cls.test_orig_phishintention(url,screenshot_path)

        result = {
            "ori_domain":ori_domain,
            "url":url,
            "phish_category": int(phish_category),
            "pred_target": str(pred_target),
            "siamese_conf": float(siamese_conf) if siamese_conf else 0.0,
            'timestamp': timestamp,
            "model_version":model_version,
            "is_typo":is_typo,
            "domain_classifier":domain_classifier_result,
            "domain_classifier_prob":domain_classifier_prob,
            "is_ood":is_ood,
            "ood_score":ood_score
        }

        if phish_category==2:
            
            save_dir = os.path.join("../../phish_pictures", exp_name)
            os.makedirs(save_dir, exist_ok=True) 
      
            save_path = os.path.join(save_dir, f"{encrypt_filename(ori_domain)}.png")
     
            cv2.imwrite(save_path, plotvis)
            
 
            ip,lat,lon,country,org = get_ip_and_geolocation(url)
            result["ip"] = ip
            result["latitude"] = lat
            result["longitude"] = lon
            result["country"] = country
            result["org"] = org
            
      
            blacklist_request = {
                "exp_name": exp_name,
                "ori_domain": ori_domain,
                "url": url,
                "pred_target": pred_target
            }
            if exp_name=="field_charcnn_phishintention":
                try:
                    requests.post(BLACKLIST_URL, json=blacklist_request)
                except Exception as e:
                    print(f"Error in submitting to blacklist service: {str(e)}")


        save_result_to_mongodb(result,exp_name)
        
        if exp_name=="phishintel":
            phishintel_redis.set(f"url_cache:{url}", phish_category)

        print("phishintention: "+url)
        return jsonify({"success": True, "phish_category": phish_category})

    except Exception as e:
        print(f"Error in analyze: {url}  {str(e)}")
        return jsonify({"success": False, "error": str(e)})
    finally:        
        new_screenshot_path = screenshot_path.replace('.png','_new.png')
        new_html_path = new_screenshot_path.replace('.png', '.txt')
        new_info_path = new_screenshot_path.replace('.png', '_new_info.txt')
        cv_path = screenshot_path.replace('.png', '_4cv.png')
        for file_path in [screenshot_path,html_path,new_screenshot_path,new_html_path,new_info_path,cv_path]:
            if os.path.exists(file_path):
                os.remove(file_path)
        
        
        
      
        

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False)    