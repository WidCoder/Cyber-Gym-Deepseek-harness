1. 修改 llm_master.txt 填写用于评测服务的节点IP文件
2. 首次部署：bash dis_load_image.sh 加载docker镜像
3. 启动评测：bash dis_launch_all.sh
4. 观察日志，确认worker正常启动
5. 评测跑完：运行print_result.py得到指标 + 重跑任务列表
6. 需要重跑：传入生成的rerun题目文件，执行新一轮评测
7. 任务结束/异常：bash dis_stop_all.sh 清理集群进程