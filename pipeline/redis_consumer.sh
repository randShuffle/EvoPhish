#!/bin/bash

EXP_NAMES=(
  "ablation_charcnn_phishintention_vlm"
)



ps -u $USER -o pid,cmd | grep redis_consumer.py | grep -v grep | awk '{print $1}' | xargs -r kill -9
for EXP_NAME in "${EXP_NAMES[@]}"
do
echo "Starting redis_consumer.py --exp_name $EXP_NAME"
nohup python ./redis_consumer.py --exp_name "$EXP_NAME" >/dev/null 2>&1 &
done


