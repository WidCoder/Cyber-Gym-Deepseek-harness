srun --job-name=glm51_stop \
       --nodes=8 --ntasks=8 --ntasks-per-node=1 \
       --nodelist=SHLG-PSC-ZS3F1-SPOD-PM-OS07-CLUSTER-ZS-[333,338,346,352,363,367,377,931] \
       /gpfsprd/jt/2ab867e449cf41f1a037ff3c532f1bb5/chenmaojian/projects/benchmarks/cybergym-main/glm_5_1_scripts/distribute_scripts/stop_all_one_node.sh