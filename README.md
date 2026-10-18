# LiftLog — Workout Tracker

LiftLog is a strength-training log: build an exercise library, log every workout set by set (weight, reps, RPE), and watch your progress with analytics usually found in premium tracking apps: **personal records, estimated one-rep max, muscle-group volume and per-exercise progress charts**.

It's also a complete DevOps capstone: the app is tested, containerised, scanned, published by CI, provisioned on AWS with Terraform, deployed to EKS with Helm through **GitOps (Argo CD)**, and monitored with Prometheus and Grafana.

Video Link: [Presentation Video](https://youtu.be/2FtC1-wvGKg)

**Contents:** [Features](#features) · [Architecture](#architecture) · [Repository layout](#repository-layout) · [Run locally](#run-locally) · [API](#api) · [CI/CD and GitOps](#cicd-and-gitops) · [Infrastructure (Terraform)](#infrastructure-terraform) · [Kubernetes / Helm](#kubernetes--helm-deployment) · [Observability](#observability-prometheus--grafana) · [Tear-down](#tear-down) · [Known issues](#known-issues-and-limitations) · [Evidence and presentation](#evidence-and-presentation)

---

## Features

| Area                    | What you can do                                                                                                                                                                |
|:------------------------|:-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Exercise library**    | 21 starter exercises (seeded by the database migration), grouped by muscle group and equipment; add, rename and delete your own. Exercises used in a workout can't be deleted. |
| **Workout logging**     | Log a session with any number of exercises and sets: weight (kg), reps and optional RPE, plus duration and notes. Edit or delete workouts later.                               |
| **History**             | Every workout with its sets per exercise, total sets and total volume (kg lifted).                                                                                             |
| **Personal records** ⭐ | Best set per exercise, ranked by **estimated 1RM** (Epley: `weight × (1 + reps / 30)`).                                                                                        |
| **Volume analytics** ⭐ | Workouts and volume over the last 7 days; volume per muscle group over the last 30 days.                                                                                       |
| **Progress charts** ⭐  | Estimated 1RM and top-set weight over time for any exercise.                                                                                                                   |

⭐ = "premium" analytics.

## Architecture

```text
Browser ──► frontend (React + Vite, served by nginx, non-root) ──/api──► backend (FastAPI, non-root) ──► PostgreSQL
                                                                              │
                                                                              └── /metrics ──► Prometheus ──► Grafana

git push ──► GitHub Actions: pytest + frontend build ──► docker build ──► Trivy gate ──► GHCR (:<sha>)
                                     └──► commit the new SHA to helm/liftlog/values-eks.yaml ──► Argo CD ──► EKS
```

| Layer          | Technology                                                                                                                                |
|:---------------|:------------------------------------------------------------------------------------------------------------------------------------------|
| Frontend       | React 19, Vite 8, nginx (`nginxinc/nginx-unprivileged`)                                                                                   |
| Backend        | Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, `prometheus-fastapi-instrumentator`                                              |
| Database       | PostgreSQL 16                                                                                                                             |
| CI/CD          | GitHub Actions → GHCR, Trivy, GitOps with Argo CD                                                                                         |
| Infrastructure | Terraform: AWS VPC (2 public + 2 private subnets) and EKS 1.36, with EBS CSI driver and AWS Load Balancer Controller via EKS Pod Identity |
| Kubernetes     | Helm chart (`helm/liftlog`), HPA, ALB Ingress (`/` → frontend, `/api` → backend)                                                          |
| Observability  | kube-prometheus-stack, ServiceMonitor, Grafana dashboard as code                                                                          |

## Repository layout

```text
backend/        FastAPI app (app/), Alembic migrations, pytest suite
frontend/       React UI and nginx config
docker-compose.yml
.github/workflows/ci-cd.yml
terraform/      VPC + EKS (+ terraform.tfvars.example)
k8s/            namespace and default StorageClass
helm/liftlog/   Helm chart; values-eks.yaml is managed by CI (GitOps)
argocd/         Argo CD Application for EKS
monitoring/     kube-prometheus-stack values and the Grafana dashboard
troubleshooting/  deliberately broken manifests for practice
```

## Run locally

```bash
docker compose up --build
```

| URL                                                    |                                                               |
|:-------------------------------------------------------|:--------------------------------------------------------------|
| <http://localhost:3000>                                | LiftLog UI (on Windows with WSL, use `http://127.0.0.1:3000`) |
| <http://localhost:8000/docs>                           | API docs (Swagger UI)                                         |
| <http://localhost:8000/health> · `/ready` · `/metrics` | Liveness, readiness (checks the DB), Prometheus metrics       |

### Tests

```bash
cd backend
pip install -r requirements.txt
python -m pytest -v      # uses a throwaway SQLite database, never Postgres
```

## API

| Method | Path                           | Description                                                  |
|:-------|:-------------------------------|:-------------------------------------------------------------|
| GET    | `/api/exercises`               | List the exercise library                                    |
| POST   | `/api/exercises`               | Add an exercise (`409` on duplicate name)                    |
| PUT    | `/api/exercises/{id}`          | Update an exercise                                           |
| DELETE | `/api/exercises/{id}`          | Delete an unused exercise (`409` if it's in a workout)       |
| GET    | `/api/exercises/{id}/progress` | Top set, estimated 1RM and volume per workout (oldest first) |
| GET    | `/api/workouts`                | List workouts with their sets, newest first                  |
| POST   | `/api/workouts`                | Log a workout with nested `sets`                             |
| GET    | `/api/workouts/{id}`           | One workout                                                  |
| PUT    | `/api/workouts/{id}`           | Update a workout (`sets`, when given, replaces all sets)     |
| DELETE | `/api/workouts/{id}`           | Delete a workout                                             |
| GET    | `/api/stats`                   | 7-day totals, 30-day muscle-group volume, personal records   |

Example:

```bash
curl -X POST http://localhost:8000/api/workouts -H 'Content-Type: application/json' -d '{
  "title": "Push Day", "duration_min": 60,
  "sets": [{"exercise_id": 1, "reps": 5, "weight_kg": 100}, {"exercise_id": 1, "reps": 5, "weight_kg": 102.5, "rpe": 8.5}]
}'
```

## CI/CD and GitOps

On every push to `main`, [`.github/workflows/ci-cd.yml`](.github/workflows/ci-cd.yml):

1. **test**: `pytest` and the frontend production build.
2. **build-scan-push**: builds both images, fails on any fixable HIGH/CRITICAL CVE (Trivy), then pushes `ghcr.io/<owner>/liftlog-backend` and `liftlog-frontend` tagged with the **commit SHA** (and `latest`).
3. **update-gitops**: writes that SHA into [`helm/liftlog/values-eks.yaml`](helm/liftlog/values-eks.yaml) and commits it. Argo CD on EKS sees the commit and rolls the new images out. No cloud credentials are stored in CI.

**Live demo:** change something visible (e.g. the dashboard greeting in `frontend/src/main.jsx`), push, watch the Actions run go green and the `deploy: liftlog images <sha>` commit appear, then refresh the app as Argo CD rolls out the new pods.

## Infrastructure (Terraform)

[`terraform/`](terraform) provisions everything the app needs on AWS (region `ap-southeast-2`):

| Component | Details |
| :--- | :--- |
| VPC | `terraform-aws-modules/vpc` 6.7.3: `10.20.0.0/16`, **2 public + 2 private subnets** across 2 AZs, internet gateway, single NAT gateway, subnet tags for load balancers |
| EKS | `terraform-aws-modules/eks` 21.29.0: Kubernetes **1.36**, private nodes, public API endpoint, KMS-encrypted secrets, control-plane logs |
| Nodes | Managed node group of 2 × `m7i-flex.large` |
| Add-ons | vpc-cni, kube-proxy, coredns, eks-pod-identity-agent, **metrics-server** (HPA), **aws-ebs-csi-driver** (Postgres volume) |
| IAM for pods | **EKS Pod Identity** roles for the EBS CSI driver and the AWS Load Balancer Controller (no IAM OIDC provider needed) |

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars      # optional: override region / cluster name
terraform init
terraform plan -out main.tfplan                   # 64 resources
terraform apply main.tfplan
aws eks update-kubeconfig --region ap-southeast-2 --name liftlog-eks
```

Authentication uses `aws login` (short-lived credentials); no keys are stored in the repo.

## Kubernetes / Helm deployment

```bash
# 1. Bootstrap: namespace, default gp3 StorageClass, AWS Load Balancer Controller (turns the Ingress into an ALB)
kubectl apply -f k8s/namespace.yaml -f k8s/storageclass.yaml
helm repo add eks https://aws.github.io/eks-charts
helm install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system \
  --set clusterName=liftlog-eks --set serviceAccount.name=aws-load-balancer-controller \
  --set vpcId=$(terraform -chdir=terraform output -raw vpc_id) --set region=ap-southeast-2

# 2. Deploy LiftLog with Helm
helm upgrade --install liftlog ./helm/liftlog -n liftlog -f helm/liftlog/values-eks.yaml --wait
kubectl get pods,svc,ingress -n liftlog            # ALB address in the ingress ADDRESS column

# 3. Hand it over to Argo CD (GitOps): from now on every green pipeline run deploys automatically
kubectl create namespace argocd
kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl apply -f argocd/liftlog-application.yaml
```

The chart ([`helm/liftlog`](helm/liftlog)) deploys the backend and frontend (2 replicas each, HPA 2–6 on CPU for the backend), Postgres on a gp3 EBS volume, ClusterIP Services, an ALB Ingress (`/` → frontend, `/api` → backend) and a ServiceMonitor.

## Observability (Prometheus + Grafana)

| Piece | How |
| :--- | :--- |
| Metrics | The backend exposes Prometheus metrics at **`/metrics`** (`prometheus-fastapi-instrumentator`: request counts, latency histograms, process stats) |
| Prometheus + Grafana | `kube-prometheus-stack` with [`monitoring/prometheus-values.yaml`](monitoring/prometheus-values.yaml) (selects ServiceMonitors from every namespace) |
| Scraping | The chart's ServiceMonitor scrapes every backend pod every 15s |
| Dashboard | [`monitoring/liftlog-dashboard.yaml`](monitoring/liftlog-dashboard.yaml) is dashboard-as-code: targets UP, requests/s, workouts logged, memory, request rate and p95 latency by handler, pod CPU, responses by status |

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install monitoring prometheus-community/kube-prometheus-stack -n monitoring --create-namespace -f monitoring/prometheus-values.yaml
kubectl apply -f monitoring/liftlog-dashboard.yaml
kubectl port-forward -n monitoring svc/monitoring-grafana 13000:80                         # Grafana   → http://127.0.0.1:13000
kubectl port-forward -n monitoring svc/monitoring-kube-prometheus-prometheus 19090:9090    # Prometheus → http://127.0.0.1:19090/targets
```

## Tear-down

Delete in this order so nothing is left outside Terraform's state:

```bash
kubectl delete application liftlog -n argocd    # stop Argo CD from recreating resources
helm uninstall liftlog -n liftlog               # Ingress → ALB deleted, PVC → EBS volume deleted
helm uninstall monitoring -n monitoring
helm uninstall aws-load-balancer-controller -n kube-system
terraform -chdir=terraform destroy
```

> Cost while running: EKS control plane, a NAT gateway, 2 × `m7i-flex.large` and an ALB come to roughly US$0.45/hour.

## Known issues and limitations

- **Single user, no authentication.** All workouts belong to one implicit user; there's no login or multi-tenancy.
- **Demo database credentials.** The Postgres username and password are plain defaults (`liftlog`) in `docker-compose.yml` and `helm/liftlog/values.yaml`. A real deployment should take them from a Kubernetes Secret managed outside Git (External Secrets / AWS Secrets Manager).
- **In-cluster Postgres.** A single Postgres pod on one EBS volume: no replication, backups or failover. A production setup would use Amazon RDS.
- **HTTP only.** The ALB listens on port 80; HTTPS needs a domain and an ACM certificate.
- **Initial Helm install, then Argo CD.** The first deploy uses `helm upgrade --install`, then Argo CD adopts the release (`releaseName: liftlog`). `helm list` keeps showing revision 1 even though Argo CD now manages the resources.
- **GitOps commits.** The `update-gitops` job pushes a `deploy: liftlog images <sha>` commit to `main` after every green run. Pull before pushing to avoid non-fast-forward errors.
- **Postgres restarts on first start.** The backend may restart once or twice on first deploy while Postgres initialises. Kubernetes recovers it automatically.
- **Region and plan constraints.** The project runs on an AWS free-plan account limited to one Region (ap-southeast-2) and 5 vCPUs, hence 2 × `m7i-flex.large` nodes and EKS Pod Identity instead of IRSA (the account's service control policy blocks IAM OIDC providers).

## Evidence and presentation

- [`docs/evidence/`](docs/evidence/README.md): screenshots and write-ups for every grading module (tests, Docker, pipeline, Trivy, Terraform plan/apply/destroy, AWS console, Kubernetes, Prometheus, Grafana, Argo CD, GitOps demo).
- [`demo/`](demo): presentation slides (and the walkthrough video).
