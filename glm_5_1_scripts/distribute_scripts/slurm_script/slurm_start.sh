#!/bin/bash
#SBATCH --job-name=glm51_eval
#SBATCH --nodes=8
#SBATCH --ntasks=8
#SBATCH --ntasks-per-node=1
#SBATCH --nodelist=SHLG-PSC-ZS3F1-SPOD-PM-OS07-CLUSTER-ZS-[333,338,346,352,363,367,377,931]
#SBATCH --output=slurm_logs/%x_%j_node%t.log

EXP_NAME=glm51_eval_20260710_to7200
TOTAL=10

cd /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/glm_5_1_scripts/distribute_scripts

srun bash -c './start_all_one_node.sh $SLURM_PROCID $SLURM_NNODES '"$TOTAL $EXP_NAME"