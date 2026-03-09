#!/bin/bash
set -euo pipefail


down_file="down.log"
build_file="build.log"
up_file="up.log"


time docker compose --profile test down 2>&1 | tee $down_file
sleep 1
time docker compose --profile cpu build --no-cache 2>&1 | tee $build_file
sleep 1
time docker compose --profile cpu up -d 2>&1 | tee $up_file

echo Complete!

