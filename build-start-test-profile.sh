#!/bin/bash


docker compose --profile test down
sleep 1
docker compose -f docker-compose.yml -f docker-compose.test-override.yml --profile test build --no-cache
sleep 1
docker cmopose --profile test up -d
sleep 1
docker compose --profile test run --rm test-runner 
echo Complete!

