# GCP VPS Instance Reference

## Current Instances

### gcp-vps2 (本机)
- **Hostname**: gcp-vps2
- **Instance ID**: 8425274972061862870
- **Project ID**: 40129528744
- **Zone**: us-central1-c
- **Machine**: e2-standard-2 (2 vCPU / 7.7 GiB RAM)
- **Internal IP**: 10.128.0.4
- **External IP**: 34.172.33.185
- **OS**: Ubuntu 25.10, kernel 6.17.0-1018-gcp
- **User**: caozuohua99 (uid=1001)
- **Key groups**: docker(987), luck-agent(990), ubuntu(1000)
- **sudo**: restricted to systemctl for luck-agent/luckclaw only
- **Hermes Gateway**: active + enabled + Linger=yes
- **Disk**: 28G total, ~12G available (58% used — monitor)

### instance-20260413-080555 (远程目标)
- **Instance ID**: (see gcloud)
- **Zone**: us-central1-c
- **Machine**: e2-micro (1 vCPU / 954 MiB RAM)
- **Internal IP**: 10.128.0.3
- **External IP**: 34.10.143.63
- **OS**: Ubuntu 25.10
- **SSH method**: `gcloud compute ssh instance-20260413-080555 --zone=us-central1-c --command='<cmd>'`
- **SSH keys**: `~/.ssh/google_compute_engine` works; `~/.ssh/id_ed25519` is REJECTED by server (despite being in known_hosts). Always use google_compute_engine key.
- **Service account**: 40129528744-compute@developer.gserviceaccount
- **Roles**: compute.instanceAdmin.v1, iam.serviceAccountUser
- **Installed tools**: rg, jq, htop
- **hermes-lite service**: systemd unit `hermes-lite`, runs as user caozuohua99, HERMES_HOME=~/.hermes-lite
- **hermes-lite memory limit**: MemoryMax=500MiB, TimeoutStopUSec=2min
- **luck-agent service**: systemd, user=luck-agent, venv at /opt/luck-agent/venv
- **luck-agent PID**: 4460 (as of 2026-06-11)
- **luck-agent memory.db**: /opt/luck-agent/memory.db (WAL mode)
- **luck-agent .env**: PKB at https://pkb-self.vercel.app/api/pkb (auth required)
- **luck-agent PKB status**: ✅ working (health 200, search returns results with `x-api-secret` header)
- **luck-agent memory.db**: cleaned — 407 rows (was 718), PKB user_profile has 5 curated entries

## Connection Notes

- Direct SSH with key file does NOT work — OS Login manages keys via metadata
- Always use `gcloud compute ssh`
- Service account needs both `compute.instanceAdmin.v1` AND `iam.serviceAccountUser` roles
