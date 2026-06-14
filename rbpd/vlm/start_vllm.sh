#!/bin/bash
export CUDA_VISIBLE_DEVICES=4,5,6,7
export NCCL_P2P_DISABLE=1
export NCCL_IB_DISABLE=1
# Substitute with your path
MODEL_PATH="Qwen3-VL-32B-Instruct"

ARGS="--max-model-len 32768 \
--trust-remote-code \
--gpu-memory-utilization 0.7 \
--host 0.0.0.0"
# start vllm server
vllm serve $MODEL_PATH --port 7000 --tensor-parallel-size 4 $ARGS

