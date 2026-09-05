#!/bin/bash
HOSTS=(10.17.5.141 10.17.5.146 10.17.5.154 10.17.5.160
        10.17.5.203 10.17.5.207 10.17.5.217 10.17.10.67)

# HOSTS=(10.17.10.67)

EXP=glm51_eval_20260716_to4h_ccv4
N=${#HOSTS[@]}
P=7

for i in "${!HOSTS[@]}"; do
  ssh -n "${HOSTS[$i]}" "cd /gpfsprd/jt_kunlun/2ab867e449cf41f1a037ff3c532f1bb5/data/filestorage/zhangyuyao/cybergym/glm_5_1_scripts/distribute_scripts && ./start_poc_server.sh $EXP" &
done
wait