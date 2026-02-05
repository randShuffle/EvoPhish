import sys
import os
from pymongo import MongoClient
sys.stderr = open(os.devnull, 'w') 
import asyncio
import aiohttp
import logging
from datetime import datetime, timezone, timedelta
import argparse
import httpx
import time
import json
from dotenv import load_dotenv
load_dotenv()
# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,  # Set the level to INFO
    format='%(asctime)s - %(levelname)s - %(message)s',
)


username = "yourusername"
password = "yourpassword"
MONGO_URI = f'mongodb://{username}:{password}@localhost:27019'
DB_NAME = 'certstream'

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
headers = {
    "User-Agent":'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/5d7.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36'
}
PROXY_SERVER = os.getenv('PROXY_SERVER')
SERVICE_PORT = int(os.getenv('SERVICE_PORT'))
LOCAL_SVR_ADDR = os.getenv('LOCAL_SVR_ADDR')
API_ADDR = f"{os.getenv('GOOGLE_SAFE_BROWSING_API')}?key={os.getenv('GOOGLE_SAFE_BROWSING_KEY')}"




async def lookupGoogleSafeBrowse(url, server_addr):
    # --CONFIGS--
    THREAT_TYPES = ["SOCIAL_ENGINEERING"] # can also use "MALWARE", "UNWANTED_SOFTWARE"
    PLATFORM_TYPES = ["ANY_PLATFORM"]
    THREAT_ENTRY_TYPES = ["URL"]
    # -----------
    try:
        # logging.info(f'[LOOKUP] Looking up {url} in {server_addr}')
        payload = {
            "threatInfo": {
                "threatTypes": THREAT_TYPES,
                "platformTypes": PLATFORM_TYPES,
                "threatEntryTypes": THREAT_ENTRY_TYPES,
                "threatEntries": [{"url": url}]
            }
        }
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.post(server_addr, json=payload)
            if response.status_code != 200:
                # print(f"LookupGoogleSafeBrowse：Lookup failed with {response.status_code}: {response.text}")
                return False
            
            data = response.json()
            if not data or len(data.keys()) == 0:
                return False

            return True
    except:
        print(f"{url[:64]}LookupGoogleSafeBrowse Exception")
        return False
    
    

async def lookupAlienVault(url):
    try:
        headers = {
            "X-OTX-API-KEY": os.getenv("ALIENVAULT_KEY"),
        }

        lookup_url = f"{os.getenv('ALIENVAULT_LOOKUP')}{url}/general"

        async with aiohttp.ClientSession() as session:
            async with session.get(lookup_url, headers=headers) as response:
                data = await response.json()

                if "error" in data:
                    return False

                pulse_count = data.get("pulse_info", {}).get("count", 0)
                return pulse_count > 0    
    except:
        print(f"{url[:64]}lookupAlienVault Exception")
        return False
        


async def lookupYandexSafeBrowsing(url):
    try:
        body = {
            "client": {
                "clientId": "captcha-honeypot",
                "clientVersion": "1.0.0"
            },
            "threatInfo": {
                "threatTypes": ["MALWARE", "SOCIAL_ENGINEERING"],
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}]
            }
        }

        headers = {"Content-Type": "application/json"}
        api_url = f"{os.getenv('YANDEX_SAFE_BROWSING_API')}?key={os.getenv('YANDEX_SAFE_BROWSING_KEY')}"
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, headers=headers, json=body) as response:
                data = await response.json()
                key_count = len(data.keys())
                return key_count > 0
    except:
        print(f"{url[:64]}lookupYandexSafeBrowsing Exception")
        return False




     
   
        
  
async def nohup_poll():
    tol_round = 0
    while True:
        index = 0
        exp_name_list = ['field_charcnn_phishintention']
        current_time = datetime.now()
        last_time = current_time - timedelta(days=7)

        query = {
            "first_lookup_time": {"$gte": last_time},
        }

        for exp_name in exp_name_list:
            collection = db[exp_name + "_blacklist"]
            results = collection.find(query)

            for result in results:
                update_fields = {}
                time_now = datetime.now()

                if "googlesafebrowse_in_blacklist" not in result:
                    googlesafebrowse_lookup = await lookupGoogleSafeBrowse(result["url"], API_ADDR)
                    update_fields["googlesafebrowse_lookup"] = time_now
                    if googlesafebrowse_lookup:
                        update_fields["googlesafebrowse_in_blacklist"] = time_now

                if "yandexsafebrowse_in_blacklist" not in result:
                    yandexsafebrowse_lookup = await lookupYandexSafeBrowsing(result["url"])
                    update_fields["yandexsafebrowse_lookup"] = time_now
                    if yandexsafebrowse_lookup:
                        update_fields["yandexsafebrowse_in_blacklist"] = time_now

                if "alienvault_in_blacklist" not in result:
                    alienvault_lookup = await lookupAlienVault(result["url"])
                    update_fields["alienvault_lookup"] = time_now
                    if alienvault_lookup:
                        update_fields["alienvault_in_blacklist"] = time_now

                # update the collection only if new fields exist
                if update_fields:
                    collection.update_one(
                        {"_id": result["_id"]},
                        {"$set": update_fields}
                    ) 
                index+=1
                print(tol_round,index)

        

if __name__ == "__main__":
    asyncio.run(nohup_poll())
    
