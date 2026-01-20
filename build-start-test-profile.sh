#!/bin/bash


sudo docker compose --profile test down
sleep 1
sudo docker compose -f docker-compose.yml -f docker-compose.test-override.yml --profile test build --no-cache
sleep 1
sudo docker cmopose --profile test up -d
sleep 1
sudo docker compose --profile test run --rm test-runner | tee pytest.txt
echo Complete!

