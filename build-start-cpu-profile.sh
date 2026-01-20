#!/bin/bash


sudo docker compose --profile test down
sleep 1
sudo docker compose --profile cpu build --no-cache
sleep 1
sudo docker cmopose --profile cpu up -d
echo Complete!

