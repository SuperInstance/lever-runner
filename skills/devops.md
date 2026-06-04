# DevOps Skill Pack — 50 Commands

```yaml
# Docker
- intent: "list running containers"
  command: "docker ps"
  tags: [docker, containers, list]

- intent: "list all containers including stopped"
  command: "docker ps -a"
  tags: [docker, containers, list]

- intent: "show logs for {{container}}"
  command: "docker logs --tail 100 {{container}}"
  tags: [docker, logs]

- intent: "show live logs for {{container}}"
  command: "docker logs -f --tail 50 {{container}}"
  tags: [docker, logs, follow]

- intent: "execute command in {{container}}"
  command: "docker exec -it {{container}} {{cmd}}"
  tags: [docker, exec]

- intent: "start docker compose services"
  command: "docker compose up -d"
  tags: [docker, compose, start]

- intent: "stop docker compose services"
  command: "docker compose down"
  tags: [docker, compose, stop]

- intent: "restart docker compose services"
  command: "docker compose restart"
  tags: [docker, compose, restart]

- intent: "show docker compose service status"
  command: "docker compose ps"
  tags: [docker, compose, status]

- intent: "pull docker compose images"
  command: "docker compose pull"
  tags: [docker, compose, update]

- intent: "inspect docker {{resource}}"
  command: "docker inspect {{resource}}"
  tags: [docker, inspect]

- intent: "show docker disk usage"
  command: "docker system df"
  tags: [docker, disk]

- intent: "remove unused docker resources"
  command: "docker system prune -f"
  tags: [docker, cleanup]

- intent: "remove all unused docker volumes"
  command: "docker volume prune -f"
  tags: [docker, cleanup, volumes]

- intent: "show docker images"
  command: "docker images"
  tags: [docker, images, list]

- intent: "remove dangling docker images"
  command: "docker image prune -f"
  tags: [docker, cleanup, images]

- intent: "show docker container stats"
  command: "docker stats --no-stream"
  tags: [docker, stats, monitoring]

- intent: "build docker image from {{path}}"
  command: "docker build -t {{name}} {{path}}"
  tags: [docker, build]

- intent: "run docker image {{image}}"
  command: "docker run -d --name {{name}} {{image}}"
  tags: [docker, run]

- intent: "stop docker container {{container}}"
  command: "docker stop {{container}}"
  tags: [docker, stop]

- intent: "remove docker container {{container}}"
  command: "docker rm {{container}}"
  tags: [docker, remove]

# Kubernetes
- intent: "show kubernetes pods"
  command: "kubectl get pods"
  tags: [k8s, pods, list]

- intent: "show kubernetes pods in {{namespace}}"
  command: "kubectl get pods -n {{namespace}}"
  tags: [k8s, pods, namespace]

- intent: "describe kubernetes {{resource}} {{name}}"
  command: "kubectl describe {{resource}} {{name}}"
  tags: [k8s, describe]

- intent: "show kubernetes pod logs for {{pod}}"
  command: "kubectl logs --tail 100 {{pod}}"
  tags: [k8s, logs]

- intent: "show live kubernetes pod logs for {{pod}}"
  command: "kubectl logs -f --tail 50 {{pod}}"
  tags: [k8s, logs, follow]

- intent: "port forward kubernetes {{resource}} {{name}}"
  command: "kubectl port-forward {{resource}}/{{name}} {{local_port}}:{{remote_port}}"
  tags: [k8s, port-forward]

- intent: "show kubernetes deployments"
  command: "kubectl get deployments"
  tags: [k8s, deployments, list]

- intent: "show kubernetes services"
  command: "kubectl get services"
  tags: [k8s, services, list]

- intent: "show kubernetes nodes"
  command: "kubectl get nodes"
  tags: [k8s, nodes, list]

- intent: "apply kubernetes manifest {{file}}"
  command: "kubectl apply -f {{file}}"
  tags: [k8s, apply, deploy]

- intent: "delete kubernetes resource {{type}} {{name}}"
  command: "kubectl delete {{type}} {{name}}"
  tags: [k8s, delete]

- intent: "show kubernetes events"
  command: "kubectl get events --sort-by=.lastTimestamp"
  tags: [k8s, events]

- intent: "show kubernetes namespaces"
  command: "kubectl get namespaces"
  tags: [k8s, namespaces]

# System
- intent: "check disk usage"
  command: "df -h"
  tags: [system, disk]

- intent: "check directory size {{path}}"
  command: "du -sh {{path}}"
  tags: [system, disk, size]

- intent: "show top processes by cpu"
  command: "top -b -n 1 | head -20"
  tags: [system, processes, cpu]

- intent: "show memory usage"
  command: "free -h"
  tags: [system, memory]

- intent: "list running processes"
  command: "ps aux --sort=-%mem | head -20"
  tags: [system, processes, list]

- intent: "show system uptime"
  command: "uptime"
  tags: [system, uptime]

- intent: "show system information"
  command: "uname -a"
  tags: [system, info]

- intent: "show cpu information"
  command: "lscpu | head -20"
  tags: [system, cpu, info]

- intent: "show disk partitions"
  command: "lsblk"
  tags: [system, disk, partitions]

# Network
- intent: "check http response {{url}}"
  command: "curl -sI {{url}}"
  tags: [network, http, check]

- intent: "download file from {{url}}"
  command: "curl -L -o {{output}} {{url}}"
  tags: [network, download]

- intent: "ping {{host}}"
  command: "ping -c 4 {{host}}"
  tags: [network, ping, connectivity]

- intent: "trace route to {{host}}"
  command: "traceroute -m 20 {{host}}"
  tags: [network, traceroute]

- intent: "show listening ports"
  command: "ss -tlnp"
  tags: [network, ports, listening]

- intent: "show all network connections"
  command: "ss -tunap"
  tags: [network, connections]

- intent: "lookup dns for {{domain}}"
  command: "nslookup {{domain}}"
  tags: [network, dns]

- intent: "show network interfaces"
  command: "ip addr show"
  tags: [network, interfaces]

- intent: "show routing table"
  command: "ip route show"
  tags: [network, routing]

# Process Management
- intent: "kill process {{pid}}"
  command: "kill {{pid}}"
  tags: [process, kill]

- intent: "force kill process {{pid}}"
  command: "kill -9 {{pid}}"
  tags: [process, kill, force]

- intent: "find and kill process {{name}}"
  command: "pkill -f {{name}}"
  tags: [process, kill, find]

- intent: "run command in background"
  command: "nohup {{command}} > /dev/null 2>&1 &"
  tags: [process, background]

- intent: "start service {{service}}"
  command: "sudo systemctl start {{service}}"
  tags: [systemd, start]

- intent: "stop service {{service}}"
  command: "sudo systemctl stop {{service}}"
  tags: [systemd, stop]

- intent: "restart service {{service}}"
  command: "sudo systemctl restart {{service}}"
  tags: [systemd, restart]

- intent: "show service status {{service}}"
  command: "sudo systemctl status {{service}}"
  tags: [systemd, status]

- intent: "enable service {{service}}"
  command: "sudo systemctl enable {{service}}"
  tags: [systemd, enable]

- intent: "show service logs {{service}}"
  command: "sudo journalctl -u {{service}} -n 100 --no-pager"
  tags: [systemd, logs]
```
