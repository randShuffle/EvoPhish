import asyncio
import json
from datetime import datetime
import websockets
from confluent_kafka import Producer
from common import KAFKA_BROKER,WS_URL



producer = Producer({'bootstrap.servers': KAFKA_BROKER})


def delivery_report(err, msg):
    if err is not None:
        print(f"[Kafka Error] Delivery failed: {err}")
        

def sync_send_to_kafka(domain: str):
    producer.produce("certstream-raw-domains", value=domain.encode('utf-8'), callback=delivery_report)
    producer.poll(0)


async def receive_domains():
    i = 0
    loop = asyncio.get_running_loop()

    while True:
        start = datetime.now()
        try:
            async with websockets.connect(WS_URL, ping_interval=30) as websocket:
                print(f"[Connected] Listening on {WS_URL}")
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        domain_list = data.get("data", {}).get("leaf_cert", {}).get("all_domains", [])
                        if not domain_list:
                            continue
                        
                        cur_set = set()
                        for domain in domain_list:
                            if domain.startswith("*."):
                                domain = domain[2:]
                            if domain not in cur_set:
                                cur_set.add(domain)
                                i += 1
                                if i % 5000 == 0:
                                    cur = datetime.now()
                                    print(cur-start)
                                    start = cur
                                await loop.run_in_executor(None, sync_send_to_kafka, domain)

                    except Exception as e:
                        print("[Parse Error]:", e)
        except Exception as e:
            print(f"[Disconnected] Error: {e}, reconnecting in 5 seconds...")
            await asyncio.sleep(5)



async def main():
    try:
        await receive_domains()
    except KeyboardInterrupt:
        print("👋 Interrupted by user.")
    finally:
        print("🚪 Flushing Kafka messages before exit...")
        producer.flush()


if __name__ == "__main__":
    asyncio.run(main())
