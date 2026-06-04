# Security Skill Pack — 25 Commands

```yaml
# File Permissions
- intent: "make {{file}} executable"
  command: "chmod +x {{file}}"
  tags: [security, permissions, executable]

- intent: "set file permissions to {{mode}}"
  command: "chmod {{mode}} {{file}}"
  tags: [security, permissions]

- intent: "recursively set directory permissions"
  command: "chmod -R {{mode}} {{directory}}"
  tags: [security, permissions, recursive]

- intent: "change file owner to {{user}}"
  command: "sudo chown {{user}} {{file}}"
  tags: [security, ownership]

- intent: "change file owner and group"
  command: "sudo chown {{user}}:{{group}} {{file}}"
  tags: [security, ownership, group]

- intent: "recursively change directory owner"
  command: "sudo chown -R {{user}}:{{group}} {{directory}}"
  tags: [security, ownership, recursive]

- intent: "show file permissions {{file}}"
  command: "ls -la {{file}}"
  tags: [security, permissions, list]

- intent: "show current umask"
  command: "umask"
  tags: [security, umask]

- intent: "set umask to {{value}}"
  command: "umask {{value}}"
  tags: [security, umask, set]

- intent: "find files with suid bit set"
  command: "find / -perm -4000 -type f 2>/dev/null"
  tags: [security, permissions, suid, audit]

- intent: "find world writable files in {{dir}}"
  command: "find {{dir}} -perm -o+w -type f"
  tags: [security, permissions, audit]

# SSH
- intent: "generate ssh key"
  command: "ssh-keygen -t ed25519 -C \"{{comment}}\""
  tags: [security, ssh, keygen]

- intent: "generate ssh key with specific name"
  command: "ssh-keygen -t ed25519 -f ~/.ssh/{{name}} -C \"{{comment}}\""
  tags: [security, ssh, keygen]

- intent: "copy ssh key to {{host}}"
  command: "ssh-copy-id {{user}}@{{host}}"
  tags: [security, ssh, copy]

- intent: "show ssh config"
  command: "cat ~/.ssh/config"
  tags: [security, ssh, config]

- intent: "list ssh keys"
  command: "ls -la ~/.ssh/"
  tags: [security, ssh, list]

- intent: "test ssh connection to {{host}}"
  command: "ssh -T {{user}}@{{host}}"
  tags: [security, ssh, test]

- intent: "show ssh key fingerprint"
  command: "ssh-keygen -lf ~/.ssh/{{key}}.pub"
  tags: [security, ssh, fingerprint]

- intent: "show ssh agent keys"
  command: "ssh-add -l"
  tags: [security, ssh, agent]

# SSL/TLS
- intent: "check ssl certificate for {{domain}}"
  command: "echo | openssl s_client -connect {{domain}}:443 -servername {{domain}} 2>/dev/null | openssl x509 -noout -dates -subject"
  tags: [security, ssl, certificate, check]

- intent: "show certificate chain for {{domain}}"
  command: "echo | openssl s_client -showcerts -connect {{domain}}:443 2>/dev/null"
  tags: [security, ssl, chain]

- intent: "generate self signed certificate"
  command: "openssl req -x509 -newkey rsa:4096 -keyout {{name}}.key -out {{name}}.crt -days 365 -nodes -subj \"/CN={{domain}}\""
  tags: [security, ssl, generate]

- intent: "verify certificate matches key"
  command: "diff <(openssl x509 -noout -modulus -in {{cert}}) <(openssl rsa -noout -modulus -in {{key}})"
  tags: [security, ssl, verify]

- intent: "renew certificates with certbot"
  command: "sudo certbot renew"
  tags: [security, certbot, renew]

- intent: "get certificate for {{domain}}"
  command: "sudo certbot certonly --nginx -d {{domain}}"
  tags: [security, certbot, obtain]

- intent: "show certbot certificates"
  command: "sudo certbot certificates"
  tags: [security, certbot, list]

# Firewall
- intent: "show firewall status"
  command: "sudo ufw status verbose"
  tags: [security, firewall, ufw, status]

- intent: "enable firewall"
  command: "sudo ufw enable"
  tags: [security, firewall, ufw, enable]

- intent: "allow port {{port}}"
  command: "sudo ufw allow {{port}}"
  tags: [security, firewall, ufw, allow]

- intent: "allow port {{port}} from {{ip}}"
  command: "sudo ufw allow from {{ip}} to any port {{port}}"
  tags: [security, firewall, ufw, allow]

- intent: "deny port {{port}}"
  command: "sudo ufw deny {{port}}"
  tags: [security, firewall, ufw, deny]

- intent: "show iptables rules"
  command: "sudo iptables -L -n -v"
  tags: [security, firewall, iptables, list]

- intent: "block ip address {{ip}}"
  command: "sudo iptables -A INPUT -s {{ip}} -j DROP"
  tags: [security, firewall, iptables, block]

- intent: "show listening ports with process"
  command: "sudo ss -tlnp"
  tags: [security, ports, audit]
```
