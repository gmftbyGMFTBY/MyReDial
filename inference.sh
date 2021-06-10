#!/bin/bash

dataset=$1
model=$2
cuda=$3

gpu_ids=(${cuda//,/ })
CUDA_VISIBLE_DEVICES=$cuda python -m torch.distributed.launch --nproc_per_node=${#gpu_ids[@]} --master_addr 127.0.0.1 --master_port 29400 inference.py \
    --dataset $dataset \
    --model $model

# reconstruct
python searcher.py \
    --dataset $dataset \
    --nums ${#gpu_ids[@]}