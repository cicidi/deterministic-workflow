# Hetzner Cloud + Jenkins CI/CD — Example Infrastructure

This is an **example** — not part of the generic framework spec. Move and adapt for your project.

## Terraform

```hcl
terraform {
  required_providers {
    hcloud = { source = "hetznercloud/hcloud" }
  }
}

provider "hcloud" { token = var.hcloud_token }

resource "hcloud_server" "jenkins" {
  name        = "{project}-jenkins"
  server_type = "cx32"
  image       = "ubuntu-24.04"
  location    = "ash"
  user_data   = file("./jenkins-cloud-init.yaml")
}

resource "hcloud_firewall" "jenkins" {
  name = "jenkins-fw"
  rule {
    direction  = "in"; protocol = "tcp"; port = "8080"
    source_ips = ["0.0.0.0/0"]
  }
  rule {
    direction  = "in"; protocol = "tcp"; port = "22"
    source_ips = ["YOUR_IP/32"]
  }
}

output "jenkins_url" { value = "http://${hcloud_server.jenkins.ipv4_address}:8080" }
```

## Cloud-Init

```yaml
#cloud-config
packages: [openjdk-17-jre-headless, docker.io, python3-pip, git]
runcmd:
  - wget -q -O /usr/share/keyrings/jenkins-keyring.asc https://pkg.jenkins.io/debian-stable/jenkins.io-2023.key
  - echo "deb [signed-by=/usr/share/keyrings/jenkins-keyring.asc] https://pkg.jenkins.io/debian-stable binary/" > /etc/apt/sources.list.d/jenkins.list
  - apt-get update && apt-get install -y jenkins
  - systemctl enable --now jenkins docker
  - usermod -aG docker jenkins
```

## Jenkinsfile

```groovy
pipeline {
    agent any
    triggers { githubPush() }
    stages {
        stage('Lint')  { steps { sh 'ruff check src/' } }
        stage('T1')    { steps { sh 'rm -f *.db && pytest tests/tier1/ -q' } }
        stage('T2')    { steps { script { if (env.LLM_API_KEY) { sh 'rm -f mfangdai_t2.db && pytest tests/tier2/ -q' } } } }
        stage('T3')    { steps { script { if (env.LLM_API_KEY) { sh 'rm -f mfangdai_t3.db && pytest tests/tier3/ -q' } } } }
        stage('Build') { steps { sh 'docker build -t {project}:${GIT_COMMIT[:8]} .' } }
        stage('Deploy Dev') { steps { sh 'docker compose -f docker-compose.dev.yml up -d' } }
    }
}
```
