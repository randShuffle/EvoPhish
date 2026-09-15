while true
do
  python ./model_update.py --exp_name ablation_charcnn_phishintention_vlm_r90
  ps -u $USER -o pid,cmd | grep model_consumer.py | grep ablation_charcnn_phishintention_vlm_r90 | grep -v grep | awk '{print $1}' | xargs -r kill -9
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pipeline Ready to restart..."
  nohup python ./model_consumer.py --exp_name ablation_charcnn_phishintention_vlm_r90 >/dev/null 2>&1 &
  # retrain every 2 hours
  sleep 7200
done