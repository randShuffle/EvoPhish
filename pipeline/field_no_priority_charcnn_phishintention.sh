while true
do
  python ./model_update.py --exp_name field_no_priority_charcnn_phishintention
  ps -u $USER -o pid,cmd | grep model_consumer.py | grep field_no_priority_charcnn_phishintention | grep -v grep | awk '{print $1}' | xargs -r kill -9
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pipeline Ready to restart..."
  nohup python ./model_consumer.py --exp_name field_no_priority_charcnn_phishintention >/dev/null 2>&1 &
  # retrain every 2 hours
  sleep 7200
done