#!/bin/bash

# EXP_NAMES=(
#   "ablation_fasttext_phishpedia"
#   "ablation_charcnn_phishpedia"
#   "ablation_tfidf_phishpedia"
#   "baseline_phishintention"
#   "ablation_charcnn_phishintention"
#   "ablation_fasttext_phishintention"
#   "ablation_tfidf_phishintention"
# )

EXP_NAMES=(
  "baseline_phishintention"
  "field_charcnn_phishintention"
  "field_no_priority_charcnn_phishintention"
  "field_no_priority_no_retrain_charcnn_phishintention"
)



ps -u $USER -o pid,cmd | grep redis_consumer.py | grep -v grep | awk '{print $1}' | xargs -r kill -9
for EXP_NAME in "${EXP_NAMES[@]}"
do
echo "Starting redis_consumer.py --exp_name $EXP_NAME"
nohup python ./redis_consumer.py --exp_name "$EXP_NAME" >/dev/null 2>&1 &
done


