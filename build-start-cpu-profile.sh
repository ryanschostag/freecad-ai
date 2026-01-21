#!/bin/bash


docker compose --profile test down
sleep 1
docker compose --profile cpu build --no-cache
sleep 1
docker compose --profile cpu up -d
echo Complete!

