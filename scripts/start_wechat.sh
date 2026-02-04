#!/bin/bash

# 配置参数（适配nohup启动命令）
P1_NAME="python main.py"           # Python进程匹配关键字（完整命令更精准）
P1_DIR="/root/py_wegram"           # main.py所在目录
P1_CMD="nohup python main.py >/dev/null 2>nohup.out &"  # 进程1启动命令

P2_NAME="wechat_linux"               # 二进制程序名（pgrep匹配关键字）
P2_DIR="/root/wechat861_bin"         # 二进制程序所在目录
P2_CMD="nohup ./wechat_linux >/dev/null 2>nohup.out &"  # 进程2启动命令

SLEEP=5                            # 启动后等待时间
#CURL_URL="http://127.0.0.1:8061/api/Login/AutoHeartBeat"
#CURL_DATA='{"wxid": "lngwu11"}'


# 启动进程函数（适配nohup命令）
start_proc() {
    local name=$1 dir=$2 cmd=$3
    # 用pgrep -f匹配完整命令行，确保nohup启动的进程能被检测到
    if ! pgrep -f "$name" >/dev/null; then
        echo "[$(date +'%T')] 启动 $name..."
        if [ -d "$dir" ]; then
            cd "$dir" || { echo "[$(date +'%T')] 无法进入目录 $dir"; return 1; } # 启动成功返回1
            eval $cmd  # 用eval执行带重定向的nohup命令
            sleep $SLEEP
        else
            echo "[$(date +'%T')] 目录 $dir 不存在"
        fi
    else
        echo "[$(date +'%T')] $name 已运行"
    fi
    return 0 # 未启动返回0
}

# 发送POST请求函数
send_post() {
    echo "[$(date +'%T')] 发送开启自动心跳请求..."
    curl -s -X POST -H "Content-Type: application/json" -d "$1" "$2" >/dev/null && \
    echo "[$(date +'%T')] 开启成功" || echo "[$(date +'%T')] 开启失败"
}

# 主流程：进程2启动后发送POST
start_proc "$P1_NAME" "$P1_DIR" "$P1_CMD"  # 进程1正常启动，不影响POST
#start_proc "$P2_NAME" "$P2_DIR" "$P2_CMD" && p2_started=$?  # 获取进程2启动状态
start_proc "$P2_NAME" "$P2_DIR" "$P2_CMD"  # 获取进程2启动状态
# 仅当进程2本次启动成功（返回1），才执行POST
#[ $p2_started -eq 1 ] && send_post "$CURL_DATA" "$CURL_URL"

while true; do
    sleep $SLEEP	
done
