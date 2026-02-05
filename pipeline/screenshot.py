import sys
import os

sys.stderr = open(os.devnull, 'w')
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
logging.getLogger("uvicorn.access").disabled = True
import uvicorn
import argparse
from common import EXP_NAMES,SCREENSHOT_BASIC_PORT
import uuid
from Crypto.Cipher import AES
import base64
import argparse
import time


key = b'ThisIsA16ByteKey'
def encrypt_filename(name):
    cipher = AES.new(key, AES.MODE_ECB)
    data = name.encode('utf-8')
    padding_len = 16 - len(data) % 16
    data += bytes([padding_len]) * padding_len
    encrypted = cipher.encrypt(data)
    return base64.urlsafe_b64encode(encrypted).decode()



PROXY_SERVER = "http://127.0.0.1:7890" 

PHISHPEDIA_API_URL = 'http://localhost:5000/analyze'
PHISHINTENTION_API_URL = 'http://localhost:5001/analyze'
MAX_CONCURRENT = 20 
headers = {
    "User-Agent":'Mozilla/5.0 (Linux; Android 6.0; Nexus 5 Build/MRA58N) AppleWebKit/5d7.36 (KHTML, like Gecko) Chrome/138.0.0.0 Mobile Safari/537.36'
}

semaphore = asyncio.Semaphore(MAX_CONCURRENT)

class ScreenshotRequest(BaseModel):
    ori_domain: str
    domain_classifier :int
    domain_classifier_prob:float
    is_typo:int
    exp_name:str
    model_version:int
    timestamp:str
    ood_score:float
    is_ood:int
    



@asynccontextmanager
async def lifespan(app: FastAPI):
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
    )
    app.state.playwright = playwright
    app.state.browser = browser
   
    try:
        yield
    finally:
        try:
            pass
        except asyncio.CancelledError:
            pass

        await browser.close()
        await playwright.stop()
       


app = FastAPI(lifespan=lifespan)




async def can_access_url(url: str,exp_name) -> bool:
    try:
        timeout=aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(headers=headers,timeout=timeout) as session:
            async with session.head(url, allow_redirects=True) as response:
                return response.status < 400
    except Exception as e:
        return False

    


async def upload_screenshot(payload:dict):
    exp_name = payload["exp_name"]
    ori_domain = payload["ori_domain"]
    screenshot_path = payload["screenshot_path"]
    payload["screenshot_path"] = f"../{screenshot_path}"
    if "phishintention" in exp_name or "phishintel" in exp_name:
        API_URL = PHISHINTENTION_API_URL
    else:
        API_URL = PHISHPEDIA_API_URL
        
  
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=payload) as response:
                pass
    except Exception as e:
        print(f"[Upload] failure：{ori_domain}")


async def process_screenshot(browser,**extra_payload):
    exp_name = extra_payload["exp_name"]
    ori_domain = extra_payload["ori_domain"]
    url = "https://"+ori_domain
    real_url = None
    async with semaphore:
        pre_filter = await can_access_url(url,exp_name)
        if pre_filter:
            try:
                context = None
                context = await browser.new_context()
                page = await context.new_page()
                await page.goto(url, timeout=10000)  
                await asyncio.sleep(3)
 
                real_url = page.url
                
                if exp_name in ["phishing_catcher","streamingphish","baseline_phishintel"]:
                    today = datetime.now().strftime("%Y-%m-%d") 
                    folder_path = f"../phish_pictures/{exp_name}/{today}"
                    os.makedirs(folder_path, exist_ok=True)
                    screenshot_path = f"../phish_pictures/{exp_name}/{today}/{encrypt_filename(ori_domain)}.png"
                    await page.screenshot(path=screenshot_path)
                    return real_url
                else:
                    unique_id = str(uuid.uuid4())
                    screenshot_path = f"../tmp/{ori_domain}_{unique_id}.png"
                    await page.screenshot(path=screenshot_path)
                    html_path = f"../tmp/{ori_domain}_{unique_id}.txt"
                if "phishintention" in exp_name or "phishintel" in exp_name:
                    html_content = await page.content()
                    with open(html_path, "w", encoding="utf-8") as f:
                        f.write(html_content)
                
                print(f"{exp_name}***[Screenshot] finish：{url}")
                extra_payload["url"] = real_url
                extra_payload["screenshot_path"] = screenshot_path
                await upload_screenshot(extra_payload)
            except Exception as e:
                real_url = None
            finally:
                try:
                    if context:
                        await context.close()
                    if real_url==None:
                        if os.path.exists(screenshot_path):
                            os.remove(screenshot_path)
                        if os.path.exists(html_path):
                            os.remove(html_path)
                except:
                    pass

        else:
            print(f'{exp_name}***{url}=>filtered!')
    return real_url
   
        
        
@app.post("/screenshot")
async def screenshot(req: ScreenshotRequest, request: Request):
    if semaphore.locked():
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"status": "busy", "domain": req.ori_domain}
        )
    else:
        browser = request.app.state.browser
       
        asyncio.create_task(process_screenshot(browser,
                                               ori_domain=req.ori_domain,
                                               domain_classifier=req.domain_classifier,
                                               domain_classifier_prob=req.domain_classifier_prob,
                                               is_typo=req.is_typo,
                                               exp_name=req.exp_name,
                                               model_version=req.model_version,
                                               timestamp=req.timestamp,
                                               ood_score = req.ood_score,
                                               is_ood = req.is_ood))
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"status": "queued", "domain": req.ori_domain}
        )
        
  

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
    "--exp_name",
    type=str,
    choices=EXP_NAMES,
    required=True,
    help="Experiment name. Must be one of: " + ", ".join(EXP_NAMES)
)
    args = parser.parse_args()
    
    port = SCREENSHOT_BASIC_PORT + EXP_NAMES.index(args.exp_name)
    
    print(f"Assigned port for experiment '{args.exp_name}': {port}")

    uvicorn.run("screenshot:app", host="0.0.0.0", port=port, reload=False, log_config=None)
