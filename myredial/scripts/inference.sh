#!/bin/bash

dataset=$1
model=$2
cuda=$3

gpu_ids=(${cuda//,/ })
CUDA_VISIBLE_DEVICES=$cuda python -m torch.distributed.launch --nproc_per_node=${#gpu_ids[@]} --master_addr 127.0.0.1 --master_port 29409 inference.py \
    --dataset $dataset \
    --model $model \
    --nums ${#gpu_ids[@]} \
    --work_mode gray-one2many \
    --cut_size 1000000 \
    --pool_size 256
