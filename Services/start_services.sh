#!/bin/bash
cd /mnt/e/Work/FiberMaintain/Services
pkill -9 topology_service 2>/dev/null
pkill -9 fiber_maint_service 2>/dev/null
pkill -9 api_gateway 2>/dev/null
pkill -9 board_service 2>/dev/null
sleep 2

nohup build/src/board_service/board_service > /tmp/board.log 2>&1 &
sleep 2
nohup build/src/topology_service/topology_service > /tmp/topo.log 2>&1 &
sleep 2
nohup build/src/fiber_maint_service/fiber_maint_service > /tmp/fiber.log 2>&1 &
sleep 2
nohup build/src/api_gateway/api_gateway > /tmp/gw.log 2>&1 &
sleep 3

echo "=== Services started ==="
curl -s --max-time 5 http://localhost:8080/api/v1/topology/fibers/77/scene
