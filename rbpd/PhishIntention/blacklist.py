import sys
import os
from pymongo import MongoClient
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright
import asyncio
from fastapi.responses import JSONResponse
from fastapi import status
import aiohttp
import logging
from datetime import datetime, timezone, timedelta
import uvicorn
import argparse
import httpx
import time
import json
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
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


class BlacklistRequest(BaseModel):
    exp_name: str
    ori_domain: str
    url: str
    pred_target:str
    



@asynccontextmanager
async def lifespan(app: FastAPI):

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
    )

    app.state.playwright = playwright
    app.state.browser = browser
    #poll_task = asyncio.create_task(nohup_poll())
   
    try:
        yield
    finally:
        #poll_task.cancel()
        try:
            pass
            #await poll_task
        except asyncio.CancelledError:
            pass

        await browser.close()
        await playwright.stop()
       


app = FastAPI(lifespan=lifespan)




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
        # print(f"LookupGoogleSafeBrowse Exception")
        return False
    
    

async def lookupAlienVault(url):
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


async def lookupYandexSafeBrowsing(url):
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


async def toAlienVault(url):
    body = {
        "url": url,
        "tlp": "white"
    }
    headers = {
        "X-OTX-API-KEY": os.getenv("ALIENVAULT_KEY"),
        "Content-Type": "application/json"
    }
    api_url = os.getenv("ALIENVAULT_API")
    async with aiohttp.ClientSession() as session:
        async with session.post(api_url, headers=headers, data=json.dumps(body)) as response:
            data = await response.json()
            return data.get("status") == "ok"





async def submit(browser, url, pred_target,submit_wait=3, timeout=5000):
    try:
        context = None
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(os.getenv('GOOGLE_REPORT_URL'), timeout=10000)  
        await page.click("#mat-select-0")
        await page.wait_for_selector("mat-option")
        options = await page.query_selector_all("mat-option")
        for option in options:
            text = (await option.text_content() or "").strip()
            if text == "This page is not safe":
                await option.click()
                break
        url_input = "#mat-input-0"
        await page.wait_for_selector(url_input, state="visible")
        await page.fill(url_input, url)

        detail_input = "#mat-input-1"
        await page.wait_for_selector(detail_input, state="visible")
        await page.fill(detail_input, f"This website is imitating {pred_target} (including its content and logo) and has the intention of stealing personal information. In addition, its domain name is different from {pred_target}’s official domain, so it is a phishing site.")
        await page.click(".form-submit-button")
        await asyncio.sleep(submit_wait)
        try: 
            await page.wait_for_selector("text=Submission was successful.", timeout=timeout)
        except TimeoutError:
            print("submit fail.")
            await context.close()
            return False
        
        await context.close()
        print("submit success.")
        return True
    except Exception as e:
        try:
            print("submit fail.")
            if context:
                await context.close()
        except:
            pass




async def first_check(exp_name,domain,url,pred_target,browser):
    collection = db[exp_name+"_blacklist"]
    googlesafebrowse_lookup = await lookupGoogleSafeBrowse(url, API_ADDR)
    yandexsafebrowse_lookup = await lookupYandexSafeBrowsing(url)
    alienvault_lookup = await lookupAlienVault(url)
    time_now = datetime.now()
    log = {"domain":domain,"url": url,"pred_target":pred_target,"first_lookup_time": time_now}
    log["googlesafebrowse_lookup"] = time_now
    log["yandexsafebrowse_lookup"] = time_now
    log["alienvault_lookup"] = time_now
    
    if googlesafebrowse_lookup:
        log["googlesafebrowse_in_blacklist"] = time_now
    # else:
    #     # URL does not exist, submit URL
    #     # logging.info(f'[LOOKUP MISS]: No match for {url}')
    #     submission_status = await submit(browser, url,pred_target)

    #     if not submission_status:
    #         #logging.error("[SUBMIT ERROR] Submission confirmation timed out.")
    #         log["submit_googlesafebrowse"] = False
    #         collection.insert_one(log)
    #     else:
    #         # logging.info(f"[SUBMIT SUCCESS] Submission for {url} was successful.")
    #         log["submit_googlesafebrowse"] = True
    #         collection.insert_one(log)
        
    if yandexsafebrowse_lookup:
        log["yandexsafebrowse_in_blacklist"] = time_now
        
    if alienvault_lookup:
        log["alienvault_in_blacklist"] = time_now
    # else:
    #     await toAlienVault(url)
        
    collection.insert_one(log)
     
    # # URL does not exist, submit URL
    # # logging.info(f'[LOOKUP MISS]: No match for {url}')
    # submission_status = await submit(browser, url,pred_target)

    # if not submission_status:
    #     logging.error("[SUBMIT ERROR] Submission confirmation timed out.")
    #     log = {"domain":domain,"url": url,"pred_target":pred_target,"first_lookup_time": datetime.now(),"submit": False}
    #     collection.insert_one(log)
    # else:
    #     logging.info(f"[SUBMIT SUCCESS] Submission for {url} was successful.")
    #     log = {"domain":domain,"url": url,"pred_target":pred_target,"first_lookup_time": datetime.now(),"submit": True}
    #     collection.insert_one(log)


        
@app.post("/blacklist")
async def blacklist(req: BlacklistRequest, request: Request):
    browser = request.app.state.browser
    exp_name = req.exp_name
    domain = req.ori_domain
    url = req.url
    pred_target = req.pred_target
    asyncio.create_task(first_check(exp_name, domain, url,pred_target, browser))
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "queued"}
    )
        
  
  
async def nohup_poll():
    tol_round = 0
    while True:
        index = 0
        start_time = datetime.now()
        exp_name_list = ['field_charcnn_phishintention']
        current_time = datetime.now()
        last_time = current_time - timedelta(days=14)

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

        end_time = datetime.now()
     
        elapsed = (end_time - start_time).total_seconds()
        sleep_time = max(0, 60*60 - elapsed)
        tol_round+=1
        # print(f"[POLL] Polling took {elapsed} seconds, sleeping for {sleep_time} seconds.")
        # await asyncio.sleep(sleep_time)
            
        

if __name__ == "__main__":

    uvicorn.run("blacklist:app", host="0.0.0.0", port=SERVICE_PORT, reload=False)
