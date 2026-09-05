#for i in {0..7}; do
#  nohup "./start_${i}.sh" > "part${i}.log" 2>&1 &
#  echo "started start_${i}.sh pid=$!"
#done
#!/usr/bin/env bash
parts=${1:-8}

mkdir -p logs pids

for ((i=0; i<parts; i++)); do
  nohup ./start_one.sh "$i" "$parts" > "logs/part${i}.log" 2>&1 &
  echo $! > "pids/part${i}.pid"
  echo "started part=$i pid=$(cat pids/part${i}.pid)"
done
