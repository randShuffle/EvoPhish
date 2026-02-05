#!/bin/bash

# EXP_NAMES=(
#   "baseline_phishintention"
#   "ablation_charcnn_phishintention"
#   "ablation_fasttext_phishintention"
#   "ablation_tfidf_phishintention"
#   "ablation_fasttext_phishpedia"
#   "ablation_charcnn_phishpedia"
#   "ablation_tfidf_phishpedia"
#   "back_audit"
# )

EXP_NAMES=(
  "baseline_phishintention"
  "field_charcnn_phishintention"
  "field_no_priority_charcnn_phishintention"
  "field_no_priority_no_retrain_charcnn_phishintention"
)



while true
do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restarting screenshot jobs..."

  ps -u $USER -o pid,cmd | grep screenshot.py | grep -v grep | awk '{print $1}' | xargs -r kill -9
  ps -u $USER -o pid,cmd | grep ms-playwright | grep -v grep | awk '{print $1}' | xargs -r kill -9


  for EXP_NAME in "${EXP_NAMES[@]}"
  do
    echo "Starting screenshot.py --exp_name $EXP_NAME"
    nohup python ./screenshot.py --exp_name "$EXP_NAME" >/dev/null 2>&1 &
  done

  # restart every 30 minutes due to playwright memory cache issue
  sleep 1800
done

